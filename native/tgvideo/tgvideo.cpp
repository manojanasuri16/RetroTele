/*
 * tgvideo.exe: RetroTele video helper (stage 1: local "video mirror").
 *
 *   ECam camera -> H.264 encoder -> H.264 decoder -> picture in a global chunk
 *
 * It needs MultimediaDD, which the Python app process cannot have, so it runs as
 * its own exe and shares frames with Python through the global RChunk
 * "tgvideo_frames" (layout: tgvshared.h, read by tgvdisp.pyd).
 *
 * Commands arrive on UDP 127.0.0.1:47012 (ASCII):
 *   S w h fps kbps cam   (re)start the pipeline
 *   C n                  switch to camera n, keep encoder/decoder, force a keyframe
 *   K                    request a keyframe
 *   D                    diagnostic ORDER SWEEP: which start orders let the decoder run while
 *                        the camera captures (log lines "order N: ..."), then restart
 *   Q                    quit
 * Status lines "T state cam w h capfps10 encfps10 decfps10 lat bps err drops enc dec"
 * go to 127.0.0.1:47011 once per second.
 *
 * The encoder/decoder set-up is the one the ENCSWEEP of tgvbench found working
 * (see native/vidbench). Every risky call is logged BEFORE it runs. Log:
 * E:\retrotele_videomirror.txt, falling back to C:\Data\ (appended, one open per
 * line so the Python side can write to the same file). The last line is always
 * "mirror end".
 */
#include <e32base.h>
#include <e32std.h>
#include <f32file.h>
#include <hal.h>
#include <es_sock.h>
#include <in_sock.h>
#include <ecam.h>
#include <mmf/devvideo/devvideoplay.h>
#include <mmf/devvideo/devvideorecord.h>
#include "tgvshared.h"
#include "clip_data.h"

// ---------------------------------------------------------------- log
static RFs gFs;
static TFileName gLogPath;
static TBool gLogOk = EFalse;

static void Log(TRefByValue<const TDesC8> aFmt, ...)
{
    if (!gLogOk) return;
    VA_LIST l;
    VA_START(l, aFmt);
    TBuf8<400> b;
    b.FormatList(aFmt, l);
    VA_END(l);
    b.Append('\n');
    RFile f;
    if (f.Open(gFs, gLogPath, EFileWrite | EFileShareAny) != KErrNone) return;
    TInt pos = 0;
    f.Seek(ESeekEnd, pos);
    f.Write(b);
    f.Flush();
    f.Close();
}

static void InitLog()
{
    _LIT(KCard, "E:\\retrotele_videomirror.txt");
    _LIT(KPhone, "C:\\Data\\retrotele_videomirror.txt");
    gFs.MkDirAll(KPhone);
    RFile f;
    gLogPath.Copy(KCard);
    TInt e = f.Open(gFs, gLogPath, EFileWrite | EFileShareAny);
    if (e != KErrNone) e = f.Create(gFs, gLogPath, EFileWrite | EFileShareAny);
    if (e != KErrNone) {
        gLogPath.Copy(KPhone);
        e = f.Open(gFs, gLogPath, EFileWrite | EFileShareAny);
        if (e != KErrNone) e = f.Create(gFs, gLogPath, EFileWrite | EFileShareAny);
    }
    if (e == KErrNone) { f.Close(); gLogOk = ETrue; }
}

static TInt gTickUs = 1000;
static TInt NowMs() { return (TInt)(((TInt64)User::NTickCount() * gTickUs) / 1000); }

// ---------------------------------------------------------------- waiting
static volatile TInt gQuit = 0;
class CPump : public CBase
{
public:
    static CPump* NewL()
    {
        CPump* p = new (ELeave) CPump;
        CleanupStack::PushL(p);
        p->iTimer = CPeriodic::NewL(CActive::EPriorityLow);
        CleanupStack::Pop();
        return p;
    }
    ~CPump() { delete iTimer; }
    void Run(TInt aMs, volatile TInt* aFlag)
    {
        iDeadline = aMs / 10;
        iTicks = 0;
        iFlag = aFlag;
        iTimer->Start(10000, 10000, TCallBack(Tick, this));
        iWait.Start();
        iTimer->Cancel();
    }
private:
    static TInt Tick(TAny* a)
    {
        CPump* s = (CPump*)a;
        if (++s->iTicks >= s->iDeadline || gQuit || (s->iFlag && *s->iFlag)) s->iWait.AsyncStop();
        return 0;
    }
    CPeriodic* iTimer;
    CActiveSchedulerWait iWait;
    TInt iDeadline, iTicks;
    volatile TInt* iFlag;
};
static CPump* gPump;

// ---------------------------------------------------------------- shared chunk
static RChunk gChunk;
static volatile TInt32* H = NULL;      // header words
static TUint8* gDec = NULL;            // decoded picture buffer
static TUint8* gPrev = NULL;           // camera preview buffer

static TInt CreateChunk()
{
    _LIT(KName, "tgvideo_frames");   // = TGV_CHUNK_NAME
    TInt e = gChunk.CreateGlobal(KName, TGV_CHUNK_SIZE, TGV_CHUNK_SIZE);
    if (e != KErrNone) return e;
    TUint8* base = gChunk.Base();
    Mem::FillZ(base, TGV_HDR_SIZE);
    H = (volatile TInt32*)base;
    gDec = base + TGV_DEC_OFF;
    gPrev = base + TGV_PREV_OFF;
    H[TGV_W_VERSION] = TGV_VERSION;
    H[TGV_W_MAGIC] = TGV_MAGIC;       // last: readers wait for the magic
    return KErrNone;
}
static void HSet(TInt i, TInt v) { if (H) H[i] = v; }

// ---------------------------------------------------------------- stats
struct TStats
{
    TInt iCap, iEnc, iDec, iBytes, iErrors, iDrops, iLat;
    TInt iCapPrev, iEncPrev, iDecPrev, iBytesPrev, iKeys;
    TInt iT0;
};
static TStats gSt;

static TInt Err() { gSt.iErrors++; HSet(TGV_W_ERRORS, gSt.iErrors); return gSt.iErrors; }

// ---------------------------------------------------------------- UDP status/command
static const TInt KMaxPkt = 256;
static RSocketServ gSs;
static RSocket gCmdSock, gTxSock;
static TBool gSockOk = EFalse;

class CSend : public CActive
{
public:
    CSend() : CActive(CActive::EPriorityStandard), iPtr(iBuf, 0, KMaxPkt) { CActiveScheduler::Add(this); }
    ~CSend() { Cancel(); }
    void Send(const TDesC8& aMsg)
    {
        if (IsActive() || !gSockOk) return;
        iPtr.Copy(aMsg.Left(KMaxPkt));
        iTo.SetAddress(INET_ADDR(127, 0, 0, 1));
        iTo.SetPort(47011);
        gTxSock.SendTo(iPtr, iTo, 0, iStatus);
        SetActive();
    }
    void RunL() {}
    void DoCancel() { gTxSock.CancelSend(); }
private:
    TUint8 iBuf[KMaxPkt];
    TPtr8 iPtr;
    TInetAddr iTo;
};
static CSend* gSend;
static void Status(TRefByValue<const TDesC8> aFmt, ...)
{
    if (!gSend) return;
    VA_LIST l;
    VA_START(l, aFmt);
    TBuf8<200> b;
    b.FormatList(aFmt, l);
    VA_END(l);
    gSend->Send(b);
}

