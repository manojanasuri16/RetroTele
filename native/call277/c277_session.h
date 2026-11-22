/* c277_session.h - call orchestrator for the "2.7.7" voice path: ties the
 * transport + signalling EncryptedConnections, the reflector framing, the ICE
 * agent and RTP/jitter together. No sockets, no clock, no threads: the native
 * helper feeds datagrams/signalling payloads with a `now` in ms (wrap-safe u32)
 * and drains the output queue. C89, no malloc; the caller owns the struct
 * (about 60 KB: allocate it on the heap, not the Symbian stack). */
#ifndef C277_SESSION_H
#define C277_SESSION_H

#include "c277_conn.h"
#include "c277_refl.h"
#include "c277_ice.h"
#include "c277_rtp.h"

#define C277_SESS_RANDOM  56    /* random bytes required by init */
#define C277_OUT_MAX      1500  /* bytes per output item */
#define C277_OUTQ         16    /* output queue capacity */
#define C277_SIG_RX_MAX   8192  /* largest accepted signalling payload */

#define C277_OUT_UDP     1      /* datagram to send to ip:port (reflector framing already applied) */
#define C277_OUT_SIGNAL  2      /* blob for phone.sendSignalingData (an EncryptedConnection packet) */

#define C277_SESS_OK        0
#define C277_SESS_ERR_ARG  (-20)   /* init: no usable (non-tcp phoneConnection) entry or too few random bytes */
#define C277_SESS_ERR_BUSY (-21)   /* output queue full / path not up: retry later */
#define C277_SESS_ERR_BIG  (-22)   /* payload too large */

typedef struct {
    int kind;
    u32 ip, port;          /* UDP only (host order) */
    u32 len;
    u8  data[C277_OUT_MAX];
} c277_out_item;

typedef struct {
    int n;                 /* items queued; the consumer sets n = 0 after draining */
    c277_out_item item[C277_OUTQ];
} c277_outq;

/* One server-provided connection. webrtc != 0 for phoneConnectionWebrtc (ignored,
 * excluded from the id ranking). tcp != 0: not used but kept in the ranking. */
typedef struct {
    c277_id64 id;          /* signed 64-bit phoneConnection.id split as hi (signed) / lo */
    u32 ip, port;          /* host order */
    u8  peer_tag[16];
    int tcp, webrtc;
} c277_sess_conn;

typedef struct {
    c277_conn sig, tr;
    c277_ice ice;
    c277_rtp_tx rtp;
    c277_jb jb;
    int is_outgoing, ok;
    /* the one reflector path */
    u32 r_ip, r_port, rank, own_rt;
    u8  tag16[16];
    int refl_ready, hello_started;
    u32 next_hello;
    int cands_sent, media_state_sent;
    /* peer */
    int peer_audio, peer_cands;
    int audio_seen;
    u32 cur_now;
    u32 last_audio_rx;
    u32 n_rtp_rx, n_rtp_tx, n_stun_rx;
    c277_outq out;
    u8 tmp[C277_OUT_MAX], rtpb[C277_OUT_MAX];
    u8 scratch[C277_SIG_RX_MAX];
} c277_session;

/* key256: raw DH key. rnd: C277_SESS_RANDOM random bytes (nrnd = how many).
 * Returns C277_SESS_OK or C277_SESS_ERR_ARG. */
int c277_session_init(c277_session *s, const u8 *key256, int is_outgoing,
                      const c277_sess_conn *conns, u32 nconns, const u8 *rnd, u32 nrnd);

/* A datagram that arrived from ip:port (anything not from our reflector is ignored). */
void c277_session_on_udp(c277_session *s, u32 ip, u32 port, const u8 *d, u32 n, u32 now);

/* Payload of updatePhoneCallSignalingData. Returns 0 or a C277_ERR_* from c277_conn. */
int c277_session_on_signaling(c277_session *s, const u8 *d, u32 n, u32 now);

/* Run timers; appends due items to s->out. Call every <= 20 ms. Returns s->out.n. */
int c277_session_tick(c277_session *s, u32 now);

/* Send one Opus packet (any valid TOC; the RTP timestamp advances by its duration).
 * C277_SESS_ERR_BUSY until ICE is connected or if the output queue is full. */
int c277_session_send_opus(c277_session *s, const u8 *opus, u32 n, u32 now);

/* Next received Opus packet in sequence order: C277_JB_PACKET (out/len valid),
 * C277_JB_LOST (run PLC for one packet), C277_JB_EMPTY. */
int c277_session_poll_opus(c277_session *s, u8 *out, u32 cap, u32 *len);

void c277_outq_clear(c277_outq *q);

/* state */
int c277_session_signaling_acked(const c277_session *s);  /* our CandidatesList sent and acked */
int c277_session_refl_ready(const c277_session *s);
int c277_session_ice_connected(const c277_session *s);
int c277_session_ice_state(const c277_session *s);        /* C277_ICE_* */
int c277_session_media_flowing(const c277_session *s, u32 now);  /* RTP received within 2 s */
int c277_session_peer_audio_active(const c277_session *s); /* peer's RemoteMediaState says audio on */

#endif
