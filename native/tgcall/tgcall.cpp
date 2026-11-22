/*
 * tgcall: live audio for RetroTele call experiments (Python for S60 1.4.5).
 *
 * Step 1 of Telegram calls: can the N79 record and play 16-bit PCM in small
 * chunks while Python keeps running? This module records from the
 * microphone (CMdaAudioInputStream) into a FIFO and plays it back
 * (CMdaAudioOutputStream) after a chosen delay: a loopback "echo test".
 *
 *   tgcall.start(sample_rate=16000, delay_ms=500, volume_percent=60)
 *   tgcall.stop()
 *   tgcall.stats() -> (state, recorded_bytes, played_bytes, record_buffers,
 *                      silence_frames, read_errors, write_errors, last_error,
 *                      first_record_ms, first_play_ms, fifo_bytes, max_level)
 *
 * The engine object lives in thread-local storage (Dll::Tls), so the DLL has
 * no writable static data. All callbacks run on Python's main thread through
 * its active scheduler (the same one appuifw and e32 use).
 */
#include "Python.h"
#include <e32base.h>
#include <e32std.h>
#include <mdaaudioinputstream.h>
#include <mdaaudiooutputstream.h>
#include <mda/common/audio.h>
#include <libc/sys/reent.h>
#include "tgopus_bench.h"

const TInt KFrameMs = 20;
const TInt KMaxFifo = 64000;        /* bytes: 2 s at 16 kHz mono */

class CLoopback : public CBase,
                  public MMdaAudioInputStreamCallback,
                  public MMdaAudioOutputStreamCallback
{
public:
    static CLoopback* NewL(TInt aRate, TInt aDelayMs, TInt aVolume);
    ~CLoopback();
    void Stop();

    /* statistics */
    TInt iState;             /* 0 opening, 1 running, 2 stopped, 3 failed */
    TInt iRecorded;
    TInt iPlayed;
    TInt iRecordBuffers;
    TInt iSilence;
    TInt iReadErrors;
    TInt iWriteErrors;
    TInt iLastError;
    TInt iFirstRecordMs;
    TInt iFirstPlayMs;
    TInt iMaxLevel;

    /* MMdaAudioInputStreamCallback */
    void MaiscOpenComplete(TInt aError);
    void MaiscBufferCopied(TInt aError, const TDesC8& aBuffer);
    void MaiscRecordComplete(TInt aError);
    /* MMdaAudioOutputStreamCallback */
    void MaoscOpenComplete(TInt aError);
    void MaoscBufferCopied(TInt aError, const TDesC8& aBuffer);
    void MaoscPlayComplete(TInt aError);

    TInt FifoBytes() const { return iFifoLen; }

private:
    CLoopback(TInt aRate, TInt aDelayMs, TInt aVolume);
    void ConstructL();
    void Read();
    void WriteNext();
    TInt ElapsedMs() const;

    CMdaAudioInputStream* iIn;
    CMdaAudioOutputStream* iOut;
    TMdaAudioDataSettings iInSettings;
    TMdaAudioDataSettings iOutSettings;
    TBuf8<4096> iReadBuf;
    TBuf8<4096> iWriteBuf;
    TUint8* iFifo;
    TInt iFifoLen;
    TInt iRate;
    TInt iDelayBytes;
    TInt iFrameBytes;
    TInt iVolume;
    TBool iOutOpen;
    TBool iWriting;
    TBool iPlaying;          /* delay reached once */
    TBool iStopping;
    TTime iStart;
};

static TInt RateCap(TInt aRate)
{
    switch (aRate) {
    case 8000: return TMdaAudioDataSettings::ESampleRate8000Hz;
    case 11025: return TMdaAudioDataSettings::ESampleRate11025Hz;
    case 12000: return TMdaAudioDataSettings::ESampleRate12000Hz;
    case 22050: return TMdaAudioDataSettings::ESampleRate22050Hz;
    case 24000: return TMdaAudioDataSettings::ESampleRate24000Hz;
    case 32000: return TMdaAudioDataSettings::ESampleRate32000Hz;
    case 44100: return TMdaAudioDataSettings::ESampleRate44100Hz;
    case 48000: return TMdaAudioDataSettings::ESampleRate48000Hz;
    default: return TMdaAudioDataSettings::ESampleRate16000Hz;
    }
}

