# CallAudio: talks to tgcallaudio.exe (VoIP audio + Opus) over localhost UDP.
# The helper sends one Opus packet per datagram to 127.0.0.1:47001 and plays
# every datagram received on 127.0.0.1:47002; a lone "Q" ends it.
# Python 2.2 compatible. e32socket rule: sockets are never close()d while the
# app runs (see retrotele.py PhoneConn); stop() just forgets the socket.

import sys
import types
import socket
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

    def start(self, on_packet, seconds=60):
        self.stop()
        self.on_packet = on_packet
        self.rx = 0
        self.tx = 0
        self.errors = 0
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.bind((HOST, PORT_FROM_HELPER))
        self.sock = s
        self.running = 1
        self._arm()
        e32.start_exe(u"tgcallaudio.exe", u"%d" % seconds)

    def _arm(self):
        s = self.sock
        if s is None or not self.running:
            return
        try:
            _raw(s).recvfrom(4096, 0, self._cb)
        except:
            self.errors = self.errors + 1
            self.last_error = u"recvfrom: " + unicode(str(sys.exc_info()[1]), "latin-1")
            self.running = 0

    def _cb(self, res):
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
        if data:
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
