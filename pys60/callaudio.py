# CallAudio: talks to tgcallaudio.exe (VoIP audio + Opus) over localhost UDP.
# The helper sends one Opus packet per datagram to 127.0.0.1:47001 and plays
# every datagram received on 127.0.0.1:47002; a lone "Q" ends it.
# Python 2.2 compatible. e32socket rule: sockets are never close()d while the
# app runs (see retrotele.py PhoneConn); stop() just forgets the socket.

import sys
import types
import socket
import binascii
import e32
import tgcrypto

HOST = "127.0.0.1"
PORT_FROM_HELPER = 47001
PORT_TO_HELPER = 47002


def _raw(sock):
    return getattr(sock, "_sock", sock)


def _is_err(res):
    return (type(res) is types.TupleType and len(res) == 2 and
            type(res[0]) in (types.ClassType, types.TypeType))


_SHARED = [None]        # the one UDP socket on 127.0.0.1:47001
_CURRENT = [None]       # the CallAudio receiving the helper's datagrams
_PENDING = [0]          # a recvfrom is outstanding


def _dispatch(res):
    _PENDING[0] = 0
    ca = _CURRENT[0]
    if ca is None or not ca.running:
        return
    data = None
    if _is_err(res):
        ca.errors = ca.errors + 1
    elif type(res) is types.TupleType and len(res) == 2:
        data = res[0]
    elif type(res) is types.StringType:
        data = res
    ca._arm()
    if data:
        ca._handle(data)


