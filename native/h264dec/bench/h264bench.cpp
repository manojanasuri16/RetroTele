// tgh264bench.exe: speed + correctness benchmark of h264dec (FFmpeg 0.6.7 H.264, C only) on
// the N79. Decodes embedded x264 clips shaped like the official Telegram app's video (High
// profile, CABAC and CAVLC, 8x8 transform, no B-frames, 15 fps, 150-300 kbit/s), checks every
// picture against the PC decoder's checksum, measures decode time flat out and the CPU load
// at a paced 15 fps (idle-counter thread), and writes E:\retrotele_h264bench.txt
// (C:\Data\ if there is no card). Runs the decoder on its own thread (80/64/32 KB stack, see
// symbian/h264dec_thread.h), or on the main thread (80 KB EPOCSTACKSIZE) if that fails.
#include <e32base.h>
#include <e32std.h>
#include <f32file.h>
#include <hal.h>
#include <sys/reent.h>   // CloseSTDLIB
#include "h264dec.h"
#include "symbian/h264dec_thread.h"
#include "gen/h264bench_clips.h"

_LIT(KCard, "E:\\retrotele_h264bench.txt");
_LIT(KPhone, "C:\\Data\\retrotele_h264bench.txt");

static RFs gFs;
static RFile gFile;
static TBool gOpen = EFalse;

static void Log(TRefByValue<const TDesC8> aFmt, ...)
{
    VA_LIST l;
    VA_START(l, aFmt);
    TBuf8<300> b;
    b.FormatList(aFmt, l);
    VA_END(l);
    b.Append('\n');
    if (gOpen) { gFile.Write(b); gFile.Flush(); }
}

static void OpenLog(TBool aAppend)
{
    if (gFs.Connect() != KErrNone) return;
    gFs.MkDirAll(KPhone);
    TInt e;
    if (aAppend) {
        e = gFile.Open(gFs, KCard, EFileWrite | EFileShareAny);
        if (e != KErrNone) e = gFile.Open(gFs, KPhone, EFileWrite | EFileShareAny);
        if (e == KErrNone) { TInt pos = 0; gFile.Seek(ESeekEnd, pos); }
    } else {
        e = gFile.Replace(gFs, KCard, EFileWrite | EFileShareAny);
        if (e != KErrNone) e = gFile.Replace(gFs, KPhone, EFileWrite | EFileShareAny);
    }
    gOpen = (e == KErrNone);
}

static void CloseLog()
{
    if (gOpen) gFile.Close();
    gOpen = EFalse;
    gFs.Close();
}

// ---- time (FastCounter, unwrapped; NTickCount fallback) ----
static TInt gFastFreq = 0, gFastDown = 0, gTickUs = 1000;
static TUint32 gLast = 0;
static TInt64 gHi = 0;
static void InitClock()
{
    TInt f = 0, up = 1, p = 0;
    if (HAL::Get(HAL::EFastCounterFrequency, f) == KErrNone && f > 0) gFastFreq = f;
    if (HAL::Get(HAL::EFastCounterCountsUp, up) == KErrNone && !up) gFastDown = 1;
    if (HAL::Get(HAL::ENanoTickPeriod, p) == KErrNone && p > 0) gTickUs = p;
}
static TInt64 NowUs()
{
    if (gFastFreq > 0) {
        TUint32 c = gFastDown ? (TUint32)(0 - User::FastCounter()) : (TUint32)User::FastCounter();
        if (c < gLast) gHi += (TInt64)1 << 32;
        gLast = c;
        return ((gHi + (TInt64)c) * 1000000) / gFastFreq;
    }
    return (TInt64)User::NTickCount() * gTickUs;
}

// ---- idle counter (lowest priority spinning thread): CPU headroom ----
static volatile TUint32 gIdle = 0;
static TInt IdleFn(TAny*) { for (;;) gIdle++; return 0; }
static TInt gBaseRate = 0;   // idle increments per second with nothing else running

// FNV-1a over the visible picture, the same as tests/h264dec_test.c -sums
static TUint32 Fnv(const h264dec_frame& f)
{
    TUint32 h = 2166136261u;
    TInt x, y;
    for (y = 0; y < f.height; y++) { const unsigned char* p = f.y + y * f.stride_y; for (x = 0; x < f.width; x++) h = (h ^ p[x]) * 16777619u; }
    for (y = 0; y < f.height / 2; y++) { const unsigned char* p = f.u + y * f.stride_uv; for (x = 0; x < f.width / 2; x++) h = (h ^ p[x]) * 16777619u; }
    for (y = 0; y < f.height / 2; y++) { const unsigned char* p = f.v + y * f.stride_uv; for (x = 0; x < f.width / 2; x++) h = (h ^ p[x]) * 16777619u; }
    return h;
}

static void DecLog(void*, const char* aMsg)
{
    TPtrC8 m((const TUint8*)aMsg);
    if (m.Length() > 0 && m[m.Length() - 1] == '\n') m.Set(m.Left(m.Length() - 1));
    Log(_L8("  dec: %S"), &m);
}

