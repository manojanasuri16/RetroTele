/* c277_session.c - see c277_session.h. Flow per docs/CALL-277-SPEC.md sec. 1. */
#include <string.h>
#include "c277_session.h"

#define LATER(a, b) (((int)((a) - (b))) >= 0)

void c277_outq_clear(c277_outq *q) { q->n = 0; }

static c277_out_item *push(c277_session *s, int kind)
{
    c277_out_item *it;
    if (s->out.n >= C277_OUTQ) return 0;
    it = &s->out.item[s->out.n++];
    it->kind = kind; it->ip = 0; it->port = 0; it->len = 0;
    return it;
}

static int have_room(const c277_session *s) { return s->out.n < C277_OUTQ; }

/* wrap payload for the peer through the reflector and queue it */
static int push_wrapped(c277_session *s, u32 peer_rt, const u8 *p, u32 n)
{
    c277_out_item *it = push(s, C277_OUT_UDP);
    int w;
    if (!it) return -1;
    w = c277_refl_wrap(s->tag16, peer_rt, s->own_rt, p, n, it->data, C277_OUT_MAX);
    if (w < 0) { s->out.n--; return -1; }
    it->len = (u32)w; it->ip = s->r_ip; it->port = s->r_port;
    return 0;
}

int c277_session_init(c277_session *s, const u8 *key256, int is_outgoing,
                      const c277_sess_conn *conns, u32 nconns, const u8 *rnd, u32 nrnd)
{
    c277_id64 ids[16];
    u32 i, n = 0, sel = 0, nsel = 0, have = 0;
    memset(s, 0, sizeof(*s));
    if (nrnd < C277_SESS_RANDOM || nconns == 0) return C277_SESS_ERR_ARG;
    /* ids of ALL phoneConnection entries (tcp included, webrtc excluded) */
    for (i = 0; i < nconns && n < 16; i++) {
        if (conns[i].webrtc) continue;
        ids[n] = conns[i].id;
        if (!have && !conns[i].tcp) { have = 1; sel = i; nsel = n; }
        n++;
    }
    if (!have) return C277_SESS_ERR_ARG;
    s->is_outgoing = is_outgoing != 0;
    s->r_ip = conns[sel].ip; s->r_port = conns[sel].port;
    memcpy(s->tag16, conns[sel].peer_tag, 16);
    s->rank = c277_refl_rank(ids, n, nsel);
    s->own_rt = ((u32)rnd[44] << 24) | ((u32)rnd[45] << 16) | ((u32)rnd[46] << 8) | rnd[47];
    if (s->own_rt == 0) s->own_rt = 1;      /* pin:155-160: nonzero */
    c277_conn_init(&s->sig, key256, s->is_outgoing, 1);
    c277_conn_init(&s->tr, key256, s->is_outgoing, 0);
    c277_ice_init(&s->ice, s->is_outgoing, rnd);
    c277_ice_set_local(&s->ice, s->rank, s->own_rt, s->r_port, s->r_ip, s->r_port);
    c277_rtp_tx_init(&s->rtp, s->is_outgoing, rnd + 48);
    c277_jb_init(&s->jb);
    s->ok = 1;
    return C277_SESS_OK;
}


/* ---------------------------------------------------------------- capture */

static void cap_ch(c277_session *s, char ch)
{
    if (s->cap_len < C277_CAP_MAX) s->cap[s->cap_len++] = ch;
    else s->cap_drop++;
}
static void cap_str(c277_session *s, const char *t) { while (*t) cap_ch(s, *t++); }
static void cap_dec(c277_session *s, u32 v)
{
    char b[12]; int n = 0;
    if (v == 0) { cap_ch(s, '0'); return; }
    while (v) { b[n++] = (char)('0' + (int)(v % 10)); v /= 10; }
    while (n) cap_ch(s, b[--n]);
}
static void cap_hex8(c277_session *s, u32 v, int digits)
{
    int i;
    for (i = digits - 1; i >= 0; i--) cap_ch(s, "0123456789abcdef"[(v >> (4 * i)) & 15]);
}
static void cap_hexdump(c277_session *s, const u8 *p, u32 n, u32 max)
{
    u32 i;
    if (n > max) n = max;
    for (i = 0; i < n; i++) cap_hex8(s, p[i], 2);
}
static void cap_ascii(c277_session *s, const u8 *p, u32 n, u32 max)
{
    u32 i;
    if (n > max) n = max;
    for (i = 0; i < n; i++) cap_ch(s, (char)((p[i] >= 32 && p[i] < 127) ? p[i] : '.'));
}
static void cap_head(c277_session *s, const char *chan, int type, u32 len)
{
    cap_str(s, "t="); cap_dec(s, s->cur_now);
    cap_str(s, " "); cap_str(s, chan);
    cap_str(s, " id="); cap_dec(s, (u32)type);
    cap_str(s, " len="); cap_dec(s, len);
}

