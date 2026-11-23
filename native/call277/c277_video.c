/* c277_video.c - see c277_video.h */
#include <string.h>
#include "c277_video.h"

/* ---------------------------------------------------------------- Annex-B */

int c277_annexb_split(const u8 *d, u32 n, c277_nal *out, u32 max)
{
    u32 i = 0, start = 0, cnt = 0;
    int have = 0;
    if (n == 0 || max == 0) return 0;
    while (i + 2 < n) {
        if (d[i] == 0 && d[i + 1] == 0 && d[i + 2] == 1) {
            if (have && cnt < max) {
                u32 e = i;
                while (e > start && d[e - 1] == 0) e--;     /* 4-byte start code / trailing zeros */
                out[cnt].off = start; out[cnt].len = e - start; cnt++;
            }
            start = i + 3; have = 1; i += 3;
        } else {
            i++;
        }
    }
    if (!have) {
        out[0].off = 0; out[0].len = n;
        return 1;
    }
    if (cnt < max && start < n) {
        u32 e = n;
        while (e > start && d[e - 1] == 0) e--;
        out[cnt].off = start; out[cnt].len = e - start; cnt++;
    }
    {   /* drop empty entries */
        u32 a, b = 0;
        for (a = 0; a < cnt; a++) if (out[a].len > 0) out[b++] = out[a];
        cnt = b;
    }
    return (int)cnt;
}

/* ---------------------------------------------------------------- SPS */

typedef struct { const u8 *p; u32 n, pos; int err; } bitr;

static u32 br_bit(bitr *b)
{
    u32 v;
    if ((b->pos >> 3) >= b->n) { b->err = 1; return 0; }
    v = (b->p[b->pos >> 3] >> (7 - (b->pos & 7))) & 1;
    b->pos++;
    return v;
}
static u32 br_ue_full(bitr *b)
{
    u32 z = 0, v = 0, i;
    while (br_bit(b) == 0) {
        if (b->err || ++z > 31) { b->err = 1; return 0; }
    }
    for (i = 0; i < z; i++) v = (v << 1) | br_bit(b);
    return (z ? ((1UL << z) - 1) : 0) + v;
}
static int br_se(bitr *b)
{
    u32 k = br_ue_full(b);
    return (k & 1) ? (int)((k + 1) >> 1) : -(int)(k >> 1);
}

static void skip_scaling(bitr *b, int size)
{
    int last = 8, next = 8, j;
    for (j = 0; j < size && !b->err; j++) {
        if (next != 0) {
            int d = br_se(b);
            next = (last + d + 256) & 255;
        }
        if (next != 0) last = next;
    }
}