struct TResult { TInt iFrames, iBad, iErrors; TInt64 iUs; TInt iMaxUs; };
static TInt gSummaryMs[KNumClips];       // avg decode us per frame, flat out
static TInt gSummaryCpu176 = -1;         // paced 15 fps CPU % (x100) for clip 0
static TInt gSummaryCpu240 = -1;

// decode a clip once; aCheck: compare sums; aPerFrame: log every frame's time
static void DecodeClip(h264dec* aDec, const BenchClip& c, TBool aCheck, TBool aPerFrame, TResult& r)
{
    TInt fi = 0;
    for (TInt i = 0; i < c.naus; i++) {
        h264dec_frame f;
        TInt64 t0 = NowUs();
        TInt rc = h264dec_decode(aDec, c.data + c.au[2 * i], c.au[2 * i + 1], &f);
        TInt dt = (TInt)(NowUs() - t0);
        r.iUs += dt;
        if (dt > r.iMaxUs) r.iMaxUs = dt;
        if (rc == H264DEC_FRAME) {
            if (aCheck) {
                TUint32 s = Fnv(f);
                if (fi >= c.nframes || s != c.sums[fi] || f.width != c.w || f.height != c.h) {
                    if (r.iBad < 3) Log(_L8("  frame %d: sum %08x expected %08x (%dx%d)"), fi, s, fi < c.nframes ? c.sums[fi] : 0, f.width, f.height);
                    r.iBad++;
                }
            }
            if (aPerFrame) { TPtrC8 k(f.key ? _L8(" key") : _L8("")); Log(_L8("  frame %d: %d.%01d ms, %d bytes%S"), fi, dt / 1000, (dt % 1000) / 100, c.au[2 * i + 1], &k); }
            fi++;
            r.iFrames++;
        } else if (rc < 0) {
            r.iErrors++;
        }
    }
}

static void BenchClipL(TInt aIndex)
{
    const BenchClip& c = kClips[aIndex];
    TPtrC8 name((const TUint8*)c.name);
    Log(_L8("== clip %d: %S, %d bytes, %d frames %dx%d (%d kbit/s at 15 fps)"), aIndex,
        &name, c.len, c.nframes, c.w, c.h, (TInt)(((TInt64)c.len * 8 * 15) / c.nframes / 1000));
    TInt heap0 = 0;
    User::Heap().AllocSize(heap0);
    h264dec* d = h264dec_create(352, 640);
    if (!d) { Log(_L8("  create failed")); return; }
    h264dec_set_log(d, DecLog, NULL);
    // 1. correctness + per-frame times (cold caches)
    TResult r; Mem::FillZ(&r, sizeof(r));
    DecodeClip(d, c, ETrue, aIndex == 0, r);
    TInt heap1 = 0;
    User::Heap().AllocSize(heap1);
    TPtrC8 verdict((r.iBad == 0 && r.iFrames == c.nframes && r.iErrors == 0) ? _L8("OK (identical to the PC)") : _L8("MISMATCH"));
    Log(_L8("  check: %d frames, %d wrong, %d errors -> %S; heap used by the decoder %d KB"),
        r.iFrames, r.iBad, r.iErrors, &verdict, (heap1 - heap0) / 1024);
    // 2. flat out, about 8 s of decoding
    TResult t; Mem::FillZ(&t, sizeof(t));
    TInt64 start = NowUs();
    TInt passes = 0;
    while (NowUs() - start < 8000000 && passes < 50) { DecodeClip(d, c, EFalse, EFalse, t); passes++; }
    TInt avg = t.iFrames ? (TInt)(t.iUs / t.iFrames) : 0;
    gSummaryMs[aIndex] = avg;
    Log(_L8("  flat out: %d passes, %d frames, avg %d.%02d ms/frame = %d.%01d fps, worst %d ms; at 15 fps that is %d%% of the CPU"),
        passes, t.iFrames, avg / 1000, (avg % 1000) / 10, avg ? 10000000 / avg / 10 : 0, avg ? (10000000 / avg) % 10 : 0,
        t.iMaxUs / 1000, (avg * 15) / 10000);
    h264dec_destroy(d);
}

// paced decoding at 15 fps for aSeconds: CPU use from the idle counter
static TInt PacedL(TInt aIndex, TInt aSeconds)
{
    const BenchClip& c = kClips[aIndex];
    h264dec* d = h264dec_create(352, 640);
    if (!d) return -1;
    TInt frames = 0, late = 0, i = 0;
    TInt64 decUs = 0;
    TInt64 t0 = NowUs();
    TUint32 c0 = gIdle;
    TInt64 next = t0;
    while (next - t0 < (TInt64)aSeconds * 1000000) {
        h264dec_frame f;
        TInt64 a = NowUs();
        h264dec_decode(d, c.data + c.au[2 * i], c.au[2 * i + 1], &f);
        decUs += NowUs() - a;
        frames++;
        i = (i + 1) % c.naus;
        next += 66667;
        TInt64 now = NowUs();
        if (now < next) User::After((TInt)(next - now));
        else late++;
    }
    TInt el = (TInt)((NowUs() - t0) / 1000);
    TUint32 di = gIdle - c0;
    TInt rate = el > 0 ? (TInt)(((TInt64)di * 1000) / el) : 0;
    TInt used = gBaseRate > 0 ? 10000 - (TInt)(((TInt64)rate * 10000) / gBaseRate) : -1;
    if (used < 0 && gBaseRate > 0) used = 0;
    TInt avg = frames ? (TInt)(decUs / frames) : 0;
    TPtrC8 name((const TUint8*)c.name);
    Log(_L8("== paced 15 fps, %S, %d s: %d frames, %d late, avg decode %d.%02d ms; CPU used %d.%02d%% (idle %d/s, baseline %d/s)"),
        &name, aSeconds, frames, late, avg / 1000, (avg % 1000) / 10, used / 100, used % 100, rate, gBaseRate);
    h264dec_destroy(d);
    return used;
}