void c277_session_capture(c277_session *s, int on, int vid)
{
    s->cap_on = on != 0;
    s->vid_on = on != 0 && vid != 0;
}

u32 c277_session_cap_take(c277_session *s, char *out, u32 cap)
{
    u32 n = s->cap_len;
    if (n > cap) n = cap;
    memcpy(out, s->cap, n);
    memmove(s->cap, s->cap + n, s->cap_len - n);
    s->cap_len -= n;
    return n;
}

static void cap_sum_add(c277_session *s, int pt, u32 ssrc, u32 bytes)
{
    int i;
    if (s->vs_pk == 0) s->vs_start = s->cur_now;
    s->vs_pk++; s->vs_bytes += bytes;
    for (i = 0; i < s->vs_npt; i++) if (s->vs_pt[i] == (u32)pt) break;
    if (i == s->vs_npt && s->vs_npt < 4) s->vs_pt[s->vs_npt++] = (u32)pt;
    for (i = 0; i < s->vs_nssrc; i++) if (s->vs_ssrc[i] == ssrc) break;
    if (i == s->vs_nssrc && s->vs_nssrc < 4) s->vs_ssrc[s->vs_nssrc++] = ssrc;
}

static void cap_sum_flush(c277_session *s, u32 now)
{
    int i;
    if (!s->cap_on || (s->vs_pk == 0 && s->vs_rtcp == 0)) return;
    if ((u32)(now - s->vs_start) < 1000UL) return;
    cap_str(s, "t="); cap_dec(s, now);
    cap_str(s, " vsum pk="); cap_dec(s, s->vs_pk);
    cap_str(s, " bytes="); cap_dec(s, s->vs_bytes);
    cap_str(s, " rtcp="); cap_dec(s, s->vs_rtcp);
    cap_str(s, " pt=");
    for (i = 0; i < s->vs_npt; i++) { if (i) cap_ch(s, ','); cap_dec(s, s->vs_pt[i]); }
    cap_str(s, " ssrc=");
    for (i = 0; i < s->vs_nssrc; i++) { if (i) cap_ch(s, ','); cap_hex8(s, s->vs_ssrc[i], 8); }
    cap_str(s, " drop="); cap_dec(s, s->cap_drop);
    cap_ch(s, '\n');
    s->vs_pk = 0; s->vs_bytes = 0; s->vs_rtcp = 0; s->vs_npt = 0; s->vs_nssrc = 0;
    s->vs_start = now;
}

static void cap_rtcp(c277_session *s, int type, const u8 *b, u32 n)
{
    s->vn_rtcp++; s->vs_rtcp++;
    if (s->vs_pk == 0 && s->vs_rtcp == 1) s->vs_start = s->cur_now;
    if (s->vn_rtcp > 30) return;
    cap_head(s, "tr", type, n);
    cap_str(s, " RTCP pt="); cap_dec(s, n > 1 ? b[1] : 0);
    cap_str(s, " fmt="); cap_dec(s, n > 0 ? (u32)(b[0] & 31) : 0);
    cap_str(s, " hex="); cap_hexdump(s, b, n, 64); cap_ch(s, '\n');
}

