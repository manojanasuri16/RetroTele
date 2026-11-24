/* c277_agc.c: microphone AGC + soft limiter for calls, see c277_agc.h */
#include "c277_agc.h"

#define ONE        4096              /* Q12 */
#define PEAK_T_N   16384             /* -6 dBFS */
#define PEAK_T_H   20000             /* about -4 dBFS */
#define MEAN_T     3600              /* mean abs ~ RMS -17 dBFS (speech peaks then near -6 dBFS) */
#define MAX_G_N    (4 * ONE)         /* +12 dB (0.16.0: conservative normal) */
#define MAX_G_H    (8 * ONE)         /* +18 dB */
#define MIN_G      (ONE / 4)
#define GATE_G     (2 * ONE)         /* gain held in pauses at most +6 dB (hiss not boosted more) */
#define START_G_N  (2 * ONE)
#define START_G_H  (2 * ONE)
#define MIN_SPEECH 40                /* mean abs below this is never speech (-58 dBFS) */
#define MIN_PEAK   300               /* peaks below this are never speech (-41 dBFS) */
#define KNEE       24576             /* soft limiter starts at -2.5 dBFS */

/* Q12 gain for 0..24 dB in 1 dB steps */
static const int k_db[25] = {
    4096, 4596, 5157, 5786, 6492, 7284, 8173, 9170, 10289, 11544, 12953, 14533, 16306,
    18296, 20529, 23034, 25844, 28997, 32536, 36505, 40960, 45958, 51567, 57859, 64918
};

int c277_agc_db10(int g)
{
    int i, neg = 0;
    if (g <= 0) return -999;
    while (g < ONE) { g = g * 2; neg += 60; }          /* -6 dB per halving */
    for (i = 24; i > 0; i--)
        if (g >= k_db[i]) break;
    if (g > k_db[24]) i = 24;
    return i * 10 - neg;
}

void c277_agc_set_mode(c277_agc *a, int mode)
{
    if (mode < C277_AGC_OFF || mode > C277_AGC_HIGH) mode = C277_AGC_NORMAL;
    if (mode != a->mode) {
        a->mode = mode;
        a->gain = mode == C277_AGC_HIGH ? START_G_H : (mode == C277_AGC_NORMAL ? START_G_N : ONE);
        a->applied = a->gain > GATE_G ? GATE_G : a->gain;
    }
}

void c277_agc_init(c277_agc *a, int mode)
{
    a->mode = -1;
    a->env_peak = 0; a->env_mean = 0; a->floor = 30; a->floor_peak = 100; a->hang = 0;
    a->st_peak_in = a->st_peak_out = a->st_frames = a->st_clipped = a->st_gated = 0;
    a->st_sq = 0; a->st_n = 0;
    c277_agc_set_mode(a, mode);
}

