# MTProto 2.0 session over TCP (intermediate transport) for RetroTele.
# Single-threaded and callback based (PyS60 sockets only work on the main
# thread). Python 2.2 compatible; see tgcrypto.py for the integer rules.
#
# events object (supplied by the client):
#   log(text)                     diagnostics
#   status(text)                  short progress text for the UI (may redraw)
#   saved(session)                auth key or salt changed: persist it
#   update(obj)                   an Updates object pushed by the server
#   connected(session)            ready for encrypted requests
#   disconnected(session, why)    connection lost (the session reconnects itself)

import time
import struct
import sys

import tgcrypto
from tgcrypto import sha1, sha256, ige_encrypt, ige_decrypt, random_bytes
from tgcrypto import bytes_to_long, long_to_bytes, xor_bytes
import tl
from tl import pack_int, pack_uint, pack_long, pack_bytes, Reader, Raw, TLError

P32 = 4294967296

# Telegram production RSA keys: (fingerprint, modulus hex); exponent 65537
RSA_KEYS = [
    (847625836280919973, "aeec36c8ffc109cb099624685b97815415657bd76d8c9c3e398103d7ad16c9bba6f525ed0412d7ae2c2de2b44e77d72cbf4b7438709a4e646a05c43427c7f184debf72947519680e651500890c6832796dd11f772c25ff8f576755afe055b0a3752c696eb7d8da0d8be1faf38c9bdd97ce0a77d3916230c4032167100edd0f9e7a3a9b602d04367b689536af0d64b613ccba7962939d3b57682beb6dae5b608130b2e52aca78ba023cf6ce806b1dc49c72cf928a7199d22e3d7ac84e47bc9427d0236945d10dbd15177bab413fbf0edfda09f014c7a7da088dde9759702ca760af2b8e4e97cc055c617bd74c3d97008635b98dc4d621b4891da9fb0473047927"),
    (1562291298945373506, "bdf2c77d81f6afd47bd30f29ac76e55adfe70e487e5e48297e5a9055c9c07d2b93b4ed3994d3eca5098bf18d978d54f8b7c713eb10247607e69af9ef44f38e28f8b439f257a11572945cc0406fe3f37bb92b79112db69eedf2dc71584a661638ea5becb9e23585074b80d57d9f5710dd30d2da940e0ada2f1b878397dc1a72b5ce2531b6f7dd158e09c828d03450ca0ff8a174deacebcaa22dde84ef66ad370f259d18af806638012da0ca4a70baa83d9c158f3552bc9158e69bf332a45809e1c36905a5caa12348dd57941a482131be7b2355a5f4635374f3bd3ddf5ff925bf4809ee27c1e67d9120c5fe08a9de458b1b4a3c5d0a428437f2beca81f4e2d5ff"),
    (-5859577972006586033, "b3f762b739be98f343eb1921cf0148cfa27ff7af02b6471213fed9daa0098976e667750324f1abcea4c31e43b7d11f1579133f2b3d9fe27474e462058884e5e1b123be9cbbc6a443b2925c08520e7325e6f1a6d50e117eb61ea49d2534c8bb4d2ae4153fabe832b9edf4c5755fdd8b19940b81d1d96cf433d19e6a22968a85dc80f0312f596bd2530c1cfb28b5fe019ac9bc25cd9c2a5d8a0f3a1c0c79bcca524d315b5e21b5c26b46babe3d75d06d1cd33329ec782a0f22891ed1db42a1d6c0dea431428bc4d7aabdcf3e0eb6fda4e23eb7733e7727e9a1915580796c55188d2596d2665ad1182ba7abf15aaa5a8b779ea996317a20ae044b820bff35b6e8a1"),
    (6491968696586960280, "be6a71558ee577ff03023cfa17aab4e6c86383cff8a7ad38edb9fafe6f323f2d5106cbc8cafb83b869cffd1ccf121cd743d509e589e68765c96601e813dc5b9dfc4be415c7a6526132d0035ca33d6d6075d4f535122a1cdfe017041f1088d1419f65c8e5490ee613e16dbf662698c0f54870f0475fa893fc41eb55b08ff1ac211bc045ded31be27d12c96d8d3cfc6a7ae8aa50bf2ee0f30ed507cc2581e3dec56de94f5dc0a7abee0be990b893f2887bd2c6310a1e0a9e3e38bd34fded2541508dc102a9c9b4c95effd9dd2dfe96c29be647d6c69d66ca500843cfaed6e440196f1dbe0e2e22163c61ca48c79116fa77216726749a976a1c4b0944b5121e8c01"),
]

