/*
 * tgcallaudio.exe: audio engine for Telegram calls. VoIP Audio Services
 * (PCM16, 8 kHz mono, 20 ms = 160 samples = 320 bytes) <-> Opus <-> UDP on
 * localhost. Uplink packets go to 127.0.0.1:47001, packets to play arrive on
 * 127.0.0.1:47002; a lone 'Q' datagram ends the program. Command line =
 * seconds (default 60, max 3600). Stats: E:\retrotele_callaudio.txt.
 * Opus runs on the main thread (exe has a 64 KB stack).
 */
#include <e32base.h>
#include <e32std.h>
#include <f32file.h>
#include <es_sock.h>
#include <in_sock.h>
#include <VoIPUtilityFactory.h>
#include <VoIPDownlinkStream.h>
#include <VoIPUplinkStream.h>
#include <VoIPDataBuffer.h>
#include <VoIPFormatIntfc.h>
#include <libc/stdlib.h>
#include "opus.h"

const TInt KFrameBytes = 320;
const TInt KFrameSamples = 160;
const TInt KMaxPkt = 1500;
const TInt KRingSize = 30;
const TInt KPrefill = 6;       /* 120 ms: the RetroTele bridge delivers in bursts */
const TInt KPortOut = 47001;
const TInt KPortIn = 47002;

static TInt NowUs()
{
    TTime t;
    t.HomeTime();
    return (TInt)(t.Int64() % 2000000000);
}

class CRunner;

// Active object doing one UDP receive at a time.
class CRecv : public CActive
{
public:
    CRecv(CRunner& aOwner) : CActive(CActive::EPriorityStandard), iOwner(aOwner), iPtr(iBuf, 0, KMaxPkt)
    { CActiveScheduler::Add(this); }
    ~CRecv() { Cancel(); }
    void Start(RSocket& aSock)
    {
        iSock = &aSock;
        iPtr.Zero();
        aSock.RecvFrom(iPtr, iFrom, 0, iStatus);
        SetActive();
    }
    void RunL();
    void DoCancel() { if (iSock) iSock->CancelRecv(); }
private:
    CRunner& iOwner;
    RSocket* iSock;
    TUint8 iBuf[KMaxPkt];
    TPtr8 iPtr;
    TSockAddr iFrom;
};

// Active object sending one UDP datagram at a time (drops if busy).
class CSend : public CActive
{
public:
    CSend() : CActive(CActive::EPriorityStandard), iPtr(iBuf, 0, KMaxPkt)
    { CActiveScheduler::Add(this); }
    ~CSend() { Cancel(); }
    TBool Send(RSocket& aSock, const TInetAddr& aTo, const TUint8* aData, TInt aLen)
    {
        if (IsActive()) return EFalse;
        iSock = &aSock;
        iTo = aTo;
        Mem::Copy(iBuf, aData, aLen);
        iPtr.Set(iBuf, aLen, KMaxPkt);
        aSock.SendTo(iPtr, iTo, 0, iStatus);
        SetActive();
        return ETrue;
    }
    void RunL() { iResult = iStatus.Int(); }
    void DoCancel() { if (iSock) iSock->CancelSend(); }
    TInt iResult;
private:
    RSocket* iSock;
    TInetAddr iTo;
    TUint8 iBuf[KMaxPkt];
    TPtr8 iPtr;
};

