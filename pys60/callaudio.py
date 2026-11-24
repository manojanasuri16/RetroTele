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
        self.want_agc = 1         # mic boost: 0 off, 1 normal (AGC), 2 high
        self.want_bt = 1          # Bluetooth headset combination (tgcallaudio KBtCombos), 0..7
        self.want_btexp = 0       # experimental Bluetooth routing in the helper (off by default)
        self.route_failed = -1    # the helper could not switch to this route (it kept the old one)
        self.bt_links = -1        # connected Bluetooth links the helper sees (-1 unknown)
        self.tel_out = -1         # telephony audio output reported by tgbtroute.exe (5 = Bluetooth)
        self.route_user = 0       # the user picked a sound output in this call (no automatic switch)
        self.on_info = None
        self.sent_init = 0
        self.armed = 0
        self.v277 = 0
        self.on_signal = None
        self.helper_ready = 0
        self.sig_queue = []
        self.want_video = 0       # 1: tgvideo.exe feeds us encoder units, announce video to the peer
        self.video_active = 0     # helper says our video is announced (RemoteMediaState Active)
        self.peer_video = -1      # peer's RemoteMediaState video: 0 inactive 1 paused 2 active
        self.peer_asked = 0       # times the peer sent RequestVideo
        self.want_rx = 0          # 1: answer the peer's video offer and depacketize its picture ("W1")
        self.want_rxfwd = 0       # 1: tgvideo.exe is up and takes the peer's access units ("H1")
        self.loss = 0             # peer's RTCP loss fraction for our video (0..255), from "L n"

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
            elif data[:2] == "P ":
                try:
                    self.peer_video = int(data[2:].strip())
                except:
                    pass
                self._info()
            elif data[:2] == "X ":
                try:
                    self.peer_asked = int(data[2:].strip())
                except:
                    pass
                self._info()
            elif data[:2] == "L ":
                try:
                    self.loss = int(data[2:].strip())
                except:
                    pass
            elif data[:2] == "A ":
                self.video_active = (data[2:].strip() == "1")
                self._info()
            elif data[:2] == "T ":
                try:
                    self.tel_out = int(data[2:].strip())
                except:
                    self.tel_out = -1
                self._info()
            elif data[:2] == "B ":
                try:
                    self.bt_links = int(data[2:].strip())
                except:
                    self.bt_links = -1
                self._info()
            elif data[:2] == "O ":
                try:
                    self.route_failed = int(data[2:].strip())
                except:
                    self.route_failed = 2
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
        self._sendto("A%d" % self.want_agc)
        self._sendto("J%d" % self.want_btexp)
        self._sendto("X%d" % self.want_bt)
        if self.want_video:
            self._sendto("V1")
        if self.want_rx:
            self._sendto("W1")
        if self.want_rxfwd:
            self._sendto("H1")

    def set_rx(self, flag):
        """Receive the peer's video (2.7.7): the engine announces H264 support to the peer and
        depacketizes what it sends."""
        self.want_rx = flag and 1 or 0
        self._sendto("W%d" % self.want_rx)

    def set_rxfwd(self, flag):
        """The display helper (tgvideo.exe) is ready: forward the peer's access units to it."""
        self.want_rxfwd = flag and 1 or 0
        self._sendto("H%d" % self.want_rxfwd)

    def set_video(self, flag):
        """Video send on/off for a 2.7.7 call: the helper announces it to the peer and
        packetizes the units tgvideo.exe sends it."""
        if flag:
            self.want_video = 1
        else:
            self.want_video = 0
            self.video_active = 0
            self.loss = 0
        self._sendto("V%d" % self.want_video)

    def set_mute(self, flag):
        if flag:
            self.want_mute = 1
        else:
            self.want_mute = 0
        self._sendto("M%d" % self.want_mute)

    def set_agc(self, mode):
        """Mic boost in the helper: 0 off, 1 normal (AGC up to +18 dB), 2 high (+24 dB)."""
        if mode < 0 or mode > 2:
            mode = 1
        self.want_agc = mode
        self._sendto("A%d" % mode)

    def set_btexp(self, flag):
        """Experimental Bluetooth routing in the helper (J1); off (J0) is the 0.16.0 default."""
        self.want_btexp = flag and 1 or 0
        self._sendto("J%d" % self.want_btexp)

    def set_btmode(self, n):
        """How the helper switches the call audio to a Bluetooth headset (0..7, see the test)."""
        if n < 0 or n > 7:
            n = 1
        self.want_bt = n
        self._sendto("X%d" % n)

    def bt_answer(self, text):
        """Logs a Bluetooth test answer in the helper's log together with the audio levels."""
        self._sendto("Y" + text[:60])

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
        self.want_video = 0
        self.want_rx = 0
        self.want_rxfwd = 0
        self.video_active = 0
        self.peer_video = -1
        self.peer_asked = 0