int c277_sps_parse(const u8 *nal, u32 n, c277_sps *o)
{
    u8 rb[160];
    u32 i, m = 0, chroma = 1, fmo, pw, ph, cl = 0, cr = 0, ct = 0, cb = 0, cux, cuy;
    int prof, k;
    bitr b;
    memset(o, 0, sizeof(*o));
    if (n < 5 || (nal[0] & 31) != 7) return -1;
    /* unescape (drop the 03 of 00 00 03) */
    for (i = 1; i < n && m < sizeof(rb); i++) {
        if (i >= 3 && nal[i] == 3 && nal[i - 1] == 0 && nal[i - 2] == 0) continue;
        rb[m++] = nal[i];
    }
    b.p = rb; b.n = m; b.pos = 0; b.err = 0;
    prof = rb[0];
    o->profile = prof; o->constraints = rb[1]; o->level = rb[2];
    b.pos = 24;
    br_ue_full(&b);                                   /* sps id */
    if (prof == 100 || prof == 110 || prof == 122 || prof == 244 || prof == 44 || prof == 83 ||
        prof == 86 || prof == 118 || prof == 128 || prof == 138 || prof == 139 || prof == 134 ||
        prof == 135) {
        chroma = br_ue_full(&b);
        if (chroma == 3) br_bit(&b);
        br_ue_full(&b); br_ue_full(&b); br_bit(&b);
        if (br_bit(&b)) {
            int cnt = chroma != 3 ? 8 : 12;
            for (k = 0; k < cnt && !b.err; k++)
                if (br_bit(&b)) skip_scaling(&b, k < 6 ? 16 : 64);
        }
    }
    br_ue_full(&b);                                   /* log2_max_frame_num - 4 */
    k = (int)br_ue_full(&b);                          /* poc type */
    if (k == 0) br_ue_full(&b);
    else if (k == 1) {
        u32 cnt, j;
        br_bit(&b); br_se(&b); br_se(&b);
        cnt = br_ue_full(&b);
        if (cnt > 255) b.err = 1;
        for (j = 0; j < cnt && !b.err; j++) br_se(&b);
    }
    br_ue_full(&b);                                   /* max_num_ref_frames */
    br_bit(&b);                                       /* gaps allowed */
    pw = br_ue_full(&b);
    ph = br_ue_full(&b);
    fmo = br_bit(&b);
    if (!fmo) br_bit(&b);
    br_bit(&b);                                       /* direct 8x8 */
    if (br_bit(&b)) { cl = br_ue_full(&b); cr = br_ue_full(&b); ct = br_ue_full(&b); cb = br_ue_full(&b); }
    if (b.err || pw > 1000 || ph > 1000) return -1;
    if (chroma == 0) { cux = 1; cuy = 2 - fmo; }
    else {
        cux = chroma == 3 ? 1 : 2;
        cuy = (chroma == 1 ? 2 : 1) * (2 - fmo);
    }
    o->width = (int)((pw + 1) * 16 - cux * (cl + cr));
    o->height = (int)((2 - fmo) * (ph + 1) * 16 - cuy * (ct + cb));
    o->ok = 1;
    return 0;
}

/* ---------------------------------------------------------------- sender */

static void put16(u8 *p, u32 v) { p[0] = (u8)(v >> 8); p[1] = (u8)v; }
static void put32(u8 *p, u32 v) { p[0] = (u8)(v >> 24); p[1] = (u8)(v >> 16); p[2] = (u8)(v >> 8); p[3] = (u8)v; }

void c277_vtx_init(c277_vtx *v, u32 ssrc, const u8 *rnd6)
{
    memset(v, 0, sizeof(*v));
    v->ssrc = ssrc;
    v->seq = (u16)(((u32)rnd6[0] << 8) | rnd6[1]);
    v->ts_base = ((u32)rnd6[2] << 24) | ((u32)rnd6[3] << 16) | ((u32)rnd6[4] << 8) | rnd6[5];
    v->tseq = (u16)(rnd6[0] ^ (rnd6[5] << 4));
}

void c277_vtx_reset(c277_vtx *v)
{
    v->pending = 0; v->n_nal = 0; v->sent_idr = 0;
}

u32 c277_vtx_ts_at(const c277_vtx *v, u32 now)
{
    if (!v->started) return v->ts_base;
    return v->ts_base + (u32)(now - v->t0) * 90UL;
}

static void keep_ps(u8 *dst, u32 *dl, const u8 *src, u32 n)
{
    if (n > 0 && n <= C277_VPS_MAX) { memcpy(dst, src, n); *dl = n; }
}

