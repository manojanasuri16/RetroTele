/*
 * c277_agc: microphone level for Telegram calls on the N79. The VoIP uplink delivers the mic at
 * its maximum gain (GetMaxGain() is 1 on the N79), which is too quiet for the other side, so a
 * digital AGC runs before the Opus encoder: per 20 ms frame (8 kHz, 160 samples) it measures
 * peak and mean level, aims at about -6 dBFS peak / -17 dBFS RMS, attacks at once (and a soft
 * limiter catches what is left), releases about 3 dB per second, never raises the gain on
 * frames that are near the noise floor (background hiss is not pumped up), max +18 dB (normal)
 * or +24 dB (high). Integer only; no division in the per-sample loop.
 */
#ifndef C277_AGC_H
#define C277_AGC_H

#define C277_AGC_OFF    0
#define C277_AGC_NORMAL 1
#define C277_AGC_HIGH   2

typedef struct {
    int mode;
    int gain;          /* speech gain, Q12 (4096 = 1.0): held through pauses */
    int applied;       /* gain applied to the last frame (pauses: at most +6 dB) */
    int env_peak;      /* peak envelope of the input */
    int env_mean;      /* mean-abs envelope of the input */
    int floor;         /* noise floor estimate (mean abs of quiet frames) */
    /* statistics since the last c277_agc_stats() */
    int st_peak_in, st_peak_out, st_frames, st_clipped, st_gated;
    unsigned long long st_sq;   /* sum of x*x of the input */
    int st_n;
} c277_agc;

void c277_agc_init(c277_agc *a, int mode);
void c277_agc_set_mode(c277_agc *a, int mode);
/* processes n samples in place (n <= 960; meant for 160-sample frames) */
void c277_agc_process(c277_agc *a, short *pcm, int n);
/* input peak, input RMS, output peak, gain in dB x10, frames gated, samples limited; resets */
void c277_agc_stats(c277_agc *a, int *peak_in, int *rms_in, int *peak_out, int *gain_db10,
                    int *gated, int *limited);
/* gain in dB x10 for a Q12 gain (table based, no float) */
int c277_agc_db10(int gain_q12);

#endif