class CallAudio:
    def __init__(self):
        self.sock = None
        self.on_packet = None
        self.running = 0
        self.rx = 0
        self.tx = 0
        self.errors = 0
        self.last_error = u""
        self.relay = 0
        self.on_state = None
        self.state = ""
        self.cfg_path = ""
        self.keep = None
        self.muted = 0
        self.route = 1
        self.want_mute = 0
        self.want_route = 1
        self.on_info = None
        self.sent_init = 0
        self.armed = 0
        self.v277 = 0
        self.on_signal = None
        self.helper_ready = 0
        self.sig_queue = []

    def relay_config(self, key, is_outgoing, connections):
        """Text for the helper: out=, key= (hex) and up to 4 ep=ip,port,tag
        lines (UDP phoneConnection entries only). Returns (text, count)."""
        out = "0"
        if is_outgoing:
            out = "1"
        lines = ["out=" + out, "key=" + binascii.hexlify(key)]
        n = 0
        for c in connections:
            if n >= 4:
                break
            if c.get("_") != "phoneConnection" or c.get("tcp"):
                continue
            ip = c.get("ip", "")
            tag = c.get("peer_tag", "")
            port = c.get("port", 0)
            if not ip or len(tag) != 16 or port <= 0 or port > 65535:
                continue
            lines.append("ep=%s,%d,%s" % (ip, port, binascii.hexlify(tag)))
            n = n + 1
        return "\n".join(lines) + "\n", n

    def write_cfg(self, text):
        for p in ["C:\\Data\\retrotele_call.cfg", "E:\\retrotele_call.cfg"]:
            try:
                f = open(p, "wb")
                try:
                    f.write(text)
                finally:
                    f.close()
                return p
            except:
                self.last_error = u"cfg: " + unicode(str(sys.exc_info()[1]), "latin-1")
        return ""

    def start_relay(self, key, is_outgoing, connections, on_state, iap=0):
        """Start tgcallaudio.exe in relay mode: media goes to the Telegram
        relays directly. on_state(name): connecting connected reconnecting
        failed ended."""
        self.stop()
        text, n = self.relay_config(key, is_outgoing, connections)
        if iap:
            text = text + "iap=%d\n" % iap
        self.on_state = on_state
        self.relay = 1
        self.state = ""
        self.sent_init = 0
        self.want_mute = 0
        self.want_route = 1
        self.rx = 0
        self.tx = 0
        self.errors = 0
        if n == 0:
            self.last_error = u"no UDP relay"
            self._set_state("failed")
            return 0
        self.cfg_path = self.write_cfg(text)
        if not self.cfg_path:
            self._set_state("failed")
            return 0
        try:
            self.sock = self._open()
        except:
            self.last_error = u"udp socket: " + unicode(str(sys.exc_info()[1]), "latin-1")
            self._set_state("failed")
            return 0
        self.running = 1
        self._arm()
        try:
            e32.start_exe(u"tgcallaudio.exe", u"relay 7200")
        except:
            self.last_error = u"start_exe: " + unicode(str(sys.exc_info()[1]), "latin-1")
            self._set_state("failed")
            return 0
        return 1

    def relay_config277(self, key, is_outgoing, connections, rnd):
        """Text for the v277 helper: ver=277, out=, key=, rnd= and one
        c=<id>,<ip>,<port>,<tag hex or empty>,<tcp>,<webrtc> line per
        phoneConnection / phoneConnectionWebrtc (up to 8). Returns (text, count)."""
        out = "0"
        if is_outgoing:
            out = "1"
        lines = ["ver=277", "out=" + out, "key=" + binascii.hexlify(key),
                 "rnd=" + binascii.hexlify(rnd)]
        n = 0
        for c in connections:
            if n >= 8:
                break
            kind = c.get("_")
            if kind != "phoneConnection" and kind != "phoneConnectionWebrtc":
                continue
            ip = c.get("ip", "")
            port = c.get("port", 0)
            if not ip or port <= 0 or port > 65535:
                continue
            tag = c.get("peer_tag", "")
            if len(tag) == 16:
                tag = binascii.hexlify(tag)
            else:
                tag = ""
            tcp = 0
            if c.get("tcp"):
                tcp = 1
            web = 0
            if kind == "phoneConnectionWebrtc":
                web = 1
            lines.append("c=%d,%s,%d,%s,%d,%d" % (c.get("id", 0), ip, port, tag, tcp, web))
            n = n + 1
        return "\n".join(lines) + "\n", n

    def start_relay277(self, key, is_outgoing, connections, on_state, iap=0, on_signal=None):
        """Start tgcallaudio.exe in v277 mode (calls with official apps).
        on_state(name) as start_relay; on_signal(data) gets every signalling
        blob the helper wants sent with phone.sendSignalingData."""
        self.stop()
        text, n = self.relay_config277(key, is_outgoing, connections, tgcrypto.random_bytes(56))
        if iap:
            text = text + "iap=%d\n" % iap
        self.on_state = on_state
        self.on_signal = on_signal
        self.relay = 1
        self.v277 = 1
        self.helper_ready = 0
        self.sig_queue = []
        self.state = ""
        self.sent_init = 0
        self.want_mute = 0
        self.want_route = 1
        self.rx = 0
        self.tx = 0
        self.errors = 0
        if n == 0:
            self.last_error = u"no connection"
            self._set_state("failed")
            return 0
        self.cfg_path = self.write_cfg(text)
        if not self.cfg_path:
            self._set_state("failed")
            return 0
        try:
            self.sock = self._open()
        except:
            self.last_error = u"udp socket: " + unicode(str(sys.exc_info()[1]), "latin-1")
            self._set_state("failed")
            return 0
        self.running = 1
        self._arm()
        try:
            e32.start_exe(u"tgcallaudio.exe", u"relay 7200")
        except:
            self.last_error = u"start_exe: " + unicode(str(sys.exc_info()[1]), "latin-1")
            self._set_state("failed")
            return 0
        return 1

    def send_signaling(self, data):
        """A signalling blob from the peer (updatePhoneCallSignalingData):
        held back until the helper says 'S ready', then sent in order."""
        if not self.v277 or not self.running:
            return
        if not self.helper_ready:
            if len(self.sig_queue) < 64:
                self.sig_queue.append(data)
            return
        self._sendto("G" + data)

    def _helper_ready(self):
        if self.helper_ready:
            return
        self.helper_ready = 1
        q = self.sig_queue
        self.sig_queue = []
        for d in q:
            self._sendto("G" + d)
        self._send_controls()

    def _set_state(self, name):
        if name == self.state:
            return
        self.state = name
        if name == "connected":
            self._send_controls()
        cb = self.on_state
        if cb is not None:
            try:
                cb(name)
            except:
                self.errors = self.errors + 1
                self.last_error = u"on_state: " + unicode(str(sys.exc_info()[1]), "latin-1")

    def start(self, on_packet, seconds=60):
        self.stop()
        self.relay = 0
        self.on_packet = on_packet
        self.rx = 0
        self.tx = 0
        self.errors = 0
        self.sock = self._open()
        self.running = 1
        self._arm()
        e32.start_exe(u"tgcallaudio.exe", u"%d" % seconds)

    def _open(self):
        # sockets are never closed (e32socket): ONE socket for the whole app
        # run, shared by every CallAudio (a second bind on the port is
        # refused with "Permission denied")
        s = _SHARED[0]
        if s is None:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.bind((HOST, PORT_FROM_HELPER))
            _SHARED[0] = s
        return s

    def _arm(self):
        """Make sure the shared receive loop is running (one pending
        recvfrom for the whole app, forwarding to the current instance)."""
        _CURRENT[0] = self
        if self.sock is None or not self.running or _PENDING[0]:
            return
        _PENDING[0] = 1
        try:
            _raw(self.sock).recvfrom(2048, 0, _dispatch)
        except:
            _PENDING[0] = 0
            self.errors = self.errors + 1
            self.last_error = u"recvfrom: " + unicode(str(sys.exc_info()[1]), "latin-1")
            self.running = 0

    def _handle(self, data):
        """A datagram from the helper."""
        if not self.running:
            return
        if self.relay:
            self.rx = self.rx + 1
            if data[:1] == "G" and self.v277:
                cb = self.on_signal
                if cb is not None and len(data) > 1:
                    try:
                        cb(data[1:])
                    except:
                        self.errors = self.errors + 1
                        self.last_error = u"on_signal: " + unicode(str(sys.exc_info()[1]), "latin-1")
            elif data[:2] == "S ":
                if data[2:].strip() == "ready":
                    self._helper_ready()
                else:
                    self._set_state(data[2:].strip())
            elif data[:2] == "M ":
                self.muted = (data[2:].strip() == "1")
                self._info()
            elif data[:2] == "D ":
                try:
                    self.route = int(data[2:].strip())
                except:
                    self.route = 2
                self._info()
        else:
            self.rx = self.rx + 1
            try:
                self.on_packet(data)
            except:
                self.errors = self.errors + 1
                self.last_error = u"on_packet: " + unicode(str(sys.exc_info()[1]), "latin-1")

    def _info(self):
        cb = self.on_info
        if cb is not None:
            try:
                cb()
            except:
                self.errors = self.errors + 1
                self.last_error = u"on_info: " + unicode(str(sys.exc_info()[1]), "latin-1")

    def _send_controls(self):
        # the helper may have started after the wishes were set: re-send
        self._sendto("R%d" % self.want_route)
        self._sendto("M%d" % self.want_mute)

    def set_mute(self, flag):
        if flag:
            self.want_mute = 1
        else:
            self.want_mute = 0
        self._sendto("M%d" % self.want_mute)

    def set_route(self, n):
        if n < 0 or n > 2:
            return
        self.want_route = n
        self._sendto("R%d" % n)

    def _sendto(self, data):
        s = self.sock
        if s is None:
            return 0
        try:
            _raw(s).sendto(data, 0, (HOST, PORT_TO_HELPER))
            return 1
        except:
            self.errors = self.errors + 1
            self.last_error = u"sendto: " + unicode(str(sys.exc_info()[1]), "latin-1")
            return 0

    def send(self, data):
        if self._sendto(data):
            self.tx = self.tx + 1

    def stop(self):
        if self.sock is not None:
            self._sendto("Q")
        self.sock = None
        self.running = 0
        self.on_packet = None
        self.on_state = None
        self.on_info = None
        self.relay = 0
        self.v277 = 0
        self.on_signal = None
        self.helper_ready = 0
        self.sig_queue = []
        self.state = ""
        self.muted = 0
        self.route = 1