CLoopback::CLoopback(TInt aRate, TInt aDelayMs, TInt aVolume)
    : iRate(aRate), iVolume(aVolume)
{
    iFrameBytes = aRate * 2 * KFrameMs / 1000;
    iDelayBytes = aRate * 2 * aDelayMs / 1000;
    if (iDelayBytes > KMaxFifo / 2)
        iDelayBytes = KMaxFifo / 2;
}

CLoopback* CLoopback::NewL(TInt aRate, TInt aDelayMs, TInt aVolume)
{
    CLoopback* self = new (ELeave) CLoopback(aRate, aDelayMs, aVolume);
    CleanupStack::PushL(self);
    self->ConstructL();
    CleanupStack::Pop(self);
    return self;
}

void CLoopback::ConstructL()
{
    iFifo = (TUint8*)User::AllocL(KMaxFifo);
    iStart.HomeTime();
    iFirstRecordMs = -1;
    iFirstPlayMs = -1;

    iIn = CMdaAudioInputStream::NewL(*this);
    iInSettings.Query();
    iInSettings.iSampleRate = RateCap(iRate);
    iInSettings.iChannels = TMdaAudioDataSettings::EChannelsMono;
    iInSettings.iFlags = TMdaAudioDataSettings::ENoNetworkRouting;
    iIn->Open(&iInSettings);

    iOut = CMdaAudioOutputStream::NewL(*this);
    iOutSettings.Query();
    iOutSettings.iSampleRate = RateCap(iRate);
    iOutSettings.iChannels = TMdaAudioDataSettings::EChannelsMono;
    iOutSettings.iFlags = TMdaAudioDataSettings::ENoNetworkRouting;
    iOutSettings.iVolume = 0;
    iOut->Open(&iOutSettings);
}

CLoopback::~CLoopback()
{
    iStopping = ETrue;
    if (iIn) {
        iIn->Stop();
        delete iIn;
    }
    if (iOut) {
        iOut->Stop();
        delete iOut;
    }
    User::Free(iFifo);
}

TInt CLoopback::ElapsedMs() const
{
    TTime now;
    now.HomeTime();
    return (TInt)(now.MicroSecondsFrom(iStart).Int64() / 1000);
}

void CLoopback::Stop()
{
    iStopping = ETrue;
    if (iIn)
        iIn->Stop();
    if (iOut)
        iOut->Stop();
    iState = 2;
}

void CLoopback::Read()
{
    if (iStopping)
        return;
    iReadBuf.SetLength(0);
    TRAPD(err, iIn->ReadL(iReadBuf));
    if (err != KErrNone) {
        iReadErrors++;
        iLastError = err;
    }
}

void CLoopback::MaiscOpenComplete(TInt aError)
{
    if (aError != KErrNone) {
        iLastError = aError;
        iState = 3;
        return;
    }
    TRAPD(err, iIn->SetAudioPropertiesL(RateCap(iRate),
                                        TMdaAudioDataSettings::EChannelsMono));
    if (err != KErrNone)
        iLastError = err;
    iIn->SetGain(iIn->MaxGain());
    iState = 1;
    Read();
}

void CLoopback::MaiscBufferCopied(TInt aError, const TDesC8& aBuffer)
{
    if (aError != KErrNone) {
        if (aError != KErrAbort) {
            iReadErrors++;
            iLastError = aError;
        }
        return;
    }
    if (iFirstRecordMs < 0)
        iFirstRecordMs = ElapsedMs();
    iRecordBuffers++;
    TInt n = aBuffer.Length();
    iRecorded += n;
    /* peak level of this buffer (16-bit little-endian samples) */
    const TUint8* p = aBuffer.Ptr();
    for (TInt i = 0; i + 1 < n; i += 2) {
        TInt s = (TInt16)(p[i] | (p[i + 1] << 8));
        if (s < 0) s = -s;
        if (s > iMaxLevel) iMaxLevel = s;
    }
    /* append to the FIFO, dropping the oldest audio if it's full */
    if (n > KMaxFifo) {
        p += n - KMaxFifo;
        n = KMaxFifo;
    }
    if (iFifoLen + n > KMaxFifo) {
        TInt drop = iFifoLen + n - KMaxFifo;
        Mem::Move(iFifo, iFifo + drop, iFifoLen - drop);
        iFifoLen -= drop;
    }
    Mem::Copy(iFifo + iFifoLen, p, n);
    iFifoLen += n;
    Read();
    if (iOutOpen && !iWriting)
        WriteNext();
}