# The 2048-bit safe prime Telegram uses for DH (checked instead of a slow
# primality test on the phone).
DH_PRIME = ("c71caeb9c6b1c9048e6c522f70f13f73980d40238e3e21c14934d037563d930f"
            "48198a0aa7c14058229493d22530f4dbfa336f6e0ac925139543aed44cce7c37"
            "20fd51f69458705ac68cd4fe6b6b13abdc9746512969328454f18faf8c595f64"
            "2477fe96bb2a941d5bcd1d4ac8cc49880708fa9b378e3c4f3a9060bee67cf9a4"
            "a4a695811051907e162753b56b0f6b410dba74d8a84b2a14b3144e0ef1284754"
            "fd17ed950d5965b4b9dd46582db1178d169c6bc465b0d6ff9ca3928fef5b9ae4"
            "e418fc15e83ebea0f87fa9ff5eed70050ded2849f47bf959d956850ce929851f"
            "0d8115f635b105ee2e4e15d04b2454bf6f4fadf034b10403119cd8e3b92fcc5b")

DC_IPS = {1: "149.154.175.53", 2: "149.154.167.51", 3: "149.154.175.100",
          4: "149.154.167.91", 5: "91.108.56.130"}

ID_CONTAINER = 1945237724       # 0x73f1f8dc
ID_RPC_RESULT = 4082920705      # 0xf35c6d01
ID_RPC_ERROR = 558156313        # 0x2144ca19
ID_PONG = 880243653             # 0x347773c5
ID_BAD_SALT = 3987424379        # 0xedab447b
ID_BAD_MSG = 2817521681         # 0xa7eff811
ID_NEW_SESSION = 2663516424     # 0x9ec20908
ID_MSGS_ACK = 1658238041        # 0x62d6b459
ID_DETAILED = 661470918         # 0x276d3ec6
ID_NEW_DETAILED = 2157819615    # 0x809db6df
ID_STATE_INFO = 81704317        # 0x04deb57d
ID_FUTURE_SALTS = 2924480661    # 0xae500895


def pack_msg_id(v):
    return struct.pack("<II", v % P32, (v / P32) % P32)


def err_text():
    return str(sys.exc_info()[1])


class RpcError(Exception):
    def __init__(self, code, message):
        Exception.__init__(self, "%d %s" % (code, message))
        self.code = code
        self.message = message


class Request:
    def __init__(self, name, body, rtype, on_ok, on_err, content=1):
        self.name = name
        self.body = body
        self.rtype = rtype
        self.on_ok = on_ok
        self.on_err = on_err
        self.content = content
        self.msg_id = None
        self.sent = 0


