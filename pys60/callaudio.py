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

HOST = "127.0.0.1"
PORT_FROM_HELPER = 47001
PORT_TO_HELPER = 47002


def _raw(sock):
    return getattr(sock, "_sock", sock)


def _is_err(res):
    return (type(res) is types.TupleType and len(res) == 2 and
            type(res[0]) in (types.ClassType, types.TypeType))


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
        self.armed = 0

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

    def start_relay(self, key, is_outgoing, connections, on_state):
        """Start tgcallaudio.exe in relay mode: media goes to the Telegram
        relays directly. on_state(name): connecting connected reconnecting
        failed ended."""
        self.stop()
        text, n = self.relay_config(key, is_outgoing, connections)
        self.on_state = on_state
        self.relay = 1
        self.state = ""
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
        self.sock = self._open()
        self.running = 1
        self._arm()
        try:
            e32.start_exe(u"tgcallaudio.exe", u"relay 7200")
        except:
            self.last_error = u"start_exe: " + unicode(str(sys.exc_info()[1]), "latin-1")
            self._set_state("failed")
            return 0
        return 1

    def _set_state(self, name):
        if name == self.state:
            return
        self.state = name
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
        # sockets are never closed (e32socket): one socket serves every call
        if self.keep is None:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.bind((HOST, PORT_FROM_HELPER))
            self.keep = s
        return self.keep

    def _arm(self):
        s = self.sock
        if s is None or not self.running or self.armed:
            return
        self.armed = 1
        try:
            _raw(s).recvfrom(4096, 0, self._cb)
        except:
            self.errors = self.errors + 1
            self.armed = 0
            self.last_error = u"recvfrom: " + unicode(str(sys.exc_info()[1]), "latin-1")
            self.running = 0

    def _cb(self, res):
        self.armed = 0
        if not self.running:
            return
        data = None
        if _is_err(res):
            self.errors = self.errors + 1
        elif type(res) is types.TupleType and len(res) == 2:
            data = res[0]
        elif type(res) is types.StringType:
            data = res
        self._arm()
        if data and self.relay:
            self.rx = self.rx + 1
            if data[:2] == "S ":
                self._set_state(data[2:].strip())
        elif data:
            self.rx = self.rx + 1
            try:
                self.on_packet(data)
            except:
                self.errors = self.errors + 1
                self.last_error = u"on_packet: " + unicode(str(sys.exc_info()[1]), "latin-1")

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
        self.relay = 0
        self.state = ""