void CLoopback::MaiscRecordComplete(TInt aError)
{
    if (aError != KErrNone && aError != KErrCancel && aError != KErrAbort)
        iLastError = aError;
}

void CLoopback::WriteNext()
{
    if (iStopping || !iOutOpen || iWriting)
        return;
    if (!iPlaying && iFifoLen < iDelayBytes)
        return;                      /* still building the delay */
    iPlaying = ETrue;
    TInt n = iFrameBytes * 2;        /* 40 ms per write */
    if (n > iWriteBuf.MaxLength())
        n = iWriteBuf.MaxLength();
    if (iFifoLen >= n) {
        iWriteBuf.Copy(iFifo, n);
        Mem::Move(iFifo, iFifo + n, iFifoLen - n);
        iFifoLen -= n;
    } else {
        /* starving: play silence so the output stream keeps running */
        iWriteBuf.SetLength(n);
        iWriteBuf.FillZ();
        iSilence++;
    }
    TRAPD(err, iOut->WriteL(iWriteBuf));
    if (err != KErrNone) {
        iWriteErrors++;
        iLastError = err;
        return;
    }
    iWriting = ETrue;
}

void CLoopback::MaoscOpenComplete(TInt aError)
{
    if (aError != KErrNone) {
        iLastError = aError;
        iState = 3;
        return;
    }
    TRAPD(err, iOut->SetAudioPropertiesL(RateCap(iRate),
                                         TMdaAudioDataSettings::EChannelsMono));
    if (err != KErrNone)
        iLastError = err;
    iOut->SetVolume(iOut->MaxVolume() * iVolume / 100);
    iOutOpen = ETrue;
    WriteNext();
}

void CLoopback::MaoscBufferCopied(TInt aError, const TDesC8& aBuffer)
{
    iWriting = EFalse;
    if (aError != KErrNone) {
        if (aError != KErrAbort) {
            iWriteErrors++;
            iLastError = aError;
        }
        return;
    }
    if (iFirstPlayMs < 0)
        iFirstPlayMs = ElapsedMs();
    iPlayed += aBuffer.Length();
    WriteNext();
}

void CLoopback::MaoscPlayComplete(TInt aError)
{
    /* KErrUnderflow when we ran dry; restart writing if still running */
    iWriting = EFalse;
    if (aError != KErrNone && aError != KErrCancel && aError != KErrAbort) {
        iLastError = aError;
        if (!iStopping && aError == KErrUnderflow) {
            iOutOpen = EFalse;
            iOut->Open(&iOutSettings);   /* reopen and continue */
        }
    }
}

/* ------------------------------------------------------------------ Opus */
/* Opus needs ~16-32 KB of stack (C99 arrays), more than the Python thread
   may have, so the benchmark runs on its own thread with 64 KB and the
   caller waits for it. */

struct TBench {
    TInt iSelfTest;
    TInt iRate, iComplexity, iBitrate, iFrames;
    TInt iEncUs, iDecUs, iRc;
    TInt iWallMs;
};

static TInt BenchThread(TAny* aArg)
{
    TBench* b = (TBench*)aArg;
    TTime t0;
    t0.HomeTime();
    int enc = 0, dec = 0;
    if (b->iSelfTest)
        b->iRc = tgopus_selftest();
    else
        b->iRc = tgopus_bench(b->iRate, b->iComplexity, b->iBitrate, b->iFrames, &enc, &dec);
    b->iEncUs = enc;
    b->iDecUs = dec;
    TTime t1;
    t1.HomeTime();
    b->iWallMs = (TInt)(t1.MicroSecondsFrom(t0).Int64() / 1000);
    CloseSTDLIB();
    return KErrNone;
}

