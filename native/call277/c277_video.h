/* c277_video.h - video helpers for the "2.7.7" call (docs/CALL-VIDEO-SPEC.md):
 *  - H.264 Annex-B splitting and SPS decoding (profile, level, width x height)
 *  - RFC 6184 packetizer (packetization-mode 1: single NAL, STAP-A, FU-A) that
 *    emits complete RTP packets with the transport-cc one-byte header extension
 *  - RTCP: sender report (+ SDES CNAME) builder, parser for PLI / FIR / NACK / RR
 * C89, fixed arrays, no malloc, no writable static data. */
#ifndef C277_VIDEO_H
#define C277_VIDEO_H

#include "c277_crypto.h"

#define C277_VPT          96        /* the one H264 format we offer -> first dynamic payload type */
#define C277_VMTU         1000      /* max RTP payload bytes per packet */
#define C277_VAU_MAX      16384     /* largest access unit accepted */
#define C277_VNAL_MAX     24
#define C277_VPS_MAX      128       /* cached SPS / PPS size */
#define C277_VEXT_ID      2         /* transport-wide-cc one-byte header extension id (video) */

typedef struct { u32 off, len; } c277_nal;

/* Splits Annex-B data (00 00 01 / 00 00 00 01 start codes) into NAL units (offset,
 * length without start code and trailing zero bytes). Data without any start code
 * is one NAL. Returns the count (at most max). */
int c277_annexb_split(const u8 *d, u32 n, c277_nal *out, u32 max);

typedef struct { int ok, profile, constraints, level, width, height; } c277_sps;
/* nal: the SPS NAL including its header byte. Returns 0 on success. */
int c277_sps_parse(const u8 *nal, u32 n, c277_sps *o);

/* ---- sender */
typedef struct {
    u32 ssrc, ts_base, t0;
    u16 seq, tseq;
    int started;               /* t0 set */
    int sent_idr;              /* an IDR access unit has been queued: P frames may follow */
    /* the access unit being sent */
    u8  au[C277_VAU_MAX];
    c277_nal nal[C277_VNAL_MAX];
    int n_nal, pending, idr, it_nal, it_stap;
    u32 it_off, au_ts;
    u8  sps[C277_VPS_MAX], pps[C277_VPS_MAX];
    u32 sps_len, pps_len;
    /* totals */
    u32 n_pk, n_oct, n_au, n_idr, n_drop, n_drop_idr, n_params;
} c277_vtx;

#define C277_VTX_QUEUED  0     /* access unit queued: call c277_vtx_next until it returns 0 */
#define C277_VTX_PARAMS  1     /* only parameter sets / nothing to send: cached */
#define C277_VTX_DROPPED 2     /* dropped (busy, no IDR yet, no parameter sets) */

/* rnd6: initial sequence (2), timestamp base (4). */
void c277_vtx_init(c277_vtx *v, u32 ssrc, const u8 *rnd6);
/* One encoder output unit (Annex-B, may hold several NALs). The RTP timestamp is
 * 90 kHz derived from now (ms), continuous across encoder restarts. */
int  c277_vtx_put(c277_vtx *v, const u8 *unit, u32 n, u32 now);
/* Next complete RTP packet of the queued access unit (header + extension + payload,
 * marker on the last); returns its length or 0 when the unit is done. */
int  c277_vtx_next(c277_vtx *v, u8 *out, u32 cap);
/* Forget the queued unit and require a new IDR (video turned off). */
void c277_vtx_reset(c277_vtx *v);
/* RTP timestamp that corresponds to now (for sender reports). */
u32  c277_vtx_ts_at(const c277_vtx *v, u32 now);

/* ---- RTCP */
/* SR (28 bytes, no report blocks) + SDES with CNAME "cname" (16): 44 bytes. */
int c277_rtcp_build_sr(u8 *out, u32 cap, u32 ssrc, u32 ntp_hi, u32 ntp_lo, u32 rtp_ts, u32 pk, u32 oct);

typedef struct {
    u32 n_sr, n_rr, n_pli, n_fir, n_nack, n_twcc, n_remb, n_other;
    int rr_have;                          /* a report block for our ssrc was present */
    u32 rr_fraction, rr_lost, rr_jitter;
} c277_rtcp_info;

/* Walks a compound RTCP packet; only PLI/FIR/NACK/RR blocks about our_ssrc (or any
 * ssrc for PLI/FIR when our_ssrc == 0) are counted. Returns 0 or -1 if malformed. */
int c277_rtcp_parse(const u8 *p, u32 n, u32 our_ssrc, c277_rtcp_info *o);
/* PLI (RFC 4585, 12 bytes) for tests. */
int c277_rtcp_build_pli(u8 *out, u32 cap, u32 sender, u32 media);

#endif