// ---------------------------------------------------------------- helpers
static TInt HexVal(TUint8 c)
{
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}
static TInt ProfileLevel(const TDesC8& aMime)
{
    TInt p = aMime.Find(_L8("profile-level-id="));
    if (p < 0) return -1;
    p += 17;
    TInt v = 0;
    for (TInt i = 0; i < 6; i++) {
        if (p + i >= aMime.Length()) return -1;
        TInt h = HexVal(aMime[p + i]);
        if (h < 0) return -1;
        v = (v * 16) + h;
    }
    return v;
}
static TInt NeedLevel(TInt w, TInt h, TInt fps)
{
    static const TInt T[][3] = { { 0x0A, 99, 1485 }, { 0x0B, 396, 3000 }, { 0x0C, 396, 6000 },
                                 { 0x0D, 396, 11880 }, { 0x14, 396, 11880 }, { 0x15, 792, 19800 },
                                 { 0x1E, 1620, 40500 } };
    TInt mbs = ((w + 15) / 16) * ((h + 15) / 16);
    TInt mbps = mbs * fps;
    for (TUint i = 0; i < sizeof(T) / sizeof(T[0]); i++)
        if (mbs <= T[i][1] && mbps <= T[i][2]) return T[i][0];
    return 0x1E;
}
static CCompressedVideoFormat* PickFormat(const RPointerArray<CCompressedVideoFormat>& aList, TInt aNeed)
{
    CCompressedVideoFormat* best = NULL;
    TInt bestLvl = 0x7fff;
    for (TInt i = 0; i < aList.Count(); i++) {
        TInt pl = ProfileLevel(aList[i]->MimeType());
        if (pl < 0 || (pl >> 8) != 0x4280) continue;
        TInt lvl = pl & 0xFF;
        if (lvl >= aNeed && lvl < bestLvl) { bestLvl = lvl; best = aList[i]; }
    }
    if (!best && aList.Count() > 0) best = aList[0];
    return best;
}
static void ScanNal(const TDesC8& d, TBool& aVcl, TBool& aIdr, TBool& aSps, TBool& aPps)
{
    aVcl = aIdr = aSps = aPps = EFalse;
    TBool start = EFalse;
    const TUint8* p = d.Ptr();
    TInt len = d.Length();
    for (TInt i = 0; i + 3 < len; i++) {
        if (p[i] == 0 && p[i + 1] == 0 && p[i + 2] == 1) {
            start = ETrue;
            TInt t = p[i + 3] & 0x1F;
            if (t == 1 || t == 5) aVcl = ETrue;
            if (t == 5) aIdr = ETrue;
            if (t == 7) aSps = ETrue;
            if (t == 8) aPps = ETrue;
            i += 3;
        }
    }
    if (!start) aVcl = ETrue;
}

// latency ring: capture timestamp (us, unique) -> NowMs at capture
struct TLat { TInt64 iTs; TInt iMs; };
static TLat gLat[32];
static TInt gLatNext = 0;
static void LatNote(TInt64 aTs, TInt aMs) { gLat[gLatNext].iTs = aTs; gLat[gLatNext].iMs = aMs; gLatNext = (gLatNext + 1) & 31; }
static TInt LatFind(TInt64 aTs)
{
    for (TInt i = 0; i < 32; i++) if (gLat[i].iTs == aTs && aTs != 0) return gLat[i].iMs;
    return -1;
}

// ---------------------------------------------------------------- decoder
struct TDecOpt { TInt iUid, iOutPick, iPostProc, iSync, iBoost; };
static TDecOpt gDecOpt = { 0x10204bfc, -1, 0, 0, 0 };
static TInt gEncToDec = 1;          // encoder output goes to the decoder (not in the clip tests)

class CDec : public CBase, public MMMFDevVideoPlayObserver
{
public:
    CMMFDevVideoPlay* iPlay;
    THwDeviceId iDev;
    volatile TInt iInitDone, iInitErr, iFatal;
    TInt iPattern, iLayout;
    TInt iFirst;
    TBool iStarted;

    ~CDec() { if (iPlay && iStarted) iPlay->Stop(); delete iPlay; }

    void SetupL(TSize aSz, TInt aFps)
    {
        iInitDone = iInitErr = iFatal = 0;
        iFirst = 0; iPattern = 0; iLayout = 0; iStarted = EFalse;
        Log(_L8("step dec: CMMFDevVideoPlay::NewL"));
        iPlay = CMMFDevVideoPlay::NewL(*this);
        const TUid duid = TUid::Uid(gDecOpt.iUid);
        Log(_L8("step dec: SelectDecoderL 0x%08x"), duid.iUid);
        iDev = iPlay->SelectDecoderL(duid);
        Log(_L8("step dec: VideoDecoderInfoLC"));
        CVideoDecoderInfo* info = iPlay->VideoDecoderInfoLC(duid);
        TInt need = NeedLevel(aSz.iWidth, aSz.iHeight, aFps);
        CCompressedVideoFormat* cf = PickFormat(info->SupportedFormats(), need);
        if (!cf) User::Leave(KErrNotSupported);
        TBuf8<80> mm;
        mm.Copy(cf->MimeType().Left(78));
        Log(_L8("dec input mime=%S (need level 0x%02x)"), &mm, need);
        Log(_L8("step dec: SetInputFormatL"));
        iPlay->SetInputFormatL(iDev, *cf, EDuCodedPicture, EDuElementaryStream, ETrue);
        CleanupStack::PopAndDestroy(info);

        Log(_L8("step dec: GetOutputFormatListL"));
        RArray<TUncompressedVideoFormat> of;
        CleanupClosePushL(of);
        iPlay->GetOutputFormatListL(iDev, of);
        TInt pick = -1;
        TInt yuvSeen = 0;
        for (TInt i = 0; i < of.Count(); i++) {
            if (of[i].iDataFormat == EYuvRawData) {
                Log(_L8("  dec output[%d] yuv coeff=%d pattern=%d layout=%d"), i, (TInt)of[i].iYuvFormat.iCoefficients,
                    (TInt)of[i].iYuvFormat.iPattern, (TInt)of[i].iYuvFormat.iDataLayout);
                TInt pat = (TInt)of[i].iYuvFormat.iPattern, lay = (TInt)of[i].iYuvFormat.iDataLayout;
                if (gDecOpt.iOutPick >= 0) {
                    if (yuvSeen == gDecOpt.iOutPick) pick = i;
                } else if (pick < 0 && (lay == EYuvDataPlanar || lay == EYuvDataInterleavedLE ||
                                 lay == EYuvDataInterleavedBE || lay == EYuvDataSemiPlanar) && pat != 0)
                    pick = i;
                yuvSeen++;
            } else {
                Log(_L8("  dec output[%d] datafmt=0x%x rgb=0x%x"), i, (TInt)of[i].iDataFormat, (TInt)of[i].iRgbFormat);
            }
        }
        if (pick < 0 && of.Count() > 0) pick = 0;
        if (pick >= 0) {
            iPattern = (TInt)of[pick].iYuvFormat.iPattern;
            iLayout = (TInt)of[pick].iYuvFormat.iDataLayout;
            Log(_L8("step dec: SetOutputFormatL [%d] pattern=%d layout=%d"), pick, iPattern, iLayout);
            iPlay->SetOutputFormatL(iDev, of[pick]);
        }
        CleanupStack::PopAndDestroy(&of);
        HSet(TGV_W_DEC_PATTERN, iPattern);
        HSet(TGV_W_DEC_LAYOUT, iLayout);
        if (gDecOpt.iPostProc) {
            Log(_L8("step dec: SetPostProcessTypesL(0)"));
            TRAPD(e0, iPlay->SetPostProcessTypesL(iDev, 0));
            Log(_L8("dec SetPostProcessTypesL err=%d"), e0);
        }
        Log(_L8("step dec: SetVideoDestScreenL(false)"));
        TRAPD(e1, iPlay->SetVideoDestScreenL(EFalse));
        Log(_L8("dec SetVideoDestScreenL err=%d"), e1);
        iPlay->SynchronizeDecoding(gDecOpt.iSync ? ETrue : EFalse);
        if (gDecOpt.iBoost) { Log(_L8("dec: thread priority more (no SetPlaybackPriority in this SDK)")); RThread().SetPriority(EPriorityMore); }
        CMMFDevVideoPlay::TBufferOptions bo;
        iPlay->GetBufferOptions(bo);
        if (bo.iMaxInputBufferSize < 0x10000) bo.iMaxInputBufferSize = 0x10000;
        if (bo.iMinNumInputBuffers < 4) bo.iMinNumInputBuffers = 4;
        Log(_L8("step dec: SetBufferOptionsL"));
        TRAPD(e2, iPlay->SetBufferOptionsL(bo));
        Log(_L8("dec SetBufferOptionsL err=%d"), e2);
        Log(_L8("step dec: Initialize"));
        iPlay->Initialize();
        gPump->Run(10000, &iInitDone);
        Log(_L8("dec init done=%d err=%d fatal=%d"), (TInt)iInitDone, iInitErr, (TInt)iFatal);
        if (!iInitDone) User::Leave(KErrTimedOut);
        if (iInitErr) User::Leave(iInitErr);
        Log(_L8("step dec: CommitL"));
        TRAPD(e3, iPlay->CommitL());
        Log(_L8("dec CommitL err=%d"), e3);
        Log(_L8("step dec: Start"));
        iPlay->Start();
        iStarted = ETrue;
    }

