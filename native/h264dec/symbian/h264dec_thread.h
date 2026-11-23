// h264dec_thread.h: start the H.264 decode thread on Symbian (header only, C++).
//
// Symbian 9 refuses user thread stacks above 80 KB (0x14000) with KErrTooBig (-40); a 256 KB
// request failed on the N79. h264dec needs far less (PC -fstack-usage: deepest frame about
// 11 KB, whole call chain well under 32 KB), so try 80 KB, then 64 KB, then 32 KB. The thread
// shares the creating thread's heap (FFmpeg's buffers come from it, so size the EXE's
// EPOCHEAPSIZE for them: about 2-3 MB at 352x640). Use it from tgh264bench.exe and tgvideo.exe.
#ifndef H264DEC_THREAD_H
#define H264DEC_THREAD_H
#include <e32std.h>

typedef void (*TH264ThreadLog)(TInt aStack, TInt aErr);

// Creates (does not resume) aThread. Returns KErrNone or the last error; *aStack gets the stack
// size that worked. aLog (may be NULL) is called for every attempt.
static inline TInt H264DecCreateThread(RThread& aThread, const TDesC& aName, TThreadFunction aFn,
                                       TAny* aArg, TInt* aStack, TH264ThreadLog aLog)
{
    static const TInt KStacks[] = { 0x14000, 0x10000, 0x8000 };
    TInt err = KErrGeneral;
    for (TInt i = 0; i < (TInt)(sizeof(KStacks) / sizeof(KStacks[0])); i++) {
        err = aThread.Create(aName, aFn, KStacks[i], NULL, aArg);   // NULL: share the caller's heap
        if (aLog) aLog(KStacks[i], err);
        if (err == KErrNone) {
            if (aStack) *aStack = KStacks[i];
            return KErrNone;
        }
    }
    return err;
}
#endif