/* one decrypted message (chan 0 = signalling, 1 = transport) */
static void cap_msg(c277_session *s, int chan, int type, const u8 *body, u32 blen)
{
    c277_rtp_hdr h;
    const char *cn = chan ? "tr" : "sig";
    if (!s->cap_on) return;
    if (type == C277_MSG_AUDIO || type == C277_MSG_VIDEO) {
        if (c277_rtp_is_rtcp(body, blen)) { cap_rtcp(s, type, body, blen); return; }
        if (type == C277_MSG_AUDIO) {
            s->vn_audio++;
            if (s->vn_audio > 3) return;
            cap_head(s, cn, type, blen); cap_str(s, " audio\n");
            return;
        }
        s->vn_vid++;
        if (c277_rtp_parse(body, blen, &h) < 0) {
            if (s->vn_vid <= 30) { cap_head(s, cn, type, blen); cap_str(s, " badrtp hex="); cap_hexdump(s, body, blen, 64); cap_ch(s, '\n'); }
            return;
        }
        cap_sum_add(s, h.pt, h.ssrc, blen);
        if (s->vn_vid <= 30) {
            cap_head(s, cn, type, blen);
            cap_str(s, " VideoData pt="); cap_dec(s, (u32)h.pt);
            cap_str(s, " ssrc="); cap_hex8(s, h.ssrc, 8);
            cap_str(s, " seq="); cap_dec(s, h.seq);
            cap_str(s, " ts="); cap_dec(s, h.ts);
            cap_str(s, " m="); cap_dec(s, (u32)(h.marker != 0));
            cap_str(s, " plen="); cap_dec(s, h.plen);
            cap_str(s, " p8="); cap_hexdump(s, h.payload, h.plen, 8);
            cap_str(s, " hex="); cap_hexdump(s, body, blen, 64);
            cap_ch(s, '\n');
        }
        return;
    }
    cap_head(s, cn, type, blen);
    if (type == C277_MSG_CANDIDATES) { cap_str(s, " candidates (not dumped)\n"); return; }
    cap_str(s, " hex=");
    cap_hexdump(s, body, blen, type == C277_MSG_VIDEOFORMATS ? 1200 : 600);
    if (type == C277_MSG_VIDEOFORMATS) { cap_str(s, " ascii="); cap_ascii(s, body, blen, 1200); }
    cap_ch(s, '\n');
}

static void put_be32(u8 *p, u32 v)
{
    p[0] = (u8)(v >> 24); p[1] = (u8)(v >> 16); p[2] = (u8)(v >> 8); p[3] = (u8)v;
}

/* our minimal VideoFormats: H264 only (spec 1.3). Returns body length. */
static u32 build_videoformats(u8 *o)
{
    static const char *kv[3][2] = {
        { "level-asymmetry-allowed", "1" }, { "packetization-mode", "1" }, { "profile-level-id", "42e01f" } };
    u32 n = 0, i, l;
    o[n++] = 1;
    put_be32(o + n, 4); n += 4; memcpy(o + n, "H264", 4); n += 4;
    o[n++] = 3;
    for (i = 0; i < 3; i++) {
        l = (u32)strlen(kv[i][0]); put_be32(o + n, l); n += 4; memcpy(o + n, kv[i][0], l); n += l;
        l = (u32)strlen(kv[i][1]); put_be32(o + n, l); n += 4; memcpy(o + n, kv[i][1], l); n += l;
    }
    o[n++] = 1;                 /* encodersCount */
    return n;
}

/* ---------------------------------------------------------------- receive */

static void cb_sig(void *user, int type, const u8 *body, u32 blen)
{
    c277_session *s = (c277_session *)user;
    int k;
    cap_msg(s, 0, type, body, blen);
    if (s->vid_on && type == C277_MSG_VIDEOFORMATS && !s->vf_sent) s->vf_reply = 1;
    if (type == C277_MSG_CANDIDATES) {
        k = c277_ice_on_candidates(&s->ice, body, blen);
        if (k > 0) s->peer_cands += k;
    }
    /* VideoFormats etc.: acked by c277_conn, otherwise ignored */
}

static void cb_tr(void *user, int type, const u8 *body, u32 blen)
{
    c277_session *s = (c277_session *)user;
    c277_rtp_hdr h;
    cap_msg(s, 1, type, body, blen);
    if (type == C277_MSG_AUDIO) {
        if (c277_rtp_is_rtcp(body, blen)) return;
        if (c277_rtp_parse(body, blen, &h) < 0 || h.pt != C277_RTP_PT || h.plen == 0) return;
        s->n_rtp_rx++;
        s->audio_seen = 1;
        s->last_audio_rx = s->cur_now;
        c277_jb_put(&s->jb, h.seq, h.ts, h.payload, h.plen);
    } else if (type == C277_MSG_MEDIASTATE && blen >= 1) {
        int a, v;
        c277_msg_media_state_parse(body[0], &a, &v);
        s->peer_audio = a == 1;
        if (s->cap_on) {
            cap_str(s, "t="); cap_dec(s, s->cur_now);
            cap_str(s, " RemoteMediaState audio="); cap_dec(s, (u32)a);
            cap_str(s, " video="); cap_dec(s, (u32)v); cap_ch(s, '\n');
        }
    }
}