    // one coded unit (Annex B) from the encoder
    void Write(const TDesC8& aD, TInt64 aTs)
    {
        if (!iStarted || iFatal) return;
        TVideoInputBuffer* b = NULL;
        TRAPD(err, b = iPlay->GetBufferL(aD.Length()));
        if (err || !b) { if (Err() <= 5) Log(_L8("dec GetBufferL err=%d b=%d"), err, b ? 1 : 0); return; }
        b->iData.Copy(aD);
        b->iOptions = TVideoInputBuffer::EPresentationTimestamp;
        b->iPresentationTimestamp = TTimeIntervalMicroSeconds(aTs);
        TRAPD(e2, iPlay->WriteCodedDataL(b));
        if (e2 && Err() <= 5) Log(_L8("dec WriteCodedDataL err=%d"), e2);
    }

    // MMMFDevVideoPlayObserver
    void MdvpoNewBuffers() {}
    void MdvpoReturnPicture(TVideoPicture*) {}
    void MdvpoSupplementalInformation(const TDesC8&, const TTimeIntervalMicroSeconds&, const TPictureId&) {}
    void MdvpoPictureLoss() {}
    void MdvpoPictureLoss(const TArray<TPictureId>&) {}
    void MdvpoSliceLoss(TUint, TUint, const TPictureId&) {}
    void MdvpoReferencePictureSelection(const TDesC8&) {}
    void MdvpoTimedSnapshotComplete(TInt, TPictureData*, const TTimeIntervalMicroSeconds&, const TPictureId&) {}
    void MdvpoNewPictures()
    {
        for (;;) {
            TVideoPicture* p = NULL;
            TRAPD(err, p = iPlay->NextPictureL());
            if (err || !p) { if (err) Err(); break; }
            TInt now = NowMs();
            gSt.iDec++;
            if (p->iData.iDataFormat == EYuvRawData && p->iData.iRawData) {
                TInt w = p->iData.iDataSize.iWidth, h = p->iData.iDataSize.iHeight;
                TInt len = p->iData.iRawData->Length();
                if (iFirst == 0) {
                    iFirst = 1;
                    Log(_L8("dec first picture: fmt=0x%x size=%dx%d len=%d opts=0x%x crop=%d,%d-%d,%d"), (TInt)p->iData.iDataFormat,
                        w, h, len, (TInt)p->iOptions, p->iCropRect.iTl.iX, p->iCropRect.iTl.iY,
                        p->iCropRect.iBr.iX, p->iCropRect.iBr.iY);
                }
                if (len > TGV_DEC_CAP) len = TGV_DEC_CAP;
                if (H && len > 0) {
                    H[TGV_W_DEC_SEQ]++;                 // odd: writing
                    Mem::Copy(gDec, p->iData.iRawData->Ptr(), len);
                    H[TGV_W_DEC_W] = w;
                    H[TGV_W_DEC_H] = h;
                    H[TGV_W_DEC_LEN] = len;
                    H[TGV_W_DEC_SEQ]++;                 // even: done
                    H[TGV_W_DEC_COUNT]++;
                }
            } else if (iFirst == 0) {
                iFirst = 1;
                Log(_L8("dec first picture is not raw YUV: fmt=0x%x"), (TInt)p->iData.iDataFormat);
                Err();
            }
            if (p->iOptions & TVideoPicture::ETimestamp) {
                TInt ms = LatFind(p->iTimestamp.Int64());
                if (ms >= 0) { gSt.iLat = now - ms; HSet(TGV_W_LAT_MS, gSt.iLat); }
            }
            iPlay->ReturnPicture(p);
        }
    }
    void MdvpoFatalError(TInt aErr) { iFatal = aErr; Err(); Log(_L8("dec fatal error %d"), aErr); }
    void MdvpoInitComplete(TInt aErr) { iInitErr = aErr; iInitDone = 1; }
    void MdvpoStreamEnd() {}
};
static CDec* gDecoder;

// ---------------------------------------------------------------- encoder
static const TInt KPool = 2;      // at most 2 frames in the encoder: later ones are dropped

class CEnc : public CBase, public MMMFDevVideoRecordObserver
{
public:
    CMMFDevVideoRecord* iRec;
    THwDeviceId iDev;
    TSize iSize;
    TInt iFrameBytes;
    TVideoPicture* iPic[KPool];
    TPtr8* iPtr[KPool];
    HBufC8* iBuf[KPool];
    TBool iBusy[KPool];
    volatile TInt iInitDone, iInitErr, iFatal;
    TBool iStarted;
    TInt iT0Ms;
    TInt iUnits;

    CEnc() {}
    ~CEnc()
    {
        if (iRec && iStarted) iRec->Stop();
        delete iRec;
        for (TInt i = 0; i < KPool; i++) { delete iPic[i]; delete iPtr[i]; delete iBuf[i]; }
    }

    void StartL(TSize aSz, TInt aFps, TInt aBitrateK)
    {
        iSize = aSz;
        iFrameBytes = aSz.iWidth * aSz.iHeight * 3 / 2;
        iFatal = 0; iInitDone = 0; iInitErr = 0; iUnits = 0; iStarted = EFalse;
        for (TInt i = 0; i < KPool; i++) {
            iBuf[i] = HBufC8::NewL(iFrameBytes);
            iBuf[i]->Des().SetLength(iFrameBytes);
            iPtr[i] = new (ELeave) TPtr8(iBuf[i]->Des());
            iPic[i] = new (ELeave) TVideoPicture;
            Mem::FillZ(iPic[i], sizeof(TVideoPicture));
            iPic[i]->iData.iDataFormat = EYuvRawData;
            iPic[i]->iData.iDataSize = aSz;
            iPic[i]->iData.iRawData = iPtr[i];
            iBusy[i] = EFalse;
        }
        const TUid uid = TUid::Uid(0x20001c13);
        Log(_L8("step enc: CMMFDevVideoRecord::NewL"));
        iRec = CMMFDevVideoRecord::NewL(*this);
        Log(_L8("step enc: SelectEncoderL 0x%08x"), uid.iUid);
        iDev = iRec->SelectEncoderL(uid);
        Log(_L8("step enc: VideoEncoderInfoLC"));
        CVideoEncoderInfo* info = iRec->VideoEncoderInfoLC(uid);

        TUncompressedVideoFormat fmt;
        TBool found = EFalse;
        const RArray<TUncompressedVideoFormat>& inf = info->SupportedInputFormats();
        for (TInt i = 0; i < inf.Count() && !found; i++) {
            if (inf[i].iDataFormat == EYuvRawData && inf[i].iYuvFormat.iDataLayout == EYuvDataPlanar &&
                (inf[i].iYuvFormat.iPattern & (EYuv420Chroma1 | EYuv420Chroma2 | EYuv420Chroma3))) {
                fmt = inf[i]; found = ETrue;
            }
        }
        if (!found) {
            Mem::FillZ(&fmt, sizeof(fmt));
            fmt.iDataFormat = EYuvRawData;
            fmt.iYuvFormat.iAspectRatioNum = 1;
            fmt.iYuvFormat.iAspectRatioDenom = 1;
            fmt.iYuvFormat.iCoefficients = (TYuvCoefficients)0x01000001;
        }
        Log(_L8("enc input fmt: found=%d coeff=%d pattern=%d layout=%d (list %d)"), (TInt)found,
            (TInt)fmt.iYuvFormat.iCoefficients, (TInt)fmt.iYuvFormat.iPattern, (TInt)fmt.iYuvFormat.iDataLayout, inf.Count());

        TInt need = NeedLevel(aSz.iWidth, aSz.iHeight, aFps);
        CCompressedVideoFormat* cf = PickFormat(info->SupportedOutputFormats(), need);
        if (!cf) User::Leave(KErrNotSupported);
        TBuf8<80> mm;
        mm.Copy(cf->MimeType().Left(78));
        Log(_L8("enc output mime=%S (need level 0x%02x)"), &mm, need);
        Log(_L8("step enc: SetInputFormatL %dx%d"), aSz.iWidth, aSz.iHeight);
        iRec->SetInputFormatL(iDev, fmt, aSz);
        Log(_L8("step enc: SetOutputFormatL"));
        iRec->SetOutputFormatL(iDev, *cf, EDuCodedPicture, EDuElementaryStream, EFalse);
        CleanupStack::PopAndDestroy(info);
        Log(_L8("step enc: SetSourceMemoryL %d fps const=1 realtime=1"), aFps);
        iRec->SetSourceMemoryL((TReal)aFps, ETrue, ETrue);
        Log(_L8("step enc: SetMinRandomAccessRate 0.5"));
        iRec->SetMinRandomAccessRate(0.5);
        Log(_L8("step enc: Initialize"));
        iRec->Initialize();
        gPump->Run(10000, &iInitDone);
        Log(_L8("enc init done=%d err=%d fatal=%d"), (TInt)iInitDone, iInitErr, (TInt)iFatal);
        if (!iInitDone) User::Leave(KErrTimedOut);
        if (iInitErr) User::Leave(iInitErr);

        TRateControlOptions ro;
        Mem::FillZ(&ro, sizeof(ro));
        ro.iControl = EBrControlStream;
        ro.iBitrate = aBitrateK * 1000;
        ro.iPictureQuality = 50;
        ro.iPictureRate = (TReal)aFps;
        ro.iQualityTemporalTradeoff = 0.5;
        ro.iLatencyQualityTradeoff = 0.0;
        Log(_L8("step enc: SetRateControlOptions %d kbit/s"), aBitrateK);
        iRec->SetRateControlOptions(0, ro);
        Log(_L8("step enc: CommitL"));
        TRAPD(e2, iRec->CommitL());
        Log(_L8("enc CommitL err=%d"), e2);
        Log(_L8("step enc: Start"));
        iRec->Start();
        iStarted = ETrue;
        iT0Ms = NowMs();
    }