class Session:
    """One MTProto connection to one data centre."""

    def __init__(self, net, schema, events, dc_id, auth_key=None, salt=None,
                 time_offset=0, init_query=None, port=443, ip=None):
        self.net = net
        self.schema = schema
        self.w = tl.Writer(schema)
        self.events = events
        self.dc_id = dc_id
        self.ip = ip or DC_IPS[dc_id]
        self.port = port
        self.init_query = init_query     # function(inner_bytes) -> wrapped bytes
        self.time_offset = time_offset
        self.set_key(auth_key)
        self.salt = salt or "\x00" * 8
        self.conn = None
        self.state = "idle"     # idle, connecting, dh, ready, closed
        self.inbuf = []
        self.inlen = 0
        self.outq = []
        self.sending = 0
        self.queue = []         # requests waiting for "ready"
        self.pending = {}       # msg_id -> Request
        self.acks = []
        self.last_msg_id = 0
        self.inited = 0
        self.backoff = 1
        self.last_rx = time.time()
        self.ping_armed = 0
        self.gen = 0            # connection generation (stale callbacks are ignored)
        self.verify = 0         # check msg_key (SHA-256 of every packet; slow on the phone)
        self.rxq = []           # received packets waiting to be decrypted
        self.rx_job = None
        self.new_session()

    # ---------------------------------------------------------- basics

    def set_key(self, key):
        self.auth_key = key
        if key:
            self.auth_key_id = sha1(key)[12:20]
        else:
            self.auth_key_id = None

    def new_session(self):
        self.session_id = random_bytes(8)
        self.seq = 0
        self.inited = 0

    def log(self, msg):
        self.events.log("dc%d: %s" % (self.dc_id, msg))

    def now(self):
        return time.time() + self.time_offset

    def next_msg_id(self):
        t = self.now()
        secs = long(t)
        frac = long((t - secs) * P32)
        mid = secs * P32 + frac - frac % 4
        if mid <= self.last_msg_id:
            mid = self.last_msg_id + 4
        self.last_msg_id = mid
        return mid

    def next_seq(self, content):
        if content:
            s = self.seq * 2 + 1
            self.seq = self.seq + 1
            return s
        return self.seq * 2

    # ---------------------------------------------------------- connection

    def start(self):
        if self.state in ("connecting", "dh", "ready"):
            return
        self.state = "connecting"
        self.gen = self.gen + 1
        gen = self.gen
        self.inbuf = []
        self.inlen = 0
        self.outq = []
        self.sending = 0
        self.rxq = []
        self.rx_job = None
        self.log("connecting to %s:%d" % (self.ip, self.port))
        self.net.connect(self.ip, self.port,
                         lambda c, self=self, gen=gen: self.on_connect(c, gen),
                         lambda e, self=self, gen=gen: self.on_conn_err(e, gen))

    def on_connect(self, conn, gen):
        if gen != self.gen or self.state != "connecting":
            conn.close()
            return
        self.conn = conn
        self.inited = 0
        self.last_rx = time.time()
        self.raw_send("\xee\xee\xee\xee")
        self.read()
        self.arm_ping()
        if self.auth_key:
            self.ready()
        else:
            self.state = "dh"
            DH(self).start()

    def on_conn_err(self, err, gen):
        if gen != self.gen:
            return
        self.log("connect failed: " + str(err))
        self.drop("connect failed: " + str(err))

    def ready(self):
        self.state = "ready"
        self.backoff = 1
        self.log("ready")
        q = self.queue
        self.queue = []
        # requests that were sent on the old connection are sent again
        old = self.pending.values()
        self.pending = {}
        old.sort(lambda a, b: cmp(a.msg_id, b.msg_id))
        for r in old:
            if r.content:
                self.send_req(r)
        for r in q:
            self.send_req(r)
        self.events.connected(self)

    def drop(self, why):
        """Connection lost: reconnect later; pending requests are kept."""
        if self.state == "closed":
            return
        c = self.conn
        self.conn = None
        if c is not None:
            c.close()
        was = self.state
        self.state = "idle"
        self.gen = self.gen + 1
        if was == "dh":
            self.set_key(None)
        self.events.disconnected(self, why)
        delay = self.backoff
        self.backoff = min(self.backoff * 2, 30)
        self.log("reconnect in %ds (%s)" % (delay, why))
        self.net.later(delay, self.start)

    def close(self):
        self.state = "closed"
        self.gen = self.gen + 1
        c = self.conn
        self.conn = None
        if c is not None:
            c.close()
        for r in self.pending.values() + self.queue:
            self.fail(r, RpcError(-1, "CLOSED"))
        self.pending = {}
        self.queue = []

    def raw_send(self, data):
        """Queues bytes; only one socket send is in flight at a time."""
        if self.conn is None:
            return
        self.outq.append(data)
        if not self.sending:
            self.pump()

    def pump(self):
        if self.conn is None or not self.outq:
            self.sending = 0
            return
        data = "".join(self.outq)
        self.outq = []
        self.sending = 1
        gen = self.gen
        self.conn.send(data, lambda self=self, gen=gen: self.sent_ok(gen),
                       lambda e, self=self, gen=gen: self.send_err(e, gen))

    def sent_ok(self, gen):
        if gen == self.gen:
            self.pump()

    def send_err(self, e, gen):
        if gen == self.gen:
            self.drop("send: " + str(e))

    def send_packet(self, payload):
        self.raw_send(struct.pack("<I", len(payload)) + payload)

    def read(self):
        if self.conn is None:
            return
        gen = self.gen
        self.conn.recv(lambda d, self=self, gen=gen: self.on_data(d, gen))

    def on_data(self, data, gen):
        if gen != self.gen:
            return
        if not data:
            self.drop("closed by server")
            return
        self.last_rx = time.time()
        self.inbuf.append(data)
        self.inlen = self.inlen + len(data)
        while self.inlen >= 4 and gen == self.gen:
            buf = "".join(self.inbuf)
            n = struct.unpack("<I", buf[:4])[0]
            if self.inlen < 4 + n:
                self.inbuf = [buf]
                break
            pkt = buf[4:4 + n]
            rest = buf[4 + n:]
            self.inbuf = [rest]
            self.inlen = len(rest)
            self.packet(pkt)
        if gen == self.gen:
            self.read()

    def packet(self, pkt):
        if len(pkt) == 4:
            code = struct.unpack("<i", pkt)[0]
            self.log("transport error %d" % code)
            if code == -404:
                # the server does not know our key: make a new one
                self.set_key(None)
                self.events.saved(self)
            self.drop("transport error %d" % code)
            return
        if pkt[:8] == "\x00" * 8:
            if self.dh is not None:
                self.dh.got(pkt)
            return
        self.rxq.append(pkt)
        if self.rx_job is None:
            self.next_rx()

    def next_rx(self):
        """Decrypts queued packets in order; big ones a slice at a time so the
        phone keeps reacting to keys meanwhile."""
        while self.rx_job is None and self.rxq:
            pkt = self.rxq.pop(0)
            try:
                job = self.start_decrypt(pkt)
                if len(pkt) <= 1600:
                    while not job[0].step(256):
                        pass
                    self.finish_decrypt(job)
                else:
                    self.rx_job = job
                    gen = self.gen
                    self.net.later(0, lambda self=self, gen=gen: self.rx_slice(gen))
            except:
                self.rx_job = None
                self.bad_packet()

    def rx_slice(self, gen):
        job = self.rx_job
        if gen != self.gen or job is None:
            return
        try:
            done = job[0].step(96)
        except:
            self.rx_job = None
            self.bad_packet()
            self.next_rx()
            return
        if not done:
            self.net.later(0, lambda self=self, gen=gen: self.rx_slice(gen))
            return
        self.rx_job = None
        try:
            self.finish_decrypt(job)
        except:
            self.bad_packet()
        if gen == self.gen:
            self.next_rx()

    def bad_packet(self):
        self.log("bad packet: " + err_text())
        try:
            import traceback
            self.log("".join(traceback.format_exception(
                sys.exc_info()[0], sys.exc_info()[1], sys.exc_info()[2])))
        except:
            pass

    dh = None

    # ---------------------------------------------------------- keepalive

    def arm_ping(self):
        if self.ping_armed:
            return
        self.ping_armed = 1
        self.net.later(45, self.ping_tick)

    def ping_tick(self):
        self.ping_armed = 0
        if self.state == "closed":
            return
        if self.state == "ready":
            if time.time() - self.last_rx > 120:
                self.drop("no answer for 2 minutes")
            else:
                body = (pack_uint(self.schema.get("ping_delay_disconnect")[0]) +
                        pack_long(tgcrypto.random_long()) + pack_int(75))
                self.send_req(Request("ping", body, "Pong", None, None, 0))
        self.arm_ping()

    # ---------------------------------------------------------- requests

    def invoke(self, func, on_ok, on_err):
        """func: {"_": "messages.getDialogs", ...}; on_ok(result), on_err(RpcError)."""
        try:
            body = self.w.obj(func)
        except:
            self.net.later(0, lambda on_err=on_err, m=err_text(): on_err(RpcError(-2, m)))
            return
        name = func["_"]
        r = Request(name, body, self.schema.result_type(name), on_ok, on_err)
        if self.state == "ready":
            self.send_req(r)
        else:
            self.queue.append(r)
            if self.state == "idle":
                self.start()

    def send_req(self, r):
        body = r.body
        if r.content and r.name != "ping" and not self.inited and self.init_query:
            body = self.init_query(body)
            self.inited = 1
        msgs = []
        if self.acks:
            ack = (pack_uint(ID_MSGS_ACK) + pack_uint(tl.ID_VECTOR) + pack_int(len(self.acks)))
            for a in self.acks:
                ack = ack + pack_msg_id(a)
            self.acks = []
            msgs.append((self.next_msg_id(), self.next_seq(0), ack))
        r.msg_id = self.next_msg_id()
        msgs.append((r.msg_id, self.next_seq(r.content), body))
        self.pending[r.msg_id] = r
        r.sent = time.time()
        if len(msgs) == 1:
            mid, seq, data = msgs[0]
        else:
            parts = [pack_uint(ID_CONTAINER), pack_int(len(msgs))]
            for m in msgs:
                parts.append(pack_msg_id(m[0]) + pack_int(m[1]) + pack_int(len(m[2])) + m[2])
            data = "".join(parts)
            mid = self.next_msg_id()
            seq = self.next_seq(0)
        self.send_encrypted(mid, seq, data)

    def flush_acks(self):
        if not self.acks or self.state != "ready":
            return
        ack = (pack_uint(ID_MSGS_ACK) + pack_uint(tl.ID_VECTOR) + pack_int(len(self.acks)))
        for a in self.acks:
            ack = ack + pack_msg_id(a)
        self.acks = []
        self.send_encrypted(self.next_msg_id(), self.next_seq(0), ack)

    def send_encrypted(self, msg_id, seq, body):
        inner = (self.salt + self.session_id + pack_msg_id(msg_id) + pack_int(seq) +
                 pack_int(len(body)) + body)
        pad = 16 - len(inner) % 16
        if pad < 12:
            pad = pad + 16
        inner = inner + random_bytes(pad)
        k = self.auth_key
        msg_key = sha256(k[88:120] + inner)[8:24]
        a = sha256(msg_key + k[0:36])
        b = sha256(k[40:76] + msg_key)
        key = a[0:8] + b[8:24] + a[24:32]
        iv = b[0:8] + a[8:24] + b[24:32]
        self.send_packet(self.auth_key_id + msg_key + ige_encrypt(inner, key, iv))

    def resend(self, msg_id):
        r = self.pending.get(msg_id)
        if r is None:
            return
        del self.pending[msg_id]
        if r.name == "ping":
            return
        self.send_req(r)

    def fail(self, r, err):
        if r.on_err is not None:
            try:
                r.on_err(err)
            except:
                self.log("error callback: " + err_text())

    # ---------------------------------------------------------- receiving

    def start_decrypt(self, pkt):
        if pkt[:8] != self.auth_key_id:
            raise TLError("wrong auth_key_id")
        t0 = time.clock()
        msg_key = pkt[8:24]
        k = self.auth_key
        a = sha256(msg_key + k[8:44])
        b = sha256(k[48:84] + msg_key)
        key = a[0:8] + b[8:24] + a[24:32]
        iv = b[0:8] + a[8:24] + b[24:32]
        return (tgcrypto.IgeJob(pkt[24:], key, iv, 1), msg_key, t0, len(pkt))

    def finish_decrypt(self, job):
        ige, msg_key, t0, size = job
        plain = ige.result()
        if self.verify and sha256(self.auth_key[96:128] + plain)[8:24] != msg_key:
            raise TLError("msg_key mismatch")
        if plain[8:16] != self.session_id:
            raise TLError("other session")
        t1 = time.clock()
        r = Reader(self.schema, plain, 16)
        msg_id = r.long()
        seqno = r.int()
        n = r.int()
        if n > len(plain) - 32 or n < 0:
            raise TLError("bad length")
        self.handle(msg_id, seqno, plain[32:32 + n])
        t2 = time.clock()
        if t2 - t0 > 0.5:
            self.log("slow packet %d bytes: decrypt %.2fs, handle %.2fs" %
                     (size, t1 - t0, t2 - t1))

    def decrypt_packet(self, pkt):
        job = self.start_decrypt(pkt)
        while not job[0].step(256):
            pass
        self.finish_decrypt(job)

    def handle(self, msg_id, seqno, body):
        if seqno % 2 == 1:
            self.acks.append(msg_id)
            if len(self.acks) == 1:
                self.net.later(3, self.flush_acks)
        r = Reader(self.schema, body)
        cid = r.uint()
        if cid == ID_CONTAINER:
            n = r.int()
            i = 0
            while i < n:
                mid = r.long()
                sq = r.int()
                ln = r.int()
                self.handle(mid, sq, r.raw(ln))
                i = i + 1
            return
        if cid == tl.ID_GZIP:
            self.handle(msg_id, seqno - seqno % 2, tl.gunzip(r.bytes()))
            return
        if cid == ID_RPC_RESULT:
            req_id = r.long()
            self.rpc_result(req_id, r)
            return
        if cid == ID_BAD_SALT:
            bad = r.long()
            r.int()
            code = r.int()
            self.salt = r.raw(8)
            self.events.saved(self)
            self.log("new salt (code %d)" % code)
            self.resend(bad)
            return
        if cid == ID_BAD_MSG:
            bad = r.long()
            r.int()
            code = r.int()
            self.log("bad_msg_notification %d" % code)
            if code == 16 or code == 17:
                self.time_offset = (msg_id / P32) - time.time()
                self.last_msg_id = 0
                self.events.saved(self)
                self.resend(bad)
            elif code == 32 or code == 33:
                self.new_session()
                for mid in self.pending.keys():
                    self.resend(mid)
            else:
                req = self.pending.get(bad)
                if req is not None:
                    del self.pending[bad]
                    self.fail(req, RpcError(-code, "BAD_MSG"))
            return
        if cid == ID_NEW_SESSION:
            r.long()
            r.long()
            self.salt = r.raw(8)
            self.events.saved(self)
            self.events.update({"_": "newSession"})
            return
        if cid == ID_PONG:
            mid = r.long()
            if self.pending.has_key(mid):
                del self.pending[mid]
            return
        if cid in (ID_MSGS_ACK, ID_DETAILED, ID_NEW_DETAILED, ID_STATE_INFO, ID_FUTURE_SALTS):
            return
        # anything else is an update
        try:
            obj = r.obj(cid)
        except:
            self.log("cannot parse %08x: %s" % (cid, err_text()))
            return
        self.events.update(obj)

    def rpc_result(self, req_id, r):
        req = self.pending.get(req_id)
        if req is not None:
            del self.pending[req_id]
        start = r.pos
        cid = r.uint()
        if cid == tl.ID_GZIP:
            r = Reader(self.schema, tl.gunzip(r.bytes()))
            start = 0
            cid = r.uint()
        if cid == ID_RPC_ERROR:
            code = r.int()
            msg = r.bytes()
            if req is None:
                return
            self.log("%s -> error %d %s" % (req.name, code, msg))
            self.fail(req, RpcError(code, msg))
            return
        if req is None:
            return
        r.pos = start
        try:
            if req.rtype[:7] == "Vector<":
                res = r.value(req.rtype)
            else:
                res = r.obj()
        except:
            self.fail(req, RpcError(-3, "parse " + req.name + ": " + err_text()))
            return
        if req.on_ok is not None:
            req.on_ok(res)