int c277_vtx_put(c277_vtx *v, const u8 *unit, u32 n, u32 now)
{
    c277_nal nl[C277_VNAL_MAX];
    int cnt, i, vcl = 0, idr = 0, keep = 0;
    u32 pos = 0;
    if (v->pending) { v->n_drop++; return C277_VTX_DROPPED; }
    if (n == 0 || n > C277_VAU_MAX) { v->n_drop++; return C277_VTX_DROPPED; }
    cnt = c277_annexb_split(unit, n, nl, C277_VNAL_MAX);
    /* first pass: parameter sets, what is VCL, is it an IDR */
    for (i = 0; i < cnt; i++) {
        int t = unit[nl[i].off] & 31;
        if (nl[i].len == 0) continue;
        if (t == 7) { keep_ps(v->sps, &v->sps_len, unit + nl[i].off, nl[i].len); v->n_params++; }
        else if (t == 8) keep_ps(v->pps, &v->pps_len, unit + nl[i].off, nl[i].len);
        else if (t >= 1 && t <= 5) { vcl = 1; if (t == 5) idr = 1; }
    }
    if (!vcl) return C277_VTX_PARAMS;
    if (idr && (v->sps_len == 0 || v->pps_len == 0)) { v->n_drop++; v->n_drop_idr++; return C277_VTX_DROPPED; }
    if (!idr && !v->sent_idr) { v->n_drop++; return C277_VTX_DROPPED; }
    /* keep the VCL (and other non-parameter, non-SEI/AUD) NAL units */
    v->n_nal = 0;
    for (i = 0; i < cnt; i++) {
        int t = unit[nl[i].off] & 31;
        if (nl[i].len == 0 || t == 7 || t == 8 || t == 6 || t == 9 || t == 12 || t > 5) continue;
        if (pos + nl[i].len > C277_VAU_MAX) break;
        memcpy(v->au + pos, unit + nl[i].off, nl[i].len);
        v->nal[v->n_nal].off = pos; v->nal[v->n_nal].len = nl[i].len;
        v->n_nal++; pos += nl[i].len; keep = 1;
    }
    if (!keep) return C277_VTX_PARAMS;
    if (!v->started) { v->started = 1; v->t0 = now; }
    v->au_ts = c277_vtx_ts_at(v, now);
    v->idr = idr;
    v->it_nal = 0; v->it_off = 0; v->it_stap = idr ? 1 : 0;
    v->pending = 1;
    if (idr) { v->sent_idr = 1; v->n_idr++; }
    v->n_au++;
    return C277_VTX_QUEUED;
}

/* RTP header (12) + one-byte extension header with the transport-cc seq (8). */
static u32 rtp_head(c277_vtx *v, u8 *o, int marker)
{
    o[0] = 0x90;                                  /* V=2 X=1 */
    o[1] = (u8)((marker ? 0x80 : 0) | C277_VPT);
    put16(o + 2, v->seq); v->seq = (u16)(v->seq + 1);
    put32(o + 4, v->au_ts);
    put32(o + 8, v->ssrc);
    o[12] = 0xBE; o[13] = 0xDE; o[14] = 0; o[15] = 1;
    o[16] = (u8)((C277_VEXT_ID << 4) | 1);        /* id 2, 2 bytes */
    put16(o + 17, v->tseq); v->tseq = (u16)(v->tseq + 1);
    o[19] = 0;
    return 20;
}

int c277_vtx_next(c277_vtx *v, u8 *out, u32 cap)
{
    u32 h, plen;
    int last;
    if (!v->pending || cap < 20 + C277_VMTU + 4) return 0;
    if (v->it_stap) {
        /* STAP-A: SPS + PPS ahead of an IDR */
        u8 nri = (u8)(v->sps[0] & 0x60);
        h = rtp_head(v, out, 0);
        out[h] = (u8)(nri | 24);
        put16(out + h + 1, v->sps_len); memcpy(out + h + 3, v->sps, v->sps_len);
        put16(out + h + 3 + v->sps_len, v->pps_len);
        memcpy(out + h + 5 + v->sps_len, v->pps, v->pps_len);
        plen = 1 + 2 + v->sps_len + 2 + v->pps_len;
        v->it_stap = 0;
        v->n_pk++; v->n_oct += plen;
        return (int)(h + plen);
    }
    {
        const c277_nal *nl = &v->nal[v->it_nal];
        const u8 *nal = v->au + nl->off;
        last = v->it_nal == v->n_nal - 1;
        if (nl->len <= C277_VMTU) {
            h = rtp_head(v, out, last);
            memcpy(out + h, nal, nl->len);
            plen = nl->len;
            v->it_nal++;
        } else {
            u32 left = nl->len - 1 - v->it_off, chunk = C277_VMTU - 2;
            int first = v->it_off == 0, end;
            if (left <= chunk) { chunk = left; end = 1; } else end = 0;
            h = rtp_head(v, out, last && end);
            out[h] = (u8)((nal[0] & 0x60) | 28);
            out[h + 1] = (u8)((first ? 0x80 : 0) | (end ? 0x40 : 0) | (nal[0] & 31));
            memcpy(out + h + 2, nal + 1 + v->it_off, chunk);
            plen = chunk + 2;
            v->it_off += chunk;
            if (end) { v->it_nal++; v->it_off = 0; }
        }
    }
    if (v->it_nal >= v->n_nal) v->pending = 0;
    v->n_pk++; v->n_oct += plen;
    return (int)(h + plen);
}

