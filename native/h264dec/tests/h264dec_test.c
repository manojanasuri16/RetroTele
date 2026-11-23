/*
 * h264dec_test: host test for h264dec. Splits an Annex-B file into access units, decodes them
 * and writes the pictures as raw YUV 4:2:0 (each at its own size) so the output can be
 * compared byte for byte with ffmpeg's.
 *
 *   h264dec_test in.264 out.yuv [-max W H] [-skip-to-idr] [-drop N] [-time]
 *     -skip-to-idr  feed nothing before the first IDR access unit (a receiver joining late)
 *     -drop N       drop every Nth non-IDR access unit (loss test; output not comparable)
 *     -time         print decode time per frame
 *     -start K      skip the first K access units (joining mid-stream, before a PLI's IDR)
 *     -fuzz SEED R  corrupt about R bytes per 10000 (robustness test; output not comparable)
 *     -fast         h264dec_set_fast(1): no deblocking on P pictures (output not comparable)
 *     -loop N       decode the whole file N times (benchmark; writes only the first pass)
 *     -sums FILE    write "au OFFSET LENGTH" per access unit and "frame FNV1A" per picture
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include "h264dec.h"

static unsigned char *load(const char *p, long *n)
{
    FILE *f = fopen(p, "rb");
    unsigned char *b;
    if (!f) return NULL;
    fseek(f, 0, SEEK_END); *n = ftell(f); fseek(f, 0, SEEK_SET);
    b = (unsigned char *)malloc(*n + 16);
    if (fread(b, 1, *n, f) != (size_t)*n) { fclose(f); free(b); return NULL; }
    fclose(f);
    return b;
}

/* next start code at or after p: returns its offset (start of 00 00 01), or n */
static long next_sc(const unsigned char *b, long p, long n)
{
    for (; p + 2 < n; p++)
        if (b[p] == 0 && b[p + 1] == 0 && b[p + 2] == 1) return p;
    return n;
}

/* FNV-1a over the visible Y, U, V rows (the N79 benchmark checks the same sums) */
static unsigned int h264dec_fnv(const h264dec_frame *f)
{
    unsigned int h = 2166136261u;
    int x, y;
    for (y = 0; y < f->height; y++)
        for (x = 0; x < f->width; x++) h = (h ^ f->y[y * f->stride_y + x]) * 16777619u;
    for (y = 0; y < f->height / 2; y++)
        for (x = 0; x < f->width / 2; x++) h = (h ^ f->u[y * f->stride_uv + x]) * 16777619u;
    for (y = 0; y < f->height / 2; y++)
        for (x = 0; x < f->width / 2; x++) h = (h ^ f->v[y * f->stride_uv + x]) * 16777619u;
    return h;
}

static void logf_(void *u, const char *m) { (void)u; fprintf(stderr, "dec: %s", m); }

static double now_ms(void)
{
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec * 1000.0 + t.tv_nsec / 1e6;
}