    TInt64 TsNowUs() { return (TInt64)(NowMs() - iT0Ms + 1) * 1000; }

    // aTsUs: unique, increasing capture timestamp
    void Offer(const TUint8* aYuv, TInt aLen, TInt64 aTsUs)
    {
        if (!iStarted || iFatal || aLen < iFrameBytes) { gSt.iDrops++; return; }
        TInt k = -1;
        for (TInt i = 0; i < KPool; i++) if (!iBusy[i]) { k = i; break; }
        if (k < 0) { gSt.iDrops++; HSet(TGV_W_DROPS, gSt.iDrops); return; }
        Mem::Copy((TUint8*)iBuf[k]->Ptr(), aYuv, iFrameBytes);
        TVideoPicture* p = iPic[k];
        iPtr[k]->SetLength(iFrameBytes);
        p->iOptions = TVideoPicture::ETimestamp;
        p->iTimestamp = TTimeIntervalMicroSeconds(aTsUs);
        iBusy[k] = ETrue;
        TRAPD(err, iRec->WritePictureL(p));
        if (err) {
            iBusy[k] = EFalse;
            if (Err() <= 5) Log(_L8("enc WritePictureL err=%d"), err);
        }
    }

    void KeyFrame()
    {
        if (iRec && iStarted) { Log(_L8("enc: PictureLoss (keyframe request)")); iRec->PictureLoss(); }
    }

    // MMMFDevVideoRecordObserver
    void MdvroReturnPicture(TVideoPicture* aPic)
    {
        for (TInt i = 0; i < KPool; i++) if (iPic[i] == aPic) iBusy[i] = EFalse;
    }
    void MdvroSupplementalInfoSent() {}
    void MdvroNewBuffers()
    {
        if (!iRec) return;
        TInt n = iRec->NumDataBuffers();
        while (n-- > 0) {
            TVideoOutputBuffer* b = NULL;
            TRAPD(err, b = iRec->NextBufferL());
            if (err || !b) { if (err) Err(); break; }
            TBool vcl, idr, sps, pps;
            ScanNal(b->iData, vcl, idr, sps, pps);
            gSt.iBytes += b->iData.Length();
            iUnits++;
            if (iUnits <= 6)
                Log(_L8("enc unit %d: %d bytes vcl=%d idr=%d sps=%d pps=%d"), iUnits, b->iData.Length(), (TInt)vcl,
                    (TInt)idr, (TInt)sps, (TInt)pps);
            if (vcl) gSt.iEnc++;
            if (idr) { gSt.iKeys++; HSet(TGV_W_KEYS, gSt.iKeys); }
            if (gDecoder && gEncToDec) gDecoder->Write(b->iData, b->iCaptureTimestamp.Int64());
            iRec->ReturnBuffer(b);
        }
    }
    void MdvroFatalError(TInt aErr) { iFatal = aErr; Err(); Log(_L8("enc fatal error %d"), aErr); }
    void MdvroInitializeComplete(TInt aErr) { iInitErr = aErr; iInitDone = 1; }
    void MdvroStreamEnd() {}
};
static CEnc* gEncoder;

// ---------------------------------------------------------------- camera
class CCam : public CBase, public MCameraObserver
{
public:
    CCamera* iCam;
    volatile TInt iReserved, iPowered, iReserveErr, iPowerErr;
    TInt iIdx, iW, iH, iSIdx, iRIdx, iRate100;
    TBool iCapturing, iPoweredOn, iIsReserved;
    TInt iLastTs;
    TBool iVf;
    TUint8* iYuv;

    CCam() { iVf = EFalse; iYuv = NULL; }
    ~CCam() { Close(); }

    // Reserve + PowerOn + size/rate choice. aW/aH: wanted size (exact, else the largest smaller one).
    TInt Open(TInt aIdx, TInt aW, TInt aH, TInt aFps)
    {
        iIdx = aIdx;
        Log(_L8("step cam%d: NewL"), aIdx);
        TRAPD(ne, iCam = CCamera::NewL(*this, aIdx));
        if (ne != KErrNone || !iCam) { Log(_L8("cam%d NewL err=%d"), aIdx, ne); return ne ? ne : KErrNotFound; }
        TInt tries = 0;
        for (; tries < 4; tries++) {
            iReserved = 0; iReserveErr = 0;
            Log(_L8("step cam%d: Reserve (try %d)"), aIdx, tries + 1);
            iCam->Reserve();
            gPump->Run(5000, &iReserved);
            Log(_L8("cam%d reserve done=%d err=%d"), aIdx, (TInt)iReserved, iReserveErr);
            if (iReserved && iReserveErr == KErrNone) break;
            if (gQuit) return KErrAbort;
            if (iReserved && iReserveErr != KErrInUse) return iReserveErr;
            if (!iReserved) return KErrTimedOut;
            iReserved = 0;
            gPump->Run(500, &iReserved);       // wait a bit before retrying -14
        }
        if (tries >= 4) return KErrInUse;
        iIsReserved = ETrue;
        iPowered = 0; iPowerErr = 0;
        Log(_L8("step cam%d: PowerOn"), aIdx);
        iCam->PowerOn();
        gPump->Run(5000, &iPowered);
        Log(_L8("cam%d poweron done=%d err=%d"), aIdx, (TInt)iPowered, iPowerErr);
        if (!iPowered) return KErrTimedOut;
        if (iPowerErr) return iPowerErr;
        iPoweredOn = ETrue;
        TCameraInfo ci;
        iCam->CameraInfo(ci);
        // size: exact match, else the largest one not bigger than requested
        TInt best = -1, bestArea = 0, exact = -1;
        for (TInt s = 0; s < ci.iNumVideoFrameSizesSupported; s++) {
            TSize sz;
            iCam->EnumerateVideoFrameSizes(sz, s, CCamera::EFormatYUV420Planar);
            Log(_L8("  cam%d size[%d]=%dx%d"), aIdx, s, sz.iWidth, sz.iHeight);
            if (sz.iWidth == aW && sz.iHeight == aH) exact = s;
            TInt area = sz.iWidth * sz.iHeight;
            if (sz.iWidth <= aW && sz.iHeight <= aH && sz.iWidth <= TGV_MAX_W && sz.iHeight <= TGV_MAX_H &&
                area > bestArea) { best = s; bestArea = area; }
        }
        iSIdx = exact >= 0 ? exact : best;
        if (iSIdx < 0) return KErrNotSupported;
        TSize cs;
        iCam->EnumerateVideoFrameSizes(cs, iSIdx, CCamera::EFormatYUV420Planar);
        iW = cs.iWidth; iH = cs.iHeight;
        TInt rIdx = 0; TReal32 bestD = 1000;
        for (TInt r = 0; r < ci.iNumVideoFrameRatesSupported; r++) {
            TReal32 rate = 0;
            iCam->EnumerateVideoFrameRates(rate, r, CCamera::EFormatYUV420Planar, iSIdx);
            TReal32 d = rate > aFps ? rate - aFps : aFps - rate;
            if (rate > 0 && d < bestD) { bestD = d; rIdx = r; }
        }
        TReal32 chosen = 0;
        iCam->EnumerateVideoFrameRates(chosen, rIdx, CCamera::EFormatYUV420Planar, iSIdx);
        iRIdx = rIdx; iRate100 = (TInt)(chosen * 100);
        Log(_L8("cam%d: size idx=%d (%dx%d, wanted %dx%d) rate idx=%d (%d/100 fps)"), aIdx, iSIdx, iW, iH, aW, aH, iRIdx, iRate100);
        return KErrNone;
    }