void c277_session_on_udp(c277_session *s, u32 ip, u32 port, const u8 *d, u32 n, u32 now)
{
    c277_refl_rx rx;
    u32 peer;
    int r;
    if (!s->ok || ip != s->r_ip || port != s->r_port) return;
    c277_refl_parse(d, n, s->tag16, &rx);
    if (rx.kind == C277_REFL_NONE) return;
    s->refl_ready = 1;
    if (rx.kind != C277_REFL_DATA) return;
    s->cur_now = now;
    if (c277_stun_is_stun(rx.payload, rx.payload_len)) {
        s->n_stun_rx++;
        r = c277_ice_rx(&s->ice, now, rx.payload, rx.payload_len, rx.sender_tag, s->tmp, C277_OUT_MAX);
        if (r > 0 && have_room(s)) {
            if (!c277_ice_peer_tag(&s->ice, &peer)) peer = rx.sender_tag;
            push_wrapped(s, peer, s->tmp, (u32)r);
        }
        return;
    }
    if (rx.payload_len + 0 > C277_SIG_RX_MAX) return;
    if (c277_conn_parse(&s->tr, now, rx.payload, rx.payload_len, s->scratch, cb_tr, s) == 0)
        c277_ice_activity(&s->ice, now);
}

int c277_session_on_signaling(c277_session *s, const u8 *d, u32 n, u32 now)
{
    if (!s->ok) return C277_SESS_ERR_ARG;
    if (n > C277_SIG_RX_MAX) return C277_SESS_ERR_BIG;
    s->cur_now = now;
    return c277_conn_parse(&s->sig, now, d, n, s->scratch, cb_sig, s);
}

/* ---------------------------------------------------------------- timers */