class CRunner : public CBase, public MVoIPDownlinkObserver,
                public MVoIPUplinkObserver, public MVoIPFormatObserver
{
public:
    CRunner(TInt aSeconds) : iSeconds(aSeconds) {}
    ~CRunner()
    {
        delete iTimer;
        if (iUp) { iUp->Stop(); iUp->Close(); }
        if (iDn) { iDn->Stop(); iDn->Close(); }
        delete iUpFmt;
        delete iDnFmt;
        delete iUp;
        delete iDn;
        delete iPlayBuf;
        delete iFactory;
        iFormats.Close();
        delete iRecv;
        delete iSend;
        iSock.Close();
        iSs.Close();
        if (iEnc) opus_encoder_destroy(iEnc);
        if (iDec) opus_decoder_destroy(iDec);
        delete [] iRing;
        Write(_L8("tgcallaudio end\n"));
        iFile.Close();
        iFs.Close();
    }
    void StartL()
    {
        User::LeaveIfError(iFs.Connect());
        _LIT(KCard, "E:\\retrotele_callaudio.txt");
        _LIT(KPhone, "C:\\Data\\retrotele_callaudio.txt");
        TInt e = iFile.Open(iFs, KCard, EFileWrite | EFileShareAny);
        if (e == KErrNone) {
            TInt sz = 0;
            iFile.Size(sz);
            iFile.Seek(ESeekEnd, sz);
        } else if (iFile.Replace(iFs, KCard, EFileWrite | EFileShareAny) != KErrNone) {
            e = iFile.Open(iFs, KPhone, EFileWrite | EFileShareAny);
            if (e == KErrNone) {
                TInt sz = 0;
                iFile.Size(sz);
                iFile.Seek(ESeekEnd, sz);
            } else {
                User::LeaveIfError(iFile.Replace(iFs, KPhone, EFileWrite | EFileShareAny));
            }
        }
        Write(_L8("tgcallaudio start\n"));
        iRing = new TUint8[KRingSize * KMaxPkt];
        if (!iRing) User::Leave(KErrNoMemory);
        Mem::FillZ(iRingLen, sizeof(iRingLen));
        iTimer = CPeriodic::NewL(CActive::EPriorityStandard);
        iTimer->Start(1000000, 1000000, TCallBack(Tick, this));
        SetupOpus();
        SetupNet();
        SetupAudio();
    }
    TBool Check(const TDesC8& aStep, TInt aErr)
    {
        if (aErr != KErrNone) {
            iErrors++;
            iLast = aErr;
            if (iFirstErrs < 8) {
                iFirstErrs++;
                TBuf8<96> b;
                b.Format(_L8("error %S %d\n"), &aStep, aErr);
                Write(b);
            }
            return EFalse;
        }
        return ETrue;
    }
    void SetupOpus()
    {
        int err = 0;
        iEnc = opus_encoder_create(8000, 1, OPUS_APPLICATION_VOIP, &err);
        if (!iEnc || err != OPUS_OK) { Check(_L8("EncCreate"), err ? err : KErrNoMemory); iEnc = NULL; return; }
        opus_encoder_ctl(iEnc, OPUS_SET_BITRATE(12000));
        opus_encoder_ctl(iEnc, OPUS_SET_COMPLEXITY(2));
        opus_encoder_ctl(iEnc, OPUS_SET_VBR(0));
        opus_encoder_ctl(iEnc, OPUS_SET_INBAND_FEC(0));
        opus_encoder_ctl(iEnc, OPUS_SET_SIGNAL(OPUS_SIGNAL_VOICE));
        iDec = opus_decoder_create(8000, 1, &err);
        if (!iDec || err != OPUS_OK) { Check(_L8("DecCreate"), err ? err : KErrNoMemory); iDec = NULL; }
    }
    void SetupNet()
    {
        if (!Check(_L8("SocketServ"), iSs.Connect())) return;
        if (!Check(_L8("SocketOpen"), iSock.Open(iSs, KAfInet, KSockDatagram, KProtocolInetUdp))) return;
        TInetAddr local;
        local.SetAddress(INET_ADDR(127, 0, 0, 1));
        local.SetPort(KPortIn);
        if (!Check(_L8("SocketBind"), iSock.Bind(local))) return;
        iSock.SetOpt(KSORecvBuf, KSOLSocket, 32768);   /* queue bursts instead of dropping */
        iSock.SetOpt(KSOSendBuf, KSOLSocket, 16384);
        iDest.SetAddress(INET_ADDR(127, 0, 0, 1));
        iDest.SetPort(KPortOut);
        iSend = new CSend;
        iRecv = new CRecv(*this);
        if (!iSend || !iRecv) { Check(_L8("NetAlloc"), KErrNoMemory); return; }
        iRecv->Start(iSock);
        iNetOk = ETrue;
    }
    void SetupAudio()
    {
        if (!Check(_L8("CreateFactory"), CVoIPUtilityFactory::CreateFactory(iFactory))) return;
        if (!Check(_L8("CreateDownlink"), iFactory->CreateDownlinkStream(TVersion(1, 0, 0),
                   CVoIPUtilityFactory::EVoIPCall, iDn))) return;
        if (!Check(_L8("CreateUplink"), iFactory->CreateUplinkStream(TVersion(1, 0, 0),
                   CVoIPUtilityFactory::EVoIPCall, iUp))) return;
        if (!Check(_L8("CreateBuffer"), iFactory->CreateBuffer(iPlayBuf,
                   CVoIPDataBuffer::EStandard))) return;
        if (!Check(_L8("DnSetFormat"), iDn->SetFormat(EPCM16, iDnFmt))) return;
        Check(_L8("DnFmtObserver"), iDnFmt->SetObserver(*this));
        if (!Check(_L8("UpSetFormat"), iUp->SetFormat(EPCM16, iUpFmt))) return;
        Check(_L8("UpFmtObserver"), iUpFmt->SetObserver(*this));
        if (!Check(_L8("DnOpen"), iDn->Open(*this))) return;
        Check(_L8("UpOpen"), iUp->Open(*this));
    }
    void MaybeStart()
    {
        if (!iDnOpen || !iUpOpen || iStarted) return;
        iStarted = ETrue;
        TInt mv = 0, mg = 0;
        Check(_L8("SetAudioDevice"), iDn->SetAudioDevice(CVoIPAudioDownlinkStream::ELoudSpeaker));
        iDn->GetMaxVolume(mv);
        Check(_L8("SetVolume"), iDn->SetVolume(mv * 70 / 100));
        iUp->GetMaxGain(mg);
        Check(_L8("SetGain"), iUp->SetGain(mg));
        if (!Check(_L8("DnStart"), iDn->Start())) return;
        Check(_L8("UpStart"), iUp->Start());
    }
    // ---- network receive
    void Received(TInt aErr, const TDesC8& aData)
    {
        if (aErr == KErrNone) {
            TInt n = aData.Length();
            if (n == 1 && aData[0] == 'Q') {
                CActiveScheduler::Stop();
                return;
            }
            if (n > 0 && n <= KMaxPkt) {
                iRecvPkts++;
                if (iRingCount == KRingSize) { // drop oldest
                    iRingHead = (iRingHead + 1) % KRingSize;
                    iRingCount--;
                }
                TInt slot = (iRingHead + iRingCount) % KRingSize;
                Mem::Copy(iRing + slot * KMaxPkt, aData.Ptr(), n);
                iRingLen[slot] = n;
                iRingCount++;
                iEverRecv = ETrue;
            }
        } else {
            Check(_L8("RecvFrom"), aErr);
            if (aErr == KErrCancel || aErr == KErrAbort) return;
        }
        iRecv->Start(iSock);
    }
    // ---- MVoIPDownlinkObserver
    void FillBuffer(const CVoIPAudioDownlinkStream&, CVoIPDataBuffer* aBuffer)
    {
        TPtr8 p(NULL, 0);
        aBuffer->GetPayloadPtr(p);
        TInt n = p.MaxLength() < KFrameBytes ? (p.MaxLength() & ~1) : KFrameBytes;
        p.SetLength(n);
        TInt16* pcm = (TInt16*)p.Ptr();
        TInt samples = n / 2;
        if (samples > KFrameSamples) samples = KFrameSamples;
        Mem::FillZ(pcm, n);
        if (!iPlaying && iRingCount >= KPrefill) { iPlaying = ETrue; iPlc = 0; }
        if (iPlaying && iDec) {
            TInt t0 = NowUs();
            TInt r;
            if (iRingCount > 0) {
                r = opus_decode(iDec, iRing + iRingHead * KMaxPkt, iRingLen[iRingHead],
                                pcm, KFrameSamples, 0);
                iRingHead = (iRingHead + 1) % KRingSize;
                iRingCount--;
                iPlc = 0;
            } else {
                iUnderruns++;
                iPlc++;
                if (iEverRecv) {
                    r = opus_decode(iDec, NULL, 0, pcm, KFrameSamples, 0);
                    iPlcFrames++;
                } else {
                    r = 0;
                }
                if (iPlc >= 5) iPlaying = EFalse; // rebuild the prefill
            }
            iDecUs += NowUs() - t0;
            if (r > 0) iDecFrames++;
            else if (r < 0) Check(_L8("Decode"), r);
        }
        for (TInt i = 0; i < samples; i++) {
            TInt a = pcm[i] < 0 ? -pcm[i] : pcm[i];
            if (a > iPeakOut) iPeakOut = a;
        }
        iPlayBuf->SetPayloadPtr(p);
        TInt err = iDn->BufferFilled(iPlayBuf);
        if (err != KErrNone) Check(_L8("BufferFilled"), err);
    }
    void Event(const CVoIPAudioDownlinkStream&, TInt aType, TInt aErr)
    {
        if (aType == MVoIPDownlinkObserver::KOpenComplete) {
            if (aErr == KErrNone) iDnOpen = ETrue; else Check(_L8("DnOpenComplete"), aErr);
            MaybeStart();
        } else if (aType == MVoIPDownlinkObserver::KDownlinkError) {
            Check(_L8("DnError"), aErr ? aErr : -1);
        }
    }
    // ---- MVoIPUplinkObserver
    void EmptyBuffer(const CVoIPAudioUplinkStream&, CVoIPDataBuffer* aBuffer)
    {
        TPtr8 p(NULL, 0);
        aBuffer->GetPayloadPtr(p);
        TInt n = p.Length() & ~1;
        const TInt16* s = (const TInt16*)p.Ptr();
        for (TInt i = 0; i < n / 2; i++) {
            TInt a = s[i] < 0 ? -s[i] : s[i];
            if (a > iPeakIn) iPeakIn = a;
        }
        if (n >= KFrameBytes && iEnc) {
            TUint8 pkt[KMaxPkt];
            TInt t0 = NowUs();
            TInt r = opus_encode(iEnc, s, KFrameSamples, pkt, KMaxPkt);
            iEncUs += NowUs() - t0;
            if (r > 0) {
                iEncFrames++;
                if (iNetOk) {
                    if (iSend->Send(iSock, iDest, pkt, r)) iSentPkts++;
                    else Check(_L8("SendBusy"), KErrInUse);
                }
            } else {
                Check(_L8("Encode"), r ? r : -1);
            }
        }
        TInt err = iUp->BufferEmptied(aBuffer);
        if (err != KErrNone) Check(_L8("BufferEmptied"), err);
    }
    void Event(const CVoIPAudioUplinkStream&, TInt aType, TInt aErr)
    {
        if (aType == MVoIPUplinkObserver::KOpenComplete) {
            if (aErr == KErrNone) iUpOpen = ETrue; else Check(_L8("UpOpenComplete"), aErr);
            MaybeStart();
        } else if (aType == MVoIPUplinkObserver::KUplinkError) {
            Check(_L8("UpError"), aErr ? aErr : -1);
        }
    }
    void Event(const CVoIPFormatIntfc&, TInt) {}

    static TInt Tick(TAny* aSelf)
    {
        ((CRunner*)aSelf)->DoTick();
        return 0;
    }
    void DoTick()
    {
        iTicks++;
        TInt avg = iEncFrames > iLastEnc ? iEncUs / (iEncFrames - iLastEnc) : 0;
        TBuf8<320> line;
        line.Format(_L8("t %d enc_frames %d sent_pkts %d dec_frames %d recv_pkts %d plc %d "
                        "underruns %d jitter_depth %d enc_us_avg %d mic_peak %d spk_peak %d "
                        "errors %d last %d\n"),
                    iTicks, iEncFrames, iSentPkts, iDecFrames, iRecvPkts, iPlcFrames,
                    iUnderruns, iRingCount, avg, iPeakIn, iPeakOut, iErrors, iLast);
        iLastEnc = iEncFrames;
        iEncUs = 0;
        iPeakIn = 0;
        iPeakOut = 0;
        Write(line);
        if (iTicks >= iSeconds) CActiveScheduler::Stop();
    }
    void Write(const TDesC8& aText)
    {
        iFile.Write(aText);
        iFile.Flush();
    }
private:
    TInt iSeconds;
    TInt iTicks;
    RFs iFs;
    RFile iFile;
    CPeriodic* iTimer;
    CVoIPUtilityFactory* iFactory;
    CVoIPAudioDownlinkStream* iDn;
    CVoIPAudioUplinkStream* iUp;
    CVoIPFormatIntfc* iDnFmt;
    CVoIPFormatIntfc* iUpFmt;
    CVoIPDataBuffer* iPlayBuf;
    RArray<TVoIPCodecFormat> iFormats;
    RSocketServ iSs;
    RSocket iSock;
    TInetAddr iDest;
    CRecv* iRecv;
    CSend* iSend;
    OpusEncoder* iEnc;
    OpusDecoder* iDec;
    TUint8* iRing;
    TInt iRingLen[KRingSize];
    TInt iRingHead, iRingCount;
    TBool iDnOpen, iUpOpen, iStarted, iNetOk;
    TBool iPlaying, iEverRecv;
    TInt iPlc;
    TInt iErrors, iLast, iFirstErrs;
    TInt iEncFrames, iSentPkts, iDecFrames, iRecvPkts;
    TInt iPlcFrames, iUnderruns, iEncUs, iDecUs, iLastEnc;
    TInt iPeakIn, iPeakOut;
};

void CRecv::RunL()
{
    iOwner.Received(iStatus.Int(), iPtr);
}

static void RunL()
{
    TInt seconds = 60;
    TBuf<16> cmd;
    if (User::CommandLineLength() <= cmd.MaxLength()) {
        User::CommandLine(cmd);
        TLex lex(cmd);
        TInt v;
        if (lex.Val(v) == KErrNone && v > 0 && v <= 3600)
            seconds = v;
    }
    CActiveScheduler* sched = new (ELeave) CActiveScheduler;
    CleanupStack::PushL(sched);
    CActiveScheduler::Install(sched);
    CRunner* r = new (ELeave) CRunner(seconds);
    CleanupStack::PushL(r);
    TRAPD(err, r->StartL());
    if (err == KErrNone)
        CActiveScheduler::Start();
    CleanupStack::PopAndDestroy(2, sched);
    User::LeaveIfError(err);
}

GLDEF_C TInt E32Main()
{
    CTrapCleanup* cleanup = CTrapCleanup::New();
    TRAPD(err, RunL());
    delete cleanup;
    CloseSTDLIB();
    return err;
}