    TInt Begin()
    {
        Log(_L8("step cam%d: PrepareVideoCaptureL"), iIdx);
        TRAPD(pe, iCam->PrepareVideoCaptureL(CCamera::EFormatYUV420Planar, iSIdx, iRIdx, 2, 1));
        Log(_L8("cam%d prepare err=%d"), iIdx, pe);
        if (pe) return pe;
        Log(_L8("step cam%d: StartVideoCapture"), iIdx);
        iCam->StartVideoCapture();
        iCapturing = ETrue;
        return KErrNone;
    }

    // viewfinder bitmap mode (instead of video capture): frames converted to YUV420 in software
    TInt BeginViewFinder()
    {
        iYuv = (TUint8*)User::Alloc(iW * iH * 3 / 2);
        if (!iYuv) return KErrNoMemory;
        TSize vs(iW, iH);
        Log(_L8("step cam%d: StartViewFinderBitmapsL %dx%d"), iIdx, iW, iH);
        TRAPD(ve, iCam->StartViewFinderBitmapsL(vs));
        Log(_L8("cam%d StartViewFinderBitmapsL err=%d (size %dx%d)"), iIdx, ve, vs.iWidth, vs.iHeight);
        if (ve) return ve;
        iVf = ETrue;
        iCapturing = ETrue;
        return KErrNone;
    }

    // one YUV420 planar frame of iW x iH: preview copy + encoder
    void Deliver(const TUint8* aYuv, TInt aLen)
    {
        TInt need = iW * iH * 3 / 2;
        if (aLen >= need && H) {
            H[TGV_W_PREV_SEQ]++;
            Mem::Copy(gPrev, aYuv, need);
            H[TGV_W_PREV_W] = iW;
            H[TGV_W_PREV_H] = iH;
            H[TGV_W_CAM] = iIdx;
            H[TGV_W_PREV_SEQ]++;
            H[TGV_W_PREV_COUNT]++;
            if (gEncoder) {
                TInt64 ts = gEncoder->TsNowUs();
                LatNote(ts, NowMs());
                gEncoder->Offer(aYuv, aLen, ts);
            }
        } else if (Err() <= 5) {
            Log(_L8("cam frame bad length %d (need %d)"), aLen, need);
        }
    }

    void Close()
    {
        if (!iCam) return;
        if (iVf) { Log(_L8("step cam%d: StopViewFinder"), iIdx); iCam->StopViewFinder(); iVf = EFalse; iCapturing = EFalse; }
        User::Free(iYuv); iYuv = NULL;
        if (iCapturing) { Log(_L8("step cam%d: StopVideoCapture"), iIdx); iCam->StopVideoCapture(); iCapturing = EFalse; }
        if (iPoweredOn) { Log(_L8("step cam%d: PowerOff"), iIdx); iCam->PowerOff(); iPoweredOn = EFalse; }
        if (iIsReserved) { Log(_L8("step cam%d: Release"), iIdx); iCam->Release(); iIsReserved = EFalse; }
        delete iCam;
        iCam = NULL;
    }

    // MCameraObserver
    void ReserveComplete(TInt aErr) { iReserveErr = aErr; iReserved = 1; }
    void PowerOnComplete(TInt aErr) { iPowerErr = aErr; iPowered = 1; }
    void ViewFinderFrameReady(CFbsBitmap& aB)
    {
        if (!iVf || !iYuv) return;
        gSt.iCap++;
        TSize bs = aB.SizeInPixels();
        TDisplayMode dm = aB.DisplayMode();
        if (bs.iWidth < iW || bs.iHeight < iH || (dm != EColor64K && dm != EColor16MU && dm != EColor16MA)) {
            if (Err() <= 3) Log(_L8("viewfinder bitmap %dx%d mode %d unusable"), bs.iWidth, bs.iHeight, (TInt)dm);
            return;
        }
        TInt stride = CFbsBitmap::ScanLineLength(bs.iWidth, dm);
        aB.LockHeap();
        const TUint8* src = (const TUint8*)aB.DataAddress();
        TUint8* yp = iYuv;
        TUint8* up = iYuv + iW * iH;
        TUint8* vp = up + (iW / 2) * (iH / 2);
        for (TInt y = 0; y < iH; y++) {
            const TUint8* row = src + y * stride;
            for (TInt x = 0; x < iW; x++) {
                TInt r, g, b;
                if (dm == EColor64K) {
                    TUint v = ((const TUint16*)row)[x];
                    r = (v >> 8) & 0xF8; g = (v >> 3) & 0xFC; b = (v << 3) & 0xF8;
                } else {
                    const TUint8* px = row + x * 4;
                    b = px[0]; g = px[1]; r = px[2];
                }
                *yp++ = (TUint8)((((66 * r + 129 * g + 25 * b + 128) >> 8)) + 16);
                if (((x | y) & 1) == 0) {
                    TInt u = ((-38 * r - 74 * g + 112 * b + 128) >> 8) + 128;
                    TInt vv = ((112 * r - 94 * g - 18 * b + 128) >> 8) + 128;
                    TInt ci = (y / 2) * (iW / 2) + x / 2;
                    up[ci] = (TUint8)(u < 0 ? 0 : (u > 255 ? 255 : u));
                    vp[ci] = (TUint8)(vv < 0 ? 0 : (vv > 255 ? 255 : vv));
                }
            }
        }
        aB.UnlockHeap();
        Deliver(iYuv, iW * iH * 3 / 2);
    }
    void ImageReady(CFbsBitmap* aB, HBufC8* aD, TInt) { delete aB; delete aD; }
    void FrameBufferReady(MFrameBuffer* aB, TInt aErr)
    {
        if (aErr != KErrNone) { if (Err() <= 5) Log(_L8("cam frame err=%d"), aErr); if (aB) aB->Release(); return; }
        if (!aB || !iCapturing) { if (aB) aB->Release(); return; }
        gSt.iCap++;
        TDesC8* d = NULL;
        TRAPD(err, d = aB->DataL(0));
        if (err || !d) { Err(); aB->Release(); return; }
        Deliver(d->Ptr(), d->Length());
        aB->Release();
    }
};
static CCam* gCam;

// ---------------------------------------------------------------- pipeline
static TInt gW = 176, gHt = 144, gFps = 15, gKbps = 128, gCamIdx = 0;

static void StopPipeline()
{
    Log(_L8("step: stop pipeline"));
    if (gCam) gCam->Close();
    delete gCam; gCam = NULL;
    delete gEncoder; gEncoder = NULL;
    delete gDecoder; gDecoder = NULL;
    HSet(TGV_W_ENC_OK, 0);
    HSet(TGV_W_DEC_OK, 0);
}

static void ResetStats()
{
    Mem::FillZ(&gSt, sizeof(gSt));
    gSt.iT0 = NowMs();
    HSet(TGV_W_ERRORS, 0); HSet(TGV_W_DROPS, 0); HSet(TGV_W_CAP_FPS, 0); HSet(TGV_W_ENC_FPS, 0);
    HSet(TGV_W_DEC_FPS, 0); HSet(TGV_W_LAT_MS, 0); HSet(TGV_W_BPS, 0); HSet(TGV_W_KEYS, 0);
}

static TInt gOrder = 0;      // start order: 0 camera opened first (as before), 1 decoder first, 2 decoder first + viewfinder

static TInt BuildDec(TSize sz)
{
    delete gDecoder; gDecoder = NULL;
    HSet(TGV_W_DEC_OK, 0);
    CDec* d = new CDec;
    if (!d) return KErrNoMemory;
    gDecoder = d;
    TRAPD(de, d->SetupL(sz, gFps));
    Log(_L8("dec setup err=%d"), de);
    if (de) {
        Err();
        delete gDecoder; gDecoder = NULL;
        if (de == KErrHardwareNotAvailable) { HSet(TGV_W_BLOCKED, 1); Log(_L8("decoder unavailable while capturing (-44)")); }
    } else {
        HSet(TGV_W_DEC_OK, 1);
        HSet(TGV_W_BLOCKED, 0);
    }
    return de;
}

static TInt BuildEnc(TSize sz)
{
    delete gEncoder; gEncoder = NULL;
    HSet(TGV_W_ENC_OK, 0);
    CEnc* e = new CEnc;
    if (!e) return KErrNoMemory;
    gEncoder = e;
    TRAPD(ee, e->StartL(sz, gFps, gKbps));
    Log(_L8("enc start err=%d"), ee);
    if (ee) { Err(); delete gEncoder; gEncoder = NULL; } else HSet(TGV_W_ENC_OK, 1);
    return ee;
}

static void BuildCodecs()
{
    TSize sz(gW, gHt);
    BuildDec(sz);
    BuildEnc(sz);
}

