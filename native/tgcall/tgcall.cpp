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
#include "loopback.h"
#include <libc/sys/reent.h>
#include "tgopus_bench.h"

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