int c277_session_tick(c277_session *s, u32 now)
{
    c277_out_item *it;
    int n, k;
    u32 peer;

    if (!s->ok) return 0;
    /* 1. HELLO: every 500 ms until READY, then every 10 s (spec 2.2) */
    if (have_room(s) && (!s->hello_started || LATER(now, s->next_hello))) {
        n = c277_refl_build_hello(s->tag16, s->own_rt, s->tmp, C277_OUT_MAX);
        if (n > 0 && (it = push(s, C277_OUT_UDP)) != 0) {
            memcpy(it->data, s->tmp, (u32)n);
            it->len = (u32)n; it->ip = s->r_ip; it->port = s->r_port;
            s->hello_started = 1;
            s->next_hello = now + (s->refl_ready ? 10000UL : 500UL);
        }
    }
    /* 2. our candidate, once the reflector is READY (spec sec.1 step 2-3), reliable on signalling */
    if (s->refl_ready && !s->cands_sent && have_room(s)) {
        n = c277_ice_build_candidates(&s->ice, s->rtpb, C277_OUT_MAX);
        if (n > 0) {
            it = push(s, C277_OUT_SIGNAL);
            k = c277_conn_build(&s->sig, now, C277_MSG_CANDIDATES, s->rtpb, (u32)n, 1, it->data, C277_OUT_MAX);
            if (k > 0) { it->len = (u32)k; s->cands_sent = 1; }
            else s->out.n--;
        }
    }
    /* 3. signalling acks / resends */
    if (have_room(s)) {
        it = &s->out.item[s->out.n];
        k = c277_conn_tick(&s->sig, now, it->data, C277_OUT_MAX);
        if (k > 0) { push(s, C277_OUT_SIGNAL); it->len = (u32)k; }
    }
    /* 4. ICE binding requests */
    if (s->refl_ready && have_room(s)) {
        k = c277_ice_tick(&s->ice, now, s->tmp, C277_OUT_MAX);
        if (k > 0 && c277_ice_peer_tag(&s->ice, &peer)) push_wrapped(s, peer, s->tmp, (u32)k);
    }
    /* 5. once connected: RemoteMediaState{audio=1} reliable on transport (spec sec.1 step 6) */
    if (c277_ice_state(&s->ice) == C277_ICE_CONNECTED && !s->media_state_sent && have_room(s) &&
        c277_ice_peer_tag(&s->ice, &peer)) {
        u8 b = c277_msg_media_state_build(1, 0);
        k = c277_conn_build(&s->tr, now, C277_MSG_MEDIASTATE, &b, 1, 1, s->tmp, C277_OUT_MAX);
        if (k > 0 && push_wrapped(s, peer, s->tmp, (u32)k) == 0) s->media_state_sent = 1;
    }
    /* 5b. video capture reply: our VideoFormats (signalling), then RemoteMediaState video=0 */
    if (s->vid_on && s->vf_reply && !s->vf_sent && have_room(s)) {
        u8 vf[96];
        u32 vl = build_videoformats(vf);
        it = push(s, C277_OUT_SIGNAL);
        k = c277_conn_build(&s->sig, now, C277_MSG_VIDEOFORMATS, vf, vl, 1, it->data, C277_OUT_MAX);
        if (k > 0) {
            it->len = (u32)k; s->vf_sent = 1; s->ms_resend = 1;
            if (s->cap_on) { cap_str(s, "t="); cap_dec(s, now); cap_str(s, " sent our VideoFormats H264\n"); }
        } else s->out.n--;
    }
    if (s->ms_resend && s->media_state_sent && have_room(s) && c277_ice_peer_tag(&s->ice, &peer)) {
        u8 b2 = c277_msg_media_state_build(1, 0);
        k = c277_conn_build(&s->tr, now, C277_MSG_MEDIASTATE, &b2, 1, 1, s->tmp, C277_OUT_MAX);
        if (k > 0 && push_wrapped(s, peer, s->tmp, (u32)k) == 0) {
            s->ms_resend = 0;
            if (s->cap_on) { cap_str(s, "t="); cap_dec(s, now); cap_str(s, " sent RemoteMediaState video=0\n"); }
        }
    }
    cap_sum_flush(s, now);
    /* 6. transport acks / resends */
    if (have_room(s) && c277_ice_peer_tag(&s->ice, &peer)) {
        k = c277_conn_tick(&s->tr, now, s->tmp, C277_OUT_MAX);
        if (k > 0) push_wrapped(s, peer, s->tmp, (u32)k);
    }
    return s->out.n;
}

int c277_session_send_opus(c277_session *s, const u8 *opus, u32 n, u32 now)
{
    u32 peer;
    int r, k;
    if (!s->ok || c277_ice_state(&s->ice) != C277_ICE_CONNECTED || !c277_ice_peer_tag(&s->ice, &peer) ||
        !have_room(s))
        return C277_SESS_ERR_BUSY;
    if (n == 0 || n > 1200) return C277_SESS_ERR_BIG;
    r = c277_rtp_tx_build(&s->rtp, opus, n, s->rtpb, C277_OUT_MAX);
    if (r < 0) return C277_SESS_ERR_BIG;
    k = c277_conn_build(&s->tr, now, C277_MSG_AUDIO, s->rtpb, (u32)r, 0, s->tmp, C277_OUT_MAX);
    if (k < 0) return C277_SESS_ERR_BIG;
    if (push_wrapped(s, peer, s->tmp, (u32)k) < 0) return C277_SESS_ERR_BUSY;
    s->n_rtp_tx++;
    return C277_SESS_OK;
}

int c277_session_poll_opus(c277_session *s, u8 *out, u32 cap, u32 *len)
{
    *len = 0;
    return c277_jb_get(&s->jb, out, cap, len, 0);
}

int c277_session_signaling_acked(const c277_session *s) { return s->cands_sent && c277_conn_pending(&s->sig) == 0; }
int c277_session_refl_ready(const c277_session *s) { return s->refl_ready; }
int c277_session_ice_connected(const c277_session *s) { return c277_ice_state(&s->ice) == C277_ICE_CONNECTED; }
int c277_session_ice_state(const c277_session *s) { return c277_ice_state(&s->ice); }
int c277_session_media_flowing(const c277_session *s, u32 now)
{
    return s->audio_seen && (u32)(now - s->last_audio_rx) < 2000UL;
}
int c277_session_peer_audio_active(const c277_session *s) { return s->peer_audio; }