void c277_agc_process(c277_agc *a, short *pcm, int n)
{
    int i, peak = 0, mean, g1, want, gq, step, maxg;
    unsigned int sumabs = 0, sq = 0;
    if (n <= 0 || n > 960) return;
    for (i = 0; i < n; i++) {
        int x = pcm[i], ax = x < 0 ? -x : x;
        if (ax > peak) peak = ax;
        sumabs += (unsigned int)ax;
        sq += ((unsigned int)(ax * ax)) >> 8;
    }
    a->st_sq += (unsigned long long)sq << 8;
    a->st_n += n;
    a->st_frames++;
    if (peak > a->st_peak_in) a->st_peak_in = peak;
    mean = (int)(sumabs / (unsigned int)n);
    if (a->mode == C277_AGC_OFF) {
        if (peak > a->st_peak_out) a->st_peak_out = peak;
        return;
    }
    /* envelopes: fast up, slow down */
    if (peak > a->env_peak) a->env_peak = peak; else a->env_peak -= a->env_peak >> 3;
    if (mean > a->env_mean) a->env_mean += (mean - a->env_mean + 1) >> 1; else a->env_mean -= (a->env_mean - mean) >> 4;
    /* noise floor: follows quiet frames down at once, creeps up slowly */
    if (mean < a->floor) a->floor = mean > 4 ? mean : 4;
    else if (mean < a->floor * 4) a->floor += (a->floor >> 7) + 1;
    if (peak < a->floor_peak) a->floor_peak = peak > 16 ? peak : 16;
    else if (peak < a->floor_peak * 4) a->floor_peak += (a->floor_peak >> 7) + 1;
    maxg = a->mode == C277_AGC_HIGH ? MAX_G_H : MAX_G_N;
    /* speech: the level is well above the noise floor, by the mean (steady sounds) OR by the peaks
     * (the N79 mic gives peaky low-RMS speech: rms 40-60 with peaks around 2000; 0.15.1 gated
     * 50 of 51 such frames on the mean alone) */
    if ((mean > MIN_SPEECH && mean > a->floor * 3) ||
        (peak > MIN_PEAK && peak > a->floor_peak * 4))
        a->hang = 15;
    else if (a->hang > 0)
        a->hang--;
    if (a->hang > 0) {
        int pt = a->mode == C277_AGC_HIGH ? PEAK_T_H : PEAK_T_N;
        want = (int)(((unsigned int)pt << 12) / (unsigned int)(a->env_peak > 1 ? a->env_peak : 1));
        {
            int wm = (int)(((unsigned int)MEAN_T << 12) / (unsigned int)(a->env_mean > 1 ? a->env_mean : 1));
            if (wm < want) want = wm;
        }
        if (want > maxg) want = maxg;
        if (want < MIN_G) want = MIN_G;
        if (want < a->gain) a->gain = want;                                         /* attack: at once */
        else { int up = a->gain + (a->gain >> 7) + 1; a->gain = up > want ? want : up; } /* release ~3 dB/s */
        g1 = a->gain;
    } else {
        /* pause / noise: the speech gain is kept for the next word, but the hiss gets at most +6 dB */
        a->st_gated++;
        g1 = a->gain > GATE_G ? GATE_G : a->gain;
    }
    /* apply with a ramp from the last frame's gain to the new one (Q16 accumulator) */
    gq = a->applied << 4;
    step = ((g1 - a->applied) << 4) / n;
    for (i = 0; i < n; i++) {
        int g = gq >> 6;                       /* Q10 */
        int y = (pcm[i] * g) >> 10;
        gq += step;
        if (y > KNEE) { y = KNEE + ((y - KNEE) >> 2); if (y > 32767) { y = 32767; a->st_clipped++; } }
        else if (y < -KNEE) { y = -KNEE + ((y + KNEE) >> 2); if (y < -32767) { y = -32767; a->st_clipped++; } }
        if ((y < 0 ? -y : y) > a->st_peak_out) a->st_peak_out = y < 0 ? -y : y;
        pcm[i] = (short)y;
    }
    a->applied = g1;
}

static unsigned int isqrt64(unsigned long long v)
{
    unsigned long long r = 0, b = 1ULL << 62;
    while (b > v) b >>= 2;
    while (b) {
        if (v >= r + b) { v -= r + b; r = (r >> 1) + b; } else r >>= 1;
        b >>= 2;
    }
    return (unsigned int)r;
}

void c277_agc_stats(c277_agc *a, int *peak_in, int *rms_in, int *peak_out, int *gain_db10,
                    int *gated, int *limited)
{
    *peak_in = a->st_peak_in;
    *rms_in = a->st_n > 0 ? (int)isqrt64(a->st_sq / (unsigned long long)a->st_n) : 0;
    *peak_out = a->st_peak_out;
    *gain_db10 = a->mode == C277_AGC_OFF ? 0 : c277_agc_db10(a->gain);
    *gated = a->st_gated;
    *limited = a->st_clipped;
    a->st_peak_in = a->st_peak_out = a->st_frames = a->st_clipped = a->st_gated = 0;
    a->st_sq = 0; a->st_n = 0;
}