static void RunBenchL()
{
    OpenLog(ETrue);     // E32Main created the file
    InitClock();
    Log(_L8("RetroTele h264dec benchmark (FFmpeg 0.6.7 H.264 decoder, C only, GCCE -O2)"));
    TInt cpu = 0, ram = 0;
    HAL::Get(HAL::ECPUSpeed, cpu);
    HAL::Get(HAL::EMemoryRAMFree, ram);
    Log(_L8("cpu %d kHz (reported), ram free %d KB, fastcounter %d Hz"), cpu, ram / 1024, gFastFreq);
    RThread idle;
    TInt e = idle.Create(_L("h264idle"), IdleFn, 0x1000, NULL, NULL);
    if (e == KErrNone) { idle.SetPriority(EPriorityMuchLess); idle.Resume(); }
    User::After(300000);
    TUint32 c0 = gIdle; TInt64 t0 = NowUs();
    User::After(1500000);
    TInt el = (TInt)((NowUs() - t0) / 1000);
    gBaseRate = (e == KErrNone && el > 0) ? (TInt)(((TInt64)(gIdle - c0) * 1000) / el) : 0;
    Log(_L8("idle baseline %d/s over %d ms (idle thread err %d)"), gBaseRate, el, e);
    for (TInt k = 0; k < KNumClips; k++) BenchClipL(k);
    gSummaryCpu176 = PacedL(0, 15);
    gSummaryCpu240 = PacedL(2, 8);
    Log(_L8("SUMMARY 176x320 CABAC %d.%01d ms/frame, CAVLC %d.%01d, 240x480 %d.%01d, 352x640 %d.%01d; paced 15 fps CPU 176x320 %d%%, 240x480 %d%%"),
        gSummaryMs[0] / 1000, (gSummaryMs[0] % 1000) / 100, gSummaryMs[1] / 1000, (gSummaryMs[1] % 1000) / 100,
        gSummaryMs[2] / 1000, (gSummaryMs[2] % 1000) / 100, gSummaryMs[3] / 1000, (gSummaryMs[3] % 1000) / 100,
        gSummaryCpu176 / 100, gSummaryCpu240 / 100);
    if (e == KErrNone) { idle.Kill(0); idle.Close(); }
    CloseLog();
}

static TInt BenchThread(TAny*)
{
    CTrapCleanup* cleanup = CTrapCleanup::New();
    TRAPD(err, RunBenchL());
    delete cleanup;
    CloseSTDLIB();
    return err;
}

static void LogAttempt(TInt aStack, TInt aErr)
{
    Log(_L8("create decode thread, stack %d KB: %d"), aStack / 1024, aErr);
}

GLDEF_C TInt E32Main()
{
    CTrapCleanup* cleanup = CTrapCleanup::New();
    TInt biggest = 0;
    TInt avail = User::Available(biggest);
    TInt heapMax = User::Heap().MaxLength();
    OpenLog(EFalse);
    Log(_L8("bench start, heap avail %d KB (biggest block %d KB), heap max %d KB"), avail / 1024, biggest / 1024, heapMax / 1024);
    RThread t;
    TInt stack = 0;
    TInt err = H264DecCreateThread(t, _L("h264bench"), BenchThread, NULL, &stack, LogAttempt);
    CloseLog();
    TExitType et = EExitKill;
    TInt reason = err;
    TExitCategoryName cat;
    if (err == KErrNone) {
        TRequestStatus st;
        t.Logon(st);
        t.Resume();
        User::WaitForRequest(st);
        et = t.ExitType();
        reason = t.ExitReason();
        cat = t.ExitCategory();
        t.Close();
        OpenLog(ETrue);
        if (et == EExitPanic) { TBuf8<KMaxExitCategoryName> c8; c8.Copy(cat); Log(_L8("decode thread PANIC %S %d"), &c8, reason); }
        else Log(_L8("decode thread exit %d (stack %d KB)"), reason, stack / 1024);
    } else {
        OpenLog(ETrue);
        Log(_L8("no decode thread (%d): running on the main thread (80 KB stack)"), err);
        CloseLog();
        TRAPD(e2, RunBenchL());
        OpenLog(ETrue);
        Log(_L8("main-thread bench exit %d"), e2);
    }
    Log(_L8("bench end"));
    CloseLog();
    delete cleanup;
    return 0;
}
