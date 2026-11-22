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

/* ---------------------------------------------------------------- receive */

static void cb_sig(void *user, int type, const u8 *body, u32 blen)
{
    c277_session *s = (c277_session *)user;
    int k;
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