static TInt RunBench(TBench& aBench)
{
    RThread t;
    TName name;
    name.Format(_L("tgopus%x"), User::NTickCount());
    TInt err = t.Create(name, BenchThread, 0x10000, NULL, &aBench);
    if (err != KErrNone)
        return err;
    TRequestStatus st;
    t.Logon(st);
    t.Resume();
    User::WaitForRequest(st);
    TInt reason = t.ExitReason();
    TExitType type = t.ExitType();
    t.Close();
    if (type == EExitPanic)
        return KErrDied;
    return reason;
}

/* ------------------------------------------------------------------ Python */

static CLoopback* Engine()
{
    return (CLoopback*)Dll::Tls();
}

static void StopEngine()
{
    CLoopback* e = Engine();
    if (e) {
        Dll::SetTls(NULL);
        delete e;
    }
}

extern "C" {

static PyObject* tg_start(PyObject* /*self*/, PyObject* args)
{
    int rate = 16000, delay = 500, volume = 60;
    if (!PyArg_ParseTuple(args, "|iii", &rate, &delay, &volume))
        return NULL;
    StopEngine();
    CLoopback* e = NULL;
    TRAPD(err, e = CLoopback::NewL(rate, delay, volume));
    if (err != KErrNone) {
        PyErr_SetString(PyExc_RuntimeError, "audio start failed");
        return NULL;
    }
    Dll::SetTls(e);
    Py_INCREF(Py_None);
    return Py_None;
}

static PyObject* tg_stop(PyObject* /*self*/, PyObject* /*args*/)
{
    CLoopback* e = Engine();
    if (e)
        e->Stop();
    StopEngine();
    Py_INCREF(Py_None);
    return Py_None;
}

static PyObject* tg_stats(PyObject* /*self*/, PyObject* /*args*/)
{
    CLoopback* e = Engine();
    if (!e) {
        Py_INCREF(Py_None);
        return Py_None;
    }
    return Py_BuildValue("(iiiiiiiiiiii)", e->iState, e->iRecorded, e->iPlayed,
                         e->iRecordBuffers, e->iSilence, e->iReadErrors,
                         e->iWriteErrors, e->iLastError, e->iFirstRecordMs,
                         e->iFirstPlayMs, e->FifoBytes(), e->iMaxLevel);
}

/* opus_bench(rate, complexity, bitrate, frames) ->
       (rc, enc_us_per_frame, dec_us_per_frame, wall_ms) */
static PyObject* tg_opus_bench(PyObject* /*self*/, PyObject* args)
{
    TBench b;
    Mem::FillZ(&b, sizeof(b));
    b.iRate = 16000; b.iComplexity = 0; b.iBitrate = 16000; b.iFrames = 200;
    if (!PyArg_ParseTuple(args, "|iiii", &b.iRate, &b.iComplexity, &b.iBitrate, &b.iFrames))
        return NULL;
    TInt err;
    Py_BEGIN_ALLOW_THREADS
    err = RunBench(b);
    Py_END_ALLOW_THREADS
    if (err != KErrNone)
        b.iRc = err;
    return Py_BuildValue("(iiii)", b.iRc, b.iEncUs, b.iDecUs, b.iWallMs);
}

/* opus_selftest() -> (rc, wall_ms): encode + decode 1 s and check the output */
static PyObject* tg_opus_selftest(PyObject* /*self*/, PyObject* /*args*/)
{
    TBench b;
    Mem::FillZ(&b, sizeof(b));
    b.iSelfTest = 1;
    TInt err;
    Py_BEGIN_ALLOW_THREADS
    err = RunBench(b);
    Py_END_ALLOW_THREADS
    if (err != KErrNone)
        b.iRc = err;
    return Py_BuildValue("(ii)", b.iRc, b.iWallMs);
}

static const PyMethodDef tgcall_methods[] = {
    {"opus_bench", (PyCFunction)tg_opus_bench, METH_VARARGS, NULL},
    {"opus_selftest", (PyCFunction)tg_opus_selftest, METH_VARARGS, NULL},
    {"start", (PyCFunction)tg_start, METH_VARARGS, NULL},
    {"stop", (PyCFunction)tg_stop, METH_VARARGS, NULL},
    {"stats", (PyCFunction)tg_stats, METH_VARARGS, NULL},
    {NULL, NULL, 0, NULL}
};

DL_EXPORT(void) inittgcall(void)
{
    Py_InitModule("tgcall", (PyMethodDef*)tgcall_methods);
}

} /* extern "C" */
