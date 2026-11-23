/* Host test for c277_agc (mic AGC): quiet speech-like bursts, silence with hiss, loud/clipped
 * input, mode off. Run by run_tests.sh. */
#include <stdio.h>
#include <string.h>
#include "c277_agc.h"

static int g_n, g_fail;
#define CHECK(c) do { g_n++; if (!(c)) { g_fail++; printf("FAIL line %d: %s\n", __LINE__, #c); } } while (0)

static unsigned int g_seed = 12345;
static int rnd(int amp)    /* uniform in [-amp, amp] */
{
    g_seed = g_seed * 1103515245u + 12345u;
    return amp ? (int)((g_seed >> 8) % (unsigned int)(2 * amp + 1)) - amp : 0;
}

/* integer "speech": a 2-tone signal shaped by syllables (200 ms on, 150 ms off) */
static const short k_sin[16] = { 0, 12540, 23170, 30274, 32767, 30274, 23170, 12540,
                                 0, -12540, -23170, -30274, -32767, -30274, -23170, -12540 };
static void speech(short *f, int n, int t0, int peak, int hiss)
{
    int i;
    for (i = 0; i < n; i++) {
        int t = t0 + i, ph = t % 2800;                 /* 350 ms cycle at 8 kHz */
        int env = 0;
        if (ph < 1600) env = ph < 400 ? ph * 256 / 400 : (ph > 1200 ? (1600 - ph) * 256 / 400 : 256);
        {
            int v = (k_sin[(t * 3) & 15] * 3 + k_sin[(t * 7) & 15]) / 4;   /* ~ 1.5 kHz + 3.5 kHz */
            v = (int)((long)v * peak / 32767) * env / 256;
            f[i] = (short)(v + rnd(hiss));
        }
    }
}

static int frame_peak(const short *f, int n)
{
    int i, p = 0;
    for (i = 0; i < n; i++) { int a = f[i] < 0 ? -f[i] : f[i]; if (a > p) p = a; }
    return p;
}

/* runs `secs` seconds of speech at `peak`, returns the output peak of the last second; *hiss_out
 * gets the output peak during the last pause */
static int run(c277_agc *a, int secs, int peak, int hiss, int *hiss_out)
{
    short f[160];
    int t, last = 0, pause = 0;
    for (t = 0; t < secs * 8000; t += 160) {
        int ph;
        speech(f, 160, t, peak, hiss);
        c277_agc_process(a, f, 160);
        ph = t % 2800;
        if (t >= (secs - 1) * 8000) {
            int p = frame_peak(f, 160);
            if (ph >= 1700 && ph + 160 < 2800) { if (p > pause) pause = p; }
            else if (p > last) last = p;
        }
    }
    if (hiss_out) *hiss_out = pause;
    return last;
}

int main(void)
{
    c277_agc a;
    short f[160], g[160];
    int pk, hs, i, pi, ri, po, gd, gt, lim, peaks[4] = { 300, 600, 1000, 2000 };
    CHECK(c277_agc_db10(4096) == 0 && c277_agc_db10(8192) == 60 && c277_agc_db10(32768) == 180);
    CHECK(c277_agc_db10(2048) == -60);
    /* quiet speech gets louder (normal: up to +18 dB, aiming at about -6 dBFS peaks) */
    for (i = 0; i < 4; i++) {
        c277_agc_init(&a, C277_AGC_NORMAL);
        pk = run(&a, 8, peaks[i], 15, &hs);
        c277_agc_stats(&a, &pi, &ri, &po, &gd, &gt, &lim);
        printf("normal: input peak %4d -> output peak %5d, pause %4d, gain %d.%d dB, gated %d\n",
               peaks[i], pk, hs, gd / 10, gd % 10, gt);
        CHECK(pk >= peaks[i] * 3);                         /* at least +9.5 dB */
        CHECK(pk <= 24576 + 2048);                         /* no harder than the limiter knee */
        if (peaks[i] >= 1000) CHECK(pk >= 8000);           /* -12 dBFS or louder */
        CHECK(hs <= 15 * 2 + 8 + pk / 8);                  /* pauses: hiss not boosted beyond +6 dB */
        CHECK(lim == 0);
    }
    /* high mode is louder for very quiet speech */
    c277_agc_init(&a, C277_AGC_HIGH);
    pk = run(&a, 10, 300, 10, &hs);
    printf("high: input peak 300 -> output peak %d\n", pk);
    CHECK(pk >= 300 * 6);
    /* loud and clipped input: no gain, no wrap-around, never above full scale */
    c277_agc_init(&a, C277_AGC_NORMAL);
    for (i = 0; i < 200; i++) {
        int k;
        for (k = 0; k < 160; k++) f[k] = (short)((k & 8) ? 32767 : -32768);
        c277_agc_process(&a, f, 160);
        for (k = 0; k < 160; k++) CHECK(f[k] <= 32767 && f[k] >= -32767 && (f[k] > 0) == ((k & 8) != 0));
    }
    CHECK(a.gain <= 4096);
    /* a sudden loud word after quiet speech: attack at once, the limiter keeps it below clipping */
    c277_agc_init(&a, C277_AGC_NORMAL);
    run(&a, 6, 300, 10, NULL);
    speech(f, 160, 400, 20000, 0);
    c277_agc_process(&a, f, 160);
    CHECK(frame_peak(f, 160) <= 32767);
    c277_agc_stats(&a, &pi, &ri, &po, &gd, &gt, &lim);
    CHECK(pi == 20000 || pi >= 19000);
    /* silence with hiss only: gain stays at most +6 dB */
    c277_agc_init(&a, C277_AGC_NORMAL);
    for (i = 0; i < 300; i++) {
        int k;
        for (k = 0; k < 160; k++) f[k] = (short)rnd(20);
        c277_agc_process(&a, f, 160);
    }
    CHECK(a.gain <= 2 * 4096);
    /* off: untouched */
    c277_agc_init(&a, C277_AGC_OFF);
    speech(f, 160, 500, 1000, 5);
    memcpy(g, f, sizeof(f));
    c277_agc_process(&a, f, 160);
    CHECK(memcmp(f, g, sizeof(f)) == 0);
    c277_agc_stats(&a, &pi, &ri, &po, &gd, &gt, &lim);
    CHECK(pi > 0 && ri > 0 && ri < pi && po == pi && gd == 0);
    /* mode change at run time */
    c277_agc_set_mode(&a, C277_AGC_HIGH);
    CHECK(a.mode == C277_AGC_HIGH && a.gain == 4 * 4096);
    printf("test_agc: %d checks, %d failed\n", g_n, g_fail);
    return g_fail ? 1 : 0;
}
