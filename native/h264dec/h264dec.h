/*
 * h264dec: small H.264 software decoder API for RetroTele (Nokia N79, Symbian S60 3rd FP2).
 *
 * Decodes Annex-B H.264 (Baseline, Main, High: CAVLC and CABAC, 8x8 transform, deblocking,
 * multiple slices and reference frames, 4:2:0, 8 bit; B-frames and interlace also work but
 * are not tuned) into planar YUV 4:2:0. Backend: the H.264 decoder of FFmpeg 0.6.7, C only,
 * LGPL 2.1 (see native/third_party/ffmpeg/NOTICE).
 *
 * Threading: one decoder instance per thread (no locking inside). The only process-wide state
 * is a few read-only-after-init tables (VLC tables, clip table) that the first
 * h264dec_create() fills; create the first decoder before starting other decoding threads.
 * On Symbian run decoding on a thread with 64-80 KB stack (80 KB is the Symbian maximum;
 * symbian/h264dec_thread.h: H264DecCreateThread).
 */
#ifndef H264DEC_H
#define H264DEC_H

#ifdef __cplusplus
extern "C" {
#endif

/* return codes of h264dec_decode() */
#define H264DEC_FRAME        1   /* a picture is in *frame */
#define H264DEC_NOFRAME      0   /* access unit consumed (SPS/PPS/SEI only, or no picture yet) */
#define H264DEC_ERR         -1   /* bitstream error; the decoder conceals what it can */
#define H264DEC_ERR_TOOBIG  -2   /* the stream's picture is larger than max_w x max_h */
#define H264DEC_ERR_NOMEM   -3   /* out of memory */
#define H264DEC_ERR_ARG     -4   /* bad argument */

typedef struct h264dec h264dec;

typedef struct h264dec_frame {
    const unsigned char *y, *u, *v;   /* planes; valid until the next decode/reset/destroy */
    int stride_y, stride_uv;          /* bytes per row */
    int width, height;                /* visible picture size (after the SPS crop) */
    int crop_left, crop_top;          /* already applied to y/u/v (multiples of 2) */
    int coded_width, coded_height;    /* macroblock-aligned size */
    int key;                          /* 1 for an IDR / intra picture */
    int errors;                       /* >0: part of the picture was concealed (lost slices) */
    int profile, level;               /* from the active SPS (e.g. 100, 31) */
} h264dec_frame;

typedef void (*h264dec_log_fn)(void *user, const char *msg);

/* max_w, max_h: the largest picture accepted (in either orientation, compared by area and by
 * the longer side). Returns NULL when out of memory. */
h264dec *h264dec_create(int max_w, int max_h);

/* optional log sink for decoder warnings/errors (may be NULL to silence). */
void h264dec_set_log(h264dec *d, h264dec_log_fn fn, void *user);

/* Decode one access unit (Annex-B: start codes + NAL units; SPS/PPS/SEI may precede the
 * slices). The buffer is not modified and need not be padded. */
int h264dec_decode(h264dec *d, const unsigned char *au, int len, h264dec_frame *frame);

/* Drop all references and state (e.g. after a long loss); wait for the next IDR. */
void h264dec_reset(h264dec *d);

/* Number of pictures decoded, and decode errors seen, since create. */
int h264dec_stats(h264dec *d, int *frames, int *errors);

void h264dec_destroy(h264dec *d);

#ifdef __cplusplus
}
#endif
#endif