static TInt BeginCam(CCam* c)
{
    return gOrder == 2 ? c->BeginViewFinder() : c->Begin();
}

static void StartPipeline(TInt aW, TInt aH, TInt aFps, TInt aKbps, TInt aCam)
{
    StopPipeline();
    if (aW < 16 || aW > TGV_MAX_W) aW = 176;
    if (aH < 16 || aH > TGV_MAX_H) aH = 144;
    if (aFps < 1 || aFps > 30) aFps = 15;
    if (aKbps < 16 || aKbps > 2000) aKbps = 128;
    if (aCam < 0 || aCam > 1) aCam = 0;
    gW = aW; gHt = aH; gFps = aFps; gKbps = aKbps; gCamIdx = aCam;
    HSet(TGV_W_STATE, 0);
    HSet(TGV_W_ORDER, gOrder + 1);
    ResetStats();
    gEncToDec = 1;
    Log(_L8("pipeline start: %dx%d@%d %d kbit/s cam %d order %d"), gW, gHt, gFps, gKbps, gCamIdx, gOrder);
    if (gOrder > 0) BuildDec(TSize(gW, gHt));       // decoder before the camera is touched
    CCam* c = new CCam;
    if (!c) { Err(); return; }
    gCam = c;
    TInt e = c->Open(gCamIdx, gW, gHt, gFps);
    if (e != KErrNone) {
        Log(_L8("camera open failed err=%d"), e);
        Err();
        HSet(TGV_W_STATE, 3);
        delete gCam; gCam = NULL;
        return;
    }
    TBool sizeChanged = (c->iW != gW || c->iH != gHt);
    gW = c->iW; gHt = c->iH;
    HSet(TGV_W_CAM, gCamIdx);
    if (gOrder > 0 && !sizeChanged) BuildEnc(TSize(gW, gHt)); else BuildCodecs();
    e = BeginCam(c);
    if (e != KErrNone) { Err(); HSet(TGV_W_STATE, 3); return; }
    HSet(TGV_W_STATE, 1);
    Log(_L8("pipeline running %dx%d"), gW, gHt);
}

static void SwitchCamera(TInt aNew)
{
    if (aNew < 0 || aNew > 1) return;
    Log(_L8("switch camera %d -> %d"), gCamIdx, aNew);
    TInt old = gCamIdx;
    if (gCam) gCam->Close();
    delete gCam; gCam = NULL;
    HSet(TGV_W_STATE, 0);
    CCam* c = new CCam;
    if (!c) { Err(); return; }
    gCam = c;
    TInt e = c->Open(aNew, gW, gHt, gFps);
    if (e != KErrNone) {
        Log(_L8("camera %d open failed err=%d, going back to %d"), aNew, e, old);
        Err();
        delete gCam; gCam = NULL;
        c = new CCam;
        if (!c) return;
        gCam = c;
        e = c->Open(old, gW, gHt, gFps);
        if (e != KErrNone) { Log(_L8("camera %d reopen failed err=%d"), old, e); HSet(TGV_W_STATE, 3); return; }
        aNew = old;
    }
    gCamIdx = aNew;
    HSet(TGV_W_CAM, gCamIdx);
    if (c->iW != gW || c->iH != gHt) {
        Log(_L8("camera %d offers %dx%d instead of %dx%d: rebuilding codecs"), gCamIdx, c->iW, c->iH, gW, gHt);
        gW = c->iW; gHt = c->iH;
        BuildCodecs();
    } else if (gEncoder) {
        gEncoder->KeyFrame();
    }
    e = BeginCam(c);
    if (e != KErrNone) { Err(); HSet(TGV_W_STATE, 3); return; }
    HSet(TGV_W_STATE, 1);
    if (gEncoder) gEncoder->KeyFrame();
}

// ---------------------------------------------------------------- order sweep (command D)
// Which start orders let the hardware decoder run while the camera captures? Each variant is
// ~4 s at 176x144@15 and is torn down completely (plus 400 ms) before the next one.
static TInt gAuOff[64], gAuLen[64], gAuN = 0;
static TInt gAuNext = 0;
static TBuf8<160> gBoth;
static TInt gBothV[12];        // variant id (1..8) -> BOTH ok

static void ParseClip()
{
    const TInt len = sizeof(KClip);
    TInt acc = 0;
    gAuN = 0;
    for (TInt i = 0; i + 3 < len && gAuN < 64; i++) {
        if (KClip[i] == 0 && KClip[i + 1] == 0 && KClip[i + 2] == 1) {
            TInt t = KClip[i + 3] & 0x1F;
            if (t == 1 || t == 5) {
                // the unit ends where the next start code (with its leading zero) begins
                TInt e = len;
                for (TInt k = i + 3; k + 3 < len; k++)
                    if (KClip[k] == 0 && KClip[k + 1] == 0 && KClip[k + 2] == 1) { e = (KClip[k - 1] == 0 && k > 0) ? k - 1 : k; break; }
                gAuOff[gAuN] = acc; gAuLen[gAuN] = e - acc; gAuN++;
                acc = e;
                i = e - 1;
            }
        }
    }
    Log(_L8("clip: %d bytes, %d access units"), len, gAuN);
}

static TInt ClipTick(TAny*)
{
    if (!gDecoder || gAuN == 0) return 0;
    TInt k = gAuNext % gAuN;
    gDecoder->Write(TPtrC8(KClip + gAuOff[k], gAuLen[k]), (TInt64)(gAuNext + 1) * 66666);
    gAuNext++;
    return 0;
}

static TInt SynthFrame = 0;
static TInt SynthTick(TAny*)
{
    if (!gEncoder) return 0;
    TInt w = gW, h = gHt, n = w * h * 3 / 2;
    TUint8* b = (TUint8*)User::Alloc(n);
    if (!b) return 0;
    TInt f = SynthFrame++;
    for (TInt y = 0; y < h; y++) Mem::Fill(b + y * w, w, (TUint8)(40 + ((y * 2 + f * 5) & 127)));
    Mem::Fill(b + w * h, n - w * h, 128);
    TInt bx = (f * 4) % (w - 40), by = (f * 3) % (h - 40);
    for (TInt y = by; y < by + 32; y++) Mem::Fill(b + y * w + bx, 32, 235);
    TInt64 ts = gEncoder->TsNowUs();
    LatNote(ts, NowMs());
    gEncoder->Offer(b, n, ts);
    User::Free(b);
    return 0;
}

static void Settle(TInt aMs) { gPump->Run(aMs, NULL); }

static void SweepReset(TInt aEncToDec)
{
    StopPipeline();
    Settle(400);
    ResetStats();
    gDecOpt.iUid = 0x10204bfc; gDecOpt.iOutPick = -1; gDecOpt.iPostProc = 0; gDecOpt.iSync = 0; gDecOpt.iBoost = 0;
    gEncToDec = aEncToDec;
    gAuNext = 0;
    gW = 176; gHt = 144; gFps = 15; gKbps = 128;
}

// result line for a variant (camera/enc/decoder counters since the last mark)
static TInt gMarkCap, gMarkDec, gMarkUnits;
static void Mark() { gMarkCap = gSt.iCap; gMarkDec = gSt.iDec; gMarkUnits = gEncoder ? gEncoder->iUnits : 0; }
static void Result(TInt aId, const char* aSub, const char* aDesc, TInt aDecErr)
{
    TInt cam = gSt.iCap - gMarkCap, dec = gSt.iDec - gMarkDec;
    TInt units = (gEncoder ? gEncoder->iUnits : 0) - gMarkUnits;
    TBuf8<24> sub; sub.AppendFormat(_L8("%d%s"), aId, aSub);
    TBuf8<120> desc; desc.Copy(TPtrC8((const TUint8*)aDesc).Left(110));
    TBuf8<12> flag;
    if (cam > 0 && dec > 0) flag.Copy(_L8(" BOTH OK"));
    Log(_L8("order %S: %S: dec init err=%d, cam frames=%d, enc units=%d, decoded=%d%S"), &sub, &desc, aDecErr, cam, units, dec, &flag);
    if (cam > 0 && dec > 0) {
        if (aSub[0] == 0 || aSub[0] == 'a') gBothV[aId] = 1;
        if (gBoth.Length() < 140) { gBoth.Append(sub); gBoth.Append(' '); }
    }
}

static TInt NewDec()
{
    return BuildDec(TSize(176, 144));
}
static TInt OpenCam(TInt aMode)       // aMode 1 video capture, 2 viewfinder; returns first error
{
    CCam* c = new CCam;
    if (!c) return KErrNoMemory;
    gCam = c;
    TInt e = c->Open(0, 176, 144, 15);
    if (e != KErrNone) { Log(_L8("sweep: camera open err=%d"), e); return e; }
    e = (aMode == 2) ? c->BeginViewFinder() : c->Begin();
    Log(_L8("sweep: camera begin(mode %d) err=%d"), aMode, e);
    return e;
}