int main(int argc, char **argv)
{
    long n, p, au_start = -1;
    unsigned char *b;
    FILE *out;
    h264dec *d;
    int maxw = 720, maxh = 1280, skip = 0, drop = 0, timing = 0, i;
    int nau = 0, nframes = 0, nerr = 0, seen_slice = 0, seen_idr = 0, lastw = 0, lasth = 0;
    int au_has_idr = 0, ndropped = 0, nonidr = 0, start = 0, fuzz = 0, loops = 1, pass;
    unsigned int seed = 1;
    int fast = 0;
    unsigned char *tmp = NULL;
    FILE *sums = NULL;
    double total = 0, worst = 0;
    if (argc < 3) { fprintf(stderr, "usage: %s in.264 out.yuv [-max W H] [-skip-to-idr] [-drop N] [-time]\n", argv[0]); return 2; }
    for (i = 3; i < argc; i++) {
        if (!strcmp(argv[i], "-max") && i + 2 < argc) { maxw = atoi(argv[i + 1]); maxh = atoi(argv[i + 2]); i += 2; }
        else if (!strcmp(argv[i], "-skip-to-idr")) skip = 1;
        else if (!strcmp(argv[i], "-drop") && i + 1 < argc) drop = atoi(argv[++i]);
        else if (!strcmp(argv[i], "-time")) timing = 1;
        else if (!strcmp(argv[i], "-start") && i + 1 < argc) start = atoi(argv[++i]);
        else if (!strcmp(argv[i], "-fuzz") && i + 2 < argc) { seed = atoi(argv[i + 1]); fuzz = atoi(argv[i + 2]); i += 2; }
        else if (!strcmp(argv[i], "-loop") && i + 1 < argc) loops = atoi(argv[++i]);
        else if (!strcmp(argv[i], "-fast")) fast = 1;
        else if (!strcmp(argv[i], "-sums") && i + 1 < argc) sums = fopen(argv[++i], "w");
    }
    b = load(argv[1], &n);
    if (!b) { fprintf(stderr, "cannot read %s\n", argv[1]); return 2; }
    out = fopen(argv[2], "wb");
    d = h264dec_create(maxw, maxh);
    if (!d || !out) { fprintf(stderr, "init failed\n"); return 2; }
    h264dec_set_log(d, logf_, NULL);
    if (fast) h264dec_set_fast(d, 1);
    tmp = (unsigned char *)malloc(n + 16);
    for (pass = 0; pass < loops; pass++) {
    int au_index = 0;
    p = next_sc(b, 0, n);
    au_start = -1; seen_slice = 0; au_has_idr = 0;
    while (1) {
        long q = (p < n) ? next_sc(b, p + 3, n) : n;
        int t = (p + 3 < n) ? (b[p + 3] & 31) : -1;
        int boundary = 0;
        /* a new access unit starts at AUD/SPS/PPS/SEI or a slice with first_mb == 0, once the
         * current one holds a slice */
        if (p >= n) boundary = 1;
        else if (seen_slice && (t == 9 || t == 7 || t == 8 || t == 6)) boundary = 1;
        else if (seen_slice && (t == 1 || t == 5) && p + 4 < n && (b[p + 4] & 0x80)) boundary = 1;
        if (boundary && au_start >= 0) {
            int feed = 1;
            if (skip && !seen_idr && !au_has_idr) feed = 0;
            if (au_has_idr) seen_idr = 1;
            if (drop > 0 && !au_has_idr && (++nonidr % drop) == 0) { feed = 0; ndropped++; }
            if (au_index++ < start) feed = 0;
            if (feed) {
                h264dec_frame f;
                double t0, dt;
                const unsigned char *au = b + au_start;
                int len = (int)(p - au_start), r;
                if (fuzz > 0) {
                    int k;
                    memcpy(tmp, au, len);
                    for (k = 4; k < len; k++) {
                        seed = seed * 1103515245u + 12345u;
                        if ((seed >> 8) % 10000 < (unsigned)fuzz) tmp[k] ^= (unsigned char)(1 << ((seed >> 4) & 7));
                    }
                    au = tmp;
                }
                if (sums && pass == 0) fprintf(sums, "au %ld %d\n", au_start, len);
                t0 = now_ms();
                r = h264dec_decode(d, au, len, &f);
                dt = now_ms() - t0;
                total += dt; if (dt > worst) worst = dt;
                nau++;
                if (r == H264DEC_FRAME) {
                    int y;
                    if (f.width != lastw || f.height != lasth) {
                        fprintf(stderr, "frame %d: %dx%d profile %d level %d%s\n", nframes, f.width, f.height, f.profile, f.level, f.key ? " key" : "");
                        lastw = f.width; lasth = f.height;
                    }
                    if (sums && pass == 0) fprintf(sums, "frame %08x %d %d\n", h264dec_fnv(&f), f.width, f.height);
                    if (pass == 0) {
                    for (y = 0; y < f.height; y++) fwrite(f.y + y * f.stride_y, 1, f.width, out);
                    for (y = 0; y < f.height / 2; y++) fwrite(f.u + y * f.stride_uv, 1, f.width / 2, out);
                    for (y = 0; y < f.height / 2; y++) fwrite(f.v + y * f.stride_uv, 1, f.width / 2, out);
                    }
                    if (timing) fprintf(stderr, "frame %d %.2f ms%s%s\n", nframes, dt, f.key ? " key" : "", f.errors ? " concealed" : "");
                    nframes++;
                } else if (r < 0) {
                    nerr++;
                    if (!fuzz) fprintf(stderr, "au %d: error %d\n", nau, r);
                }
            }
            au_start = -1; seen_slice = 0; au_has_idr = 0;
        }
        if (p >= n) break;
        if (au_start < 0) au_start = p;
        if (t == 1 || t == 5) seen_slice = 1;
        if (t == 5) au_has_idr = 1;
        p = q;
    }
    }
    fprintf(stderr, "%d access units, %d frames, %d errors, %d dropped, avg %.3f ms, worst %.3f ms\n",
            nau, nframes, nerr, ndropped, nau ? total / nau : 0.0, worst);
    h264dec_destroy(d);
    fclose(out);
    free(b);
    free(tmp);
    if (sums) fclose(sums);
    if (fuzz || start || fast) return nframes > 0 ? 0 : 1;
    return nerr ? 1 : 0;
}
