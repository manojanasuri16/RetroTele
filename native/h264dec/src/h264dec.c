/*
 * h264dec.c: the h264dec API (h264dec.h) on top of FFmpeg 0.6.7's H.264 decoder.
 * Built with H264DEC_HOOKS, which enables two small patches in libavcodec/h264.c
 * (size limit before allocation, no output delay in low-delay mode); see
 * native/third_party/ffmpeg/NOTICE.
 */
#include "config.h"
#include <string.h>
#include "libavcodec/avcodec.h"
#include "libavcodec/h264.h"
#include "h264dec.h"

extern AVCodec h264_decoder;

#define PAD FF_INPUT_BUFFER_PADDING_SIZE

struct h264dec {
    AVCodecContext *ctx;
    AVFrame pic;
    unsigned char *buf;       /* padded copy of the access unit */
    int buf_size;
    int max_area, max_side;
    int too_big;              /* the last access unit was refused by the size hook */
    int frames, errors;
    h264dec_log_fn log_fn;
    void *log_user;
};

/* called from h264.c (H264DEC_HOOKS) with the coded size of a new SPS */
int h264dec_size_ok(AVCodecContext *avctx, int w, int h)
{
    h264dec *d = (h264dec *)avctx->opaque;
    int side = w > h ? w : h;
    if (d == NULL)
        return 0;
    if (w <= 0 || h <= 0 || w * h > d->max_area || side > d->max_side) {
        d->too_big = 1;
        return -1;
    }
    return 0;
}

/* av_log sink: the callback is process-wide but stateless; the context comes from avcl */
static void h264dec_av_log(void *avcl, int level, const char *fmt, va_list vl)
{
    AVCodecContext *avctx = (AVCodecContext *)avcl;
    h264dec *d;
    char line[160];
    if (level > AV_LOG_ERROR || avctx == NULL)
        return;
    d = (h264dec *)avctx->opaque;
    if (d == NULL || d->log_fn == NULL)
        return;
    vsnprintf(line, sizeof(line), fmt, vl);
    line[sizeof(line) - 1] = 0;
    d->log_fn(d->log_user, line);
}

static int open_codec(h264dec *d)
{
    AVCodecContext *c = avcodec_alloc_context();
    if (c == NULL)
        return H264DEC_ERR_NOMEM;
    c->opaque = d;
    c->flags |= CODEC_FLAG_LOW_DELAY;      /* real-time video: output every picture at once */
    c->error_concealment = FF_EC_GUESS_MVS | FF_EC_DEBLOCK;
    c->error_recognition = FF_ER_CAREFUL;
    c->thread_count = 1;
    if (avcodec_open(c, &h264_decoder) < 0) {
        av_free(c);
        return H264DEC_ERR_NOMEM;
    }
    d->ctx = c;
    return 0;
}

static void close_codec(h264dec *d)
{
    if (d->ctx != NULL) {
        avcodec_close(d->ctx);
        av_free(d->ctx);
        d->ctx = NULL;
    }
}

h264dec *h264dec_create(int max_w, int max_h)
{
    h264dec *d;
    if (max_w <= 0 || max_h <= 0)
        return NULL;
    avcodec_init();                         /* one-time static tables (idempotent) */
    av_log_set_callback(h264dec_av_log);
    d = (h264dec *)av_mallocz(sizeof(*d));
    if (d == NULL)
        return NULL;
    d->max_area = ((max_w + 15) & ~15) * ((max_h + 15) & ~15);
    d->max_side = ((max_w > max_h ? max_w : max_h) + 15) & ~15;
    if (open_codec(d) < 0) {
        av_free(d);
        return NULL;
    }
    return d;
}

void h264dec_set_log(h264dec *d, h264dec_log_fn fn, void *user)
{
    if (d != NULL) {
        d->log_fn = fn;
        d->log_user = user;
    }
}

int h264dec_decode(h264dec *d, const unsigned char *au, int len, h264dec_frame *f)
{
    AVPacket pkt;
    int got = 0, r;
    H264Context *h;
    MpegEncContext *s;
    if (d == NULL || d->ctx == NULL || au == NULL || len <= 0 || f == NULL)
        return H264DEC_ERR_ARG;
    memset(f, 0, sizeof(*f));
    if (len + PAD > d->buf_size) {
        int n = len + PAD + 4096;
        av_free(d->buf);
        d->buf = (unsigned char *)av_malloc(n);
        if (d->buf == NULL) {
            d->buf_size = 0;
            return H264DEC_ERR_NOMEM;
        }
        d->buf_size = n;
    }
    memcpy(d->buf, au, len);
    memset(d->buf + len, 0, PAD);
    av_init_packet(&pkt);
    pkt.data = d->buf;
    pkt.size = len;
    d->too_big = 0;
    avcodec_get_frame_defaults(&d->pic);
    r = avcodec_decode_video2(d->ctx, &d->pic, &got, &pkt);
    if (d->too_big) {
        d->errors++;
        return H264DEC_ERR_TOOBIG;
    }
    if (r < 0) {
        d->errors++;
        return H264DEC_ERR;
    }
    if (!got || d->pic.data[0] == NULL)
        return H264DEC_NOFRAME;
    h = (H264Context *)d->ctx->priv_data;
    s = &h->s;
    {
        int cl = 2 * h->sps.crop_left, ct = 2 * h->sps.crop_top;
        if (cl >= d->ctx->width) cl = 0;
        if (ct >= d->ctx->height) ct = 0;
        f->stride_y = d->pic.linesize[0];
        f->stride_uv = d->pic.linesize[1];
        f->y = d->pic.data[0] + ct * f->stride_y + cl;
        f->u = d->pic.data[1] + (ct >> 1) * f->stride_uv + (cl >> 1);
        f->v = d->pic.data[2] + (ct >> 1) * f->stride_uv + (cl >> 1);
        f->crop_left = cl;
        f->crop_top = ct;
        f->width = d->ctx->width - cl;
        f->height = d->ctx->height - ct;
    }
    f->coded_width = 16 * s->mb_width;
    f->coded_height = 16 * s->mb_height;
    f->key = d->pic.key_frame;
    f->errors = s->error_count > 0 ? 1 : 0;
    f->profile = h->sps.profile_idc;
    f->level = h->sps.level_idc;
    d->frames++;
    return H264DEC_FRAME;
}

void h264dec_reset(h264dec *d)
{
    if (d == NULL)
        return;
    /* reopen: drops SPS/PPS, references and the frame buffers */
    close_codec(d);
    open_codec(d);
}

int h264dec_stats(h264dec *d, int *frames, int *errors)
{
    if (d == NULL)
        return -1;
    if (frames) *frames = d->frames;
    if (errors) *errors = d->errors;
    return 0;
}

void h264dec_destroy(h264dec *d)
{
    if (d == NULL)
        return;
    close_codec(d);
    av_free(d->buf);
    av_free(d);
}