static void SweepL()
{
    TInt t0 = NowMs();
    HSet(TGV_W_SWEEP, 1);
    HSet(TGV_W_STATE, 5);
    Mem::FillZ(gBothV, sizeof(gBothV));
    gBoth.Zero();
    ParseClip();
    Log(_L8("order sweep start (176x144@15)"));
    CPeriodic* feed = CPeriodic::NewL(CActive::EPriorityStandard);
    CleanupStack::PushL(feed);
    CPeriodic* syn = CPeriodic::NewL(CActive::EPriorityStandard);
    CleanupStack::PushL(syn);
    const TInt kClipUs = 66666;

    // 1) decoder alone with the clip
    if (!gQuit) {
        SweepReset(0);
        TInt de = NewDec();
        Mark();
        if (!de) { feed->Start(1000, kClipUs, TCallBack(ClipTick, NULL)); Settle(4000); feed->Cancel(); }
        Result(1, "", "decoder alone, clip", de);
    }
    // 2) decoder first, then encoder, then camera video capture; clip keeps feeding
    if (!gQuit) {
        SweepReset(0);
        TInt de = NewDec();
        TInt ee = BuildEnc(TSize(176, 144));
        Mark();
        if (!de) feed->Start(1000, kClipUs, TCallBack(ClipTick, NULL));
        TInt ce = OpenCam(1);
        Log(_L8("order 2: enc err=%d cam err=%d"), ee, ce);
        Settle(4000);
        feed->Cancel();
        Result(2, "", "decoder first, encoder, camera video capture, clip fed", de);
    }
    // 3) decoder first, camera viewfinder bitmaps (software RGB->YUV) instead of video capture
    if (!gQuit) {
        SweepReset(0);
        TInt de = NewDec();
        TInt ee = BuildEnc(TSize(176, 144));
        Mark();
        if (!de) feed->Start(1000, kClipUs, TCallBack(ClipTick, NULL));
        TInt ce = OpenCam(2);
        Log(_L8("order 3: enc err=%d cam err=%d"), ee, ce);
        Settle(4000);
        feed->Cancel();
        Result(3, "", "decoder first, encoder, camera viewfinder bitmaps, clip fed", de);
    }
    // 4) camera video + encoder running, decoder created while they run (as the normal path did)
    if (!gQuit) {
        SweepReset(1);
        TInt ee = BuildEnc(TSize(176, 144));
        TInt ce = OpenCam(1);
        Log(_L8("order 4: enc err=%d cam err=%d, camera+encoder running"), ee, ce);
        Settle(1000);
        Mark();
        TInt de = NewDec();
        if (!de && gEncoder) gEncoder->KeyFrame();
        Settle(de ? 200 : 3500);
        Result(4, "a", "camera+encoder running, then decoder (default)", de);
        if (de) {
            RArray<TUid> u;
            CleanupClosePushL(u);
            TInt fe = KErrNoMemory;
            CDec* tmp = new CDec;
            if (tmp) {
                TRAP(fe, { tmp->iPlay = CMMFDevVideoPlay::NewL(*tmp); tmp->iPlay->FindDecodersL(_L8("video/H264"), 0, u, EFalse); });
                delete tmp;
            }
            Log(_L8("order 4b: FindDecodersL err=%d count=%d"), fe, u.Count());
            for (TInt i = 0; i < u.Count(); i++) Log(_L8("  decoder uid[%d]=0x%08x"), i, u[i].iUid);
            for (TInt i = 0; i < u.Count() && i < 4 && !gQuit; i++) {
                if (u[i].iUid == 0x10204bfc) continue;
                gDecOpt.iUid = u[i].iUid;
                Mark();
                TInt d2 = NewDec();
                Settle(d2 ? 200 : 3000);
                Result(4, "b", "other decoder uid while camera+encoder run", d2);
            }
            gDecOpt.iUid = 0x10204bfc;
            for (TInt o = 0; o < 3 && !gQuit; o++) {
                gDecOpt.iOutPick = o; gDecOpt.iPostProc = 1;
                Mark();
                TInt d3 = NewDec();
                Settle(d3 ? 200 : 3000);
                Result(4, (const char*)"c", "output entry + SetPostProcessTypesL(0)", d3);
                if (!d3) break;
            }
            gDecOpt.iOutPick = -1; gDecOpt.iPostProc = 0;
            CleanupStack::PopAndDestroy(&u);
            // retries
            Mark();
            TInt d4 = NewDec();
            TInt waited = 0;
            if (d4) { Settle(500); waited = 500; Log(_L8("order 4d: retry after 500 ms")); d4 = NewDec(); }
            if (d4) { Settle(1500); waited = 2000; Log(_L8("order 4d: retry after 2000 ms total")); d4 = NewDec(); }
            Log(_L8("order 4d: after %d ms wait dec init err=%d"), waited, d4);
            Settle(d4 ? 200 : 3000);
            Result(4, "d", "retry decoder after 500/1500 ms", d4);
        }
    }
    // 5) encoder + decoder, synthetic frames, no camera
    if (!gQuit) {
        SweepReset(1);
        TInt de = NewDec();
        TInt ee = BuildEnc(TSize(176, 144));
        Mark();
        SynthFrame = 0;
        syn->Start(1000, 66666, TCallBack(SynthTick, NULL));
        Settle(4000);
        syn->Cancel();
        Log(_L8("order 5: enc err=%d (no camera: BOTH does not apply)"), ee);
        Result(5, "", "encoder + decoder, synthetic frames, no camera", de);
    }
    // 6) camera capture only (no encoder), decoder created while capturing
    if (!gQuit) {
        SweepReset(0);
        TInt ce = OpenCam(1);
        Settle(800);
        Mark();
        TInt de = NewDec();
        if (!de) feed->Start(1000, kClipUs, TCallBack(ClipTick, NULL));
        Settle(de ? 200 : 4000);
        feed->Cancel();
        Log(_L8("order 6: cam err=%d"), ce);
        Result(6, "", "camera capture only, decoder created while capturing, clip", de);
    }
    // 7) decoder first, then camera capture, no encoder
    if (!gQuit) {
        SweepReset(0);
        TInt de = NewDec();
        Mark();
        if (!de) feed->Start(1000, kClipUs, TCallBack(ClipTick, NULL));
        TInt ce = OpenCam(1);
        Log(_L8("order 7: cam err=%d"), ce);
        Settle(4000);
        feed->Cancel();
        Result(7, "", "decoder first, camera capture, no encoder, clip", de);
    }
    // 8) camera+encoder running, decoder with SynchronizeDecoding(ETrue) and a higher thread priority
    if (!gQuit) {
        SweepReset(1);
        BuildEnc(TSize(176, 144));
        OpenCam(1);
        Settle(1000);
        gDecOpt.iSync = 1; gDecOpt.iBoost = 1;
        Mark();
        TInt de = NewDec();
        if (!de && gEncoder) gEncoder->KeyFrame();
        Settle(de ? 200 : 3500);
        Result(8, "", "camera+encoder running, then decoder with sync + thread priority", de);
    }
    CleanupStack::PopAndDestroy(2);
    SweepReset(1);
    TInt secs = (NowMs() - t0) / 1000;
    Log(_L8("order sweep end (%d s)"), secs);
    if (gBoth.Length() == 0) Log(_L8("order summary: BOTH ok for variants: none"));
    else Log(_L8("order summary: BOTH ok for variants %S"), &gBoth);
    // winner: 2 -> decoder first; 3 -> decoder first + viewfinder; 4a -> default order works
    TInt win = -1;
    if (gBothV[2]) win = 1; else if (gBothV[3]) win = 2; else if (gBothV[4]) win = 0;
    if (win >= 0) {
        gOrder = win;
        HSet(TGV_W_BLOCKED, 0);
        Log(_L8("order winner: start order %d (stored in header)"), gOrder);
    } else {
        HSet(TGV_W_BLOCKED, 1);
        Log(_L8("order winner: none: decoder unavailable while capturing"));
    }
    HSet(TGV_W_ORDER, gOrder + 1);
    HSet(TGV_W_SWEEP, 2);
    HSet(TGV_W_STATE, 2);
}

static void RunSweep()
{
    TInt sw = gW, sh = gHt, sf = gFps, sk = gKbps, sc = gCamIdx;
    TRAPD(e, SweepL());
    if (e) { Log(_L8("order sweep leave %d"), e); StopPipeline(); HSet(TGV_W_SWEEP, 2); HSet(TGV_W_STATE, 2); }
    // back to a running mirror with the best known order
    if (!gQuit) {
        StartPipeline(sw, sh, sf, sk, sc);
    }
}