class DH:
    """Creates a permanent auth key with the server (MTProto auth key exchange)."""

    def __init__(self, s):
        self.s = s
        s.dh = self
        self.step = None

    def fail(self, why):
        self.s.dh = None
        self.s.log("key exchange failed: " + why)
        self.s.drop("key exchange failed: " + why)

    def send(self, body, step):
        self.step = step
        msg = "\x00" * 8 + pack_msg_id(self.s.next_msg_id()) + pack_int(len(body)) + body
        self.s.send_packet(msg)

    def got(self, pkt):
        step = self.step
        self.step = None
        if step is None:
            return
        try:
            n = struct.unpack("<i", pkt[16:20])[0]
            r = Reader(self.s.schema, pkt[20:20 + n])
            obj = r.obj()
            step(obj)
        except:
            self.fail(err_text())

    def start(self):
        self.s.events.status(u"Creating secure key (1/3)...")
        self.nonce = random_bytes(16)
        self.send(self.s.w.obj({"_": "req_pq_multi", "nonce": self.nonce}), self.res_pq)

    def res_pq(self, res):
        if res["nonce"] != self.nonce:
            raise TLError("nonce mismatch")
        self.server_nonce = res["server_nonce"]
        key = None
        for fp, mod in RSA_KEYS:
            if fp in res["server_public_key_fingerprints"]:
                key = (fp, long(mod, 16))
                break
        if key is None:
            raise TLError("no known server RSA key")
        self.s.events.status(u"Creating secure key (2/3)...")
        pq = bytes_to_long(res["pq"])
        p, q = tgcrypto.factor_pq(pq)
        self.new_nonce = random_bytes(32)
        inner = self.s.w.obj({"_": "p_q_inner_data_dc", "pq": res["pq"],
                              "p": long_to_bytes(p), "q": long_to_bytes(q),
                              "nonce": self.nonce, "server_nonce": self.server_nonce,
                              "new_nonce": self.new_nonce, "dc": self.s.dc_id})
        enc = rsa_pad_encrypt(inner, key[1])
        self.send(self.s.w.obj({"_": "req_DH_params", "nonce": self.nonce,
                                "server_nonce": self.server_nonce,
                                "p": long_to_bytes(p), "q": long_to_bytes(q),
                                "public_key_fingerprint": key[0],
                                "encrypted_data": enc}), self.dh_params)

    def dh_params(self, res):
        if res["_"] != "server_DH_params_ok":
            raise TLError(res["_"])
        if res["nonce"] != self.nonce or res["server_nonce"] != self.server_nonce:
            raise TLError("nonce mismatch")
        nn = self.new_nonce
        sn = self.server_nonce
        h1 = sha1(nn + sn)
        h2 = sha1(sn + nn)
        self.tmp_key = h1 + h2[:12]
        self.tmp_iv = h2[12:20] + sha1(nn + nn) + nn[:4]
        ans = ige_decrypt(res["encrypted_answer"], self.tmp_key, self.tmp_iv)
        r = Reader(self.s.schema, ans, 20)
        inner = r.obj()
        if sha1(ans[20:r.pos]) != ans[:20]:
            raise TLError("DH answer hash mismatch")
        if inner["nonce"] != self.nonce or inner["server_nonce"] != sn:
            raise TLError("nonce mismatch")
        p = bytes_to_long(inner["dh_prime"])
        if p != long(DH_PRIME, 16):
            raise TLError("unexpected DH prime")
        g = inner["g"]
        g_a = bytes_to_long(inner["g_a"])
        low = pow(2 + 0 * p, 2048 - 64)
        if not (low < g_a < p - low):
            raise TLError("g_a out of range")
        self.s.time_offset = inner["server_time"] - time.time()
        self.s.last_msg_id = 0
        self.s.events.status(u"Creating secure key (3/3)...")
        b = bytes_to_long(random_bytes(256))
        g_b = pow(g, b, p)
        if not (low < g_b < p - low):
            raise TLError("g_b out of range")
        self.auth_key = long_to_bytes(pow(g_a, b, p), 256)
        data = self.s.w.obj({"_": "client_DH_inner_data", "nonce": self.nonce,
                             "server_nonce": sn, "retry_id": 0,
                             "g_b": long_to_bytes(g_b)})
        data = sha1(data) + data
        data = data + random_bytes((16 - len(data) % 16) % 16)
        enc = ige_encrypt(data, self.tmp_key, self.tmp_iv)
        self.send(self.s.w.obj({"_": "set_client_DH_params", "nonce": self.nonce,
                                "server_nonce": sn, "encrypted_data": enc}), self.dh_done)

    def dh_done(self, res):
        if res["_"] != "dh_gen_ok":
            raise TLError(res["_"])
        aux = sha1(self.auth_key)[:8]
        if sha1(self.new_nonce + "\x01" + aux)[4:20] != res["new_nonce_hash1"]:
            raise TLError("new_nonce_hash1 mismatch")
        s = self.s
        s.dh = None
        s.set_key(self.auth_key)
        s.salt = xor_bytes(self.new_nonce[:8], self.server_nonce[:8])
        s.log("auth key created")
        s.events.saved(s)
        s.ready()


def rsa_pad_encrypt(data, n):
    """RSA for req_DH_params: SHA1(data) + data + random padding to 255 bytes.
    (This is the scheme Telethon uses and Telegram accepts; the newer RSA_PAD
    variant was rejected with -404 in a live test on 2026-11-21.)"""
    if len(data) > 235:
        raise TLError("inner data too long")
    x = sha1(data) + data + random_bytes(235 - len(data))
    return long_to_bytes(pow(bytes_to_long(x), 65537, n), 256)