/* ---------------------------------------------------------------- RTCP */

int c277_rtcp_build_sr(u8 *out, u32 cap, u32 ssrc, u32 ntp_hi, u32 ntp_lo, u32 rtp_ts, u32 pk, u32 oct)
{
    static const u8 sdes_tail[] = { 0x01, 0x05, 'c', 'n', 'a', 'm', 'e', 0x00 };
    if (cap < 44) return -1;
    out[0] = 0x80; out[1] = 200; put16(out + 2, 6);
    put32(out + 4, ssrc); put32(out + 8, ntp_hi); put32(out + 12, ntp_lo);
    put32(out + 16, rtp_ts); put32(out + 20, pk); put32(out + 24, oct);
    out[28] = 0x81; out[29] = 202; put16(out + 30, 3);
    put32(out + 32, ssrc);
    memcpy(out + 36, sdes_tail, 8);
    return 44;
}

int c277_rtcp_build_pli(u8 *out, u32 cap, u32 sender, u32 media)
{
    if (cap < 12) return -1;
    out[0] = 0x81; out[1] = 206; put16(out + 2, 2);
    put32(out + 4, sender); put32(out + 8, media);
    return 12;
}

static u32 get32(const u8 *p) { return ((u32)p[0] << 24) | ((u32)p[1] << 16) | ((u32)p[2] << 8) | p[3]; }

int c277_rtcp_parse(const u8 *p, u32 n, u32 our_ssrc, c277_rtcp_info *o)
{
    u32 pos = 0;
    memset(o, 0, sizeof(*o));
    while (pos + 4 <= n) {
        u32 words, len, fmt, pt;
        const u8 *q = p + pos;
        if ((q[0] >> 6) != 2) return -1;
        fmt = q[0] & 31; pt = q[1];
        words = ((u32)q[2] << 8) | q[3];
        len = (words + 1) * 4;
        if (pos + len > n) return -1;
        if (pt == 200) o->n_sr++;
        else if (pt == 201) {
            u32 rc = fmt, k;
            o->n_rr++;
            for (k = 0; k < rc && 8 + 24 * (k + 1) <= len; k++) {
                const u8 *r = q + 8 + 24 * k;
                if (our_ssrc == 0 || get32(r) == our_ssrc) {
                    o->rr_have = 1; o->rr_fraction = r[4];
                    o->rr_lost = ((u32)r[5] << 16) | ((u32)r[6] << 8) | r[7];
                    o->rr_jitter = get32(r + 16);
                }
            }
        } else if (pt == 206 && len >= 12) {
            u32 media = get32(q + 8);
            if (fmt == 1 || fmt == 4) {
                if (our_ssrc == 0 || media == our_ssrc || media == 0) { if (fmt == 1) o->n_pli++; else o->n_fir++; }
                else if (fmt == 4 && len >= 16 && get32(q + 12) == our_ssrc) o->n_fir++;
            } else if (fmt == 15) o->n_remb++;
            else o->n_other++;
        } else if (pt == 205 && len >= 12) {
            if (fmt == 1) { if (our_ssrc == 0 || get32(q + 8) == our_ssrc) o->n_nack++; }
            else if (fmt == 15) o->n_twcc++;
            else o->n_other++;
        } else {
            o->n_other++;
        }
        pos += len;
    }
    return 0;
}