// ---------------------------------------------------------------- commands
static TInt gBusy = 0;
static TBuf8<64> gPending;

static TInt ParseInts(const TDesC8& aS, TInt* aOut, TInt aMax)
{
    TInt n = 0, i = 0, len = aS.Length();
    while (i < len && n < aMax) {
        while (i < len && (aS[i] < '0' || aS[i] > '9') && aS[i] != '-') i++;
        if (i >= len) break;
        TInt sign = 1;
        if (aS[i] == '-') { sign = -1; i++; }
        TInt v = 0;
        while (i < len && aS[i] >= '0' && aS[i] <= '9') { v = v * 10 + (aS[i] - '0'); i++; }
        aOut[n++] = v * sign;
    }
    return n;
}

static void DoQuit()
{
    Log(_L8("quit: releasing"));
    HSet(TGV_W_STATE, 4);
    StopPipeline();
    CActiveScheduler::Stop();
}

static void Exec(const TDesC8& aCmd);
static void Command(const TDesC8& aCmd)
{
    if (aCmd.Length() == 0) return;
    if (aCmd[0] == 'Q') { gQuit = 1; if (!gBusy) DoQuit(); return; }
    if (gBusy) { gPending.Copy(aCmd.Left(63)); return; }
    gBusy = 1;
    Exec(aCmd);
    while (gPending.Length() > 0 && !gQuit) {
        TBuf8<64> p(gPending);
        gPending.Zero();
        Exec(p);
    }
    gBusy = 0;
    if (gQuit) DoQuit();
}
static void Exec(const TDesC8& aCmd)
{
    TInt v[6];
    Mem::FillZ(v, sizeof(v));
    TInt n = ParseInts(aCmd.Mid(1), v, 6);
    switch (aCmd[0]) {
    case 'S':
        Log(_L8("cmd S (%d args)"), n);
        if (n >= 5) StartPipeline(v[0], v[1], v[2], v[3], n >= 5 ? v[4] : 0);
        else Log(_L8("cmd S: need 5 numbers"));
        break;
    case 'C':
        Log(_L8("cmd C %d"), v[0]);
        SwitchCamera(v[0]);
        break;
    case 'D':
        Log(_L8("cmd D (order sweep)"));
        RunSweep();
        break;
    case 'K':
        Log(_L8("cmd K"));
        if (gEncoder) gEncoder->KeyFrame();
        break;
    default:
        Log(_L8("unknown command"));
    }
}

class CCmdRecv : public CActive
{
public:
    CCmdRecv() : CActive(CActive::EPriorityStandard), iPtr(iBuf, 0, KMaxPkt) { CActiveScheduler::Add(this); }
    ~CCmdRecv() { Cancel(); }
    void Start()
    {
        iPtr.Zero();
        gCmdSock.RecvFrom(iPtr, iFrom, 0, iStatus);
        SetActive();
    }
    void RunL()
    {
        TInt s = iStatus.Int();
        if (s == KErrNone) {
            TBuf8<64> c;
            c.Copy(iPtr.Left(63));
            Command(c);
        } else {
            Log(_L8("cmd recv err=%d"), s);
        }
        if (!gQuit) Start();
    }
    void DoCancel() { gCmdSock.CancelRecv(); }
private:
    TUint8 iBuf[KMaxPkt];
    TPtr8 iPtr;
    TInetAddr iFrom;
};

// once per second: stats to the chunk, a status line to Python, a log line every 5 s
static TInt gSecs = 0;
static TInt StatTick(TAny*)
{
    TInt now = NowMs();
    TInt el = now - gSt.iT0;
    if (el < 200) return 0;
    TInt cap = gSt.iCap - gSt.iCapPrev, enc = gSt.iEnc - gSt.iEncPrev, dec = gSt.iDec - gSt.iDecPrev;
    TInt bytes = gSt.iBytes - gSt.iBytesPrev;
    gSt.iCapPrev = gSt.iCap; gSt.iEncPrev = gSt.iEnc; gSt.iDecPrev = gSt.iDec; gSt.iBytesPrev = gSt.iBytes;
    gSt.iT0 = now;
    TInt capF = (TInt)((TInt64)cap * 10000 / el), encF = (TInt)((TInt64)enc * 10000 / el),
         decF = (TInt)((TInt64)dec * 10000 / el), bps = (TInt)((TInt64)bytes * 1000 / el);
    HSet(TGV_W_CAP_FPS, capF); HSet(TGV_W_ENC_FPS, encF); HSet(TGV_W_DEC_FPS, decF); HSet(TGV_W_BPS, bps);
    HSet(TGV_W_ERRORS, gSt.iErrors); HSet(TGV_W_DROPS, gSt.iDrops);
    TInt st = H ? H[TGV_W_STATE] : 0;
    Status(_L8("T %d %d %d %d %d %d %d %d %d %d %d %d %d"), st, gCamIdx, gW, gHt, capF, encF, decF, gSt.iLat, bps,
           gSt.iErrors, gSt.iDrops, H ? (TInt)H[TGV_W_ENC_OK] : 0, H ? (TInt)H[TGV_W_DEC_OK] : 0);
    if (++gSecs % 5 == 0)
        Log(_L8("stats: cap=%d.%d enc=%d.%d dec=%d.%d fps lat=%d ms %d B/s err=%d drops=%d keys=%d"), capF / 10, capF % 10,
            encF / 10, encF % 10, decF / 10, decF % 10, gSt.iLat, bps, gSt.iErrors, gSt.iDrops, gSt.iKeys);
    return 0;
}

static void RunL()
{
    gSt.iT0 = NowMs();
    Log(_L8("step: CActiveScheduler"));
    CActiveScheduler* sch = new (ELeave) CActiveScheduler;
    CleanupStack::PushL(sch);
    CActiveScheduler::Install(sch);
    gPump = CPump::NewL();
    CleanupStack::PushL(gPump);

    Log(_L8("step: chunk %s"), TGV_CHUNK_NAME);
    TInt ce = CreateChunk();
    Log(_L8("chunk create err=%d size=%d"), ce, (TInt)TGV_CHUNK_SIZE);
    User::LeaveIfError(ce);

    Log(_L8("step: sockets"));
    User::LeaveIfError(gSs.Connect());
    User::LeaveIfError(gCmdSock.Open(gSs, KAfInet, KSockDatagram, KProtocolInetUdp));
    TInetAddr local;
    local.SetAddress(INET_ADDR(127, 0, 0, 1));
    local.SetPort(47012);
    TInt be = gCmdSock.Bind(local);
    Log(_L8("cmd socket bind err=%d"), be);
    User::LeaveIfError(be);
    User::LeaveIfError(gTxSock.Open(gSs, KAfInet, KSockDatagram, KProtocolInetUdp));
    gSockOk = ETrue;
    gSend = new (ELeave) CSend;
    CleanupStack::PushL(gSend);
    CCmdRecv* rx = new (ELeave) CCmdRecv;
    CleanupStack::PushL(rx);
    rx->Start();
    CPeriodic* tick = CPeriodic::NewL(CActive::EPriorityStandard);
    CleanupStack::PushL(tick);
    tick->Start(1000000, 1000000, TCallBack(StatTick, NULL));

    HSet(TGV_W_STATE, 2);
    Status(_L8("T hello"));
    Log(_L8("ready, waiting for commands on 127.0.0.1:47012"));
    CActiveScheduler::Start();

    Log(_L8("scheduler stopped"));
    tick->Cancel();
    CleanupStack::PopAndDestroy(3);          // tick, rx, gSend
    gSend = NULL;
    gCmdSock.Close();
    gTxSock.Close();
    gSockOk = EFalse;
    gSs.Close();
    CleanupStack::PopAndDestroy(2);          // gPump, sch
    gPump = NULL;
}

GLDEF_C TInt E32Main()
{
    CTrapCleanup* cleanup = CTrapCleanup::New();
    gFs.Connect();
    InitLog();
    TInt p = 0;
    if (HAL::Get(HAL::ENanoTickPeriod, p) == KErrNone && p > 0) gTickUs = p;
    Log(_L8("mirror start"));
    TRAPD(err, RunL());
    if (err) Log(_L8("fatal err=%d"), err);
    StopPipeline();
    if (H) H[TGV_W_STATE] = 4;
    gChunk.Close();
    Log(_L8("mirror end"));
    gFs.Close();
    delete cleanup;
    return err;
}
