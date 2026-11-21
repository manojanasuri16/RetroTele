# Two-step verification (SRP) password hash for RetroTele.
# Telegram's x = SH(PBKDF2-HMAC-SHA512(SH(SH(pw, salt1), salt2), salt1, 100000), salt2)
# where SH(d, s) = SHA256(s + d + s). PBKDF2 with 100000 rounds of pure-Python
# SHA-512 is slow on a phone, so PasswordHash runs in small slices
# (step()) and the UI calls it from a timer, showing progress.
# Python 2.2 compatible (decimal masks, no <<).

import struct
from tgcrypto import sha256

M64 = 18446744073709551615
P64 = 18446744073709551616

_K = [
    4794697086780616226, 8158064640168781261, 13096744586834688815, 16840607885511220156,
    4131703408338449720, 6480981068601479193, 10538285296894168987, 12329834152419229976,
    15566598209576043074, 1334009975649890238, 2608012711638119052, 6128411473006802146,
    8268148722764581231, 9286055187155687089, 11230858885718282805, 13951009754708518548,
    16472876342353939154, 17275323862435702243, 1135362057144423861, 2597628984639134821,
    3308224258029322869, 5365058923640841347, 6679025012923562964, 8573033837759648693,
    10970295158949994411, 12119686244451234320, 12683024718118986047, 13788192230050041572,
    14330467153632333762, 15395433587784984357, 489312712824947311, 1452737877330783856,
    2861767655752347644, 3322285676063803686, 5560940570517711597, 5996557281743188959,
    7280758554555802590, 8532644243296465576, 9350256976987008742, 10552545826968843579,
    11727347734174303076, 12113106623233404929, 14000437183269869457, 14369950271660146224,
    15101387698204529176, 15463397548674623760, 17586052441742319658, 1182934255886127544,
    1847814050463011016, 2177327727835720531, 2830643537854262169, 3796741975233480872,
    4115178125766777443, 5681478168544905931, 6601373596472566643, 7507060721942968483,
    8399075790359081724, 8693463985226723168, 9568029438360202098, 10144078919501101548,
    10430055236837252648, 11840083180663258601, 13761210420658862357, 14299343276471374635,
    14566680578165727644, 15097957966210449927, 16922976911328602910, 17689382322260857208,
    500013540394364858, 748580250866718886, 1242879168328830382, 1977374033974150939,
    2944078676154940804, 3659926193048069267, 4368137639120453308, 4836135668995329356,
    5532061633213252278, 6448918945643986474, 6902733635092675308, 7801388544844847127]

_H = [7640891576956012808, 13503953896175478587, 4354685564936845355, 11912009170470909681,
      5840696475078001361, 11170449401992604703, 2270897969802886507, 6620516959819538809]


def _rotr(x, n):
    return (x >> n) | ((x * _P[64 - n]) & M64)


_P = []
_i = 0
while _i <= 64:
    _P.append(pow(2 + 0 * M64, _i))
    _i = _i + 1
del _i


def _compress(h, block):
    w = list(struct.unpack(">32I", block))
    ws = []
    i = 0
    while i < 32:
        ws.append(w[i] * 4294967296 + w[i + 1])
        i = i + 2
    w = ws
    rotr = _rotr
    j = 16
    while j < 80:
        x = w[j - 15]
        y = w[j - 2]
        s0 = rotr(x, 1) ^ rotr(x, 8) ^ (x >> 7)
        s1 = rotr(y, 19) ^ rotr(y, 61) ^ (y >> 6)
        w.append((w[j - 16] + s0 + w[j - 7] + s1) & M64)
        j = j + 1
    a, b, c, d, e, f, g, hh = h
    K = _K
    j = 0
    while j < 80:
        S1 = rotr(e, 14) ^ rotr(e, 18) ^ rotr(e, 41)
        ch = (e & f) ^ ((M64 ^ e) & g)
        t1 = (hh + S1 + ch + K[j] + w[j]) & M64
        S0 = rotr(a, 28) ^ rotr(a, 34) ^ rotr(a, 39)
        maj = (a & b) ^ (a & c) ^ (b & c)
        hh = g
        g = f
        f = e
        e = (d + t1) & M64
        d = c
        c = b
        b = a
        a = (t1 + S0 + maj) & M64
        j = j + 1
    return [(h[0] + a) & M64, (h[1] + b) & M64, (h[2] + c) & M64, (h[3] + d) & M64,
            (h[4] + e) & M64, (h[5] + f) & M64, (h[6] + g) & M64, (h[7] + hh) & M64]


def _pack(h):
    out = []
    for v in h:
        out.append(struct.pack(">II", (v / 4294967296) & 4294967295, v & 4294967295))
    return "".join(out)


def _pad(total_len):
    bits = total_len * 8
    pad = "\x80" + "\x00" * ((111 - total_len) % 128)
    return pad + struct.pack(">IIII", 0, 0, (bits / 4294967296) & 4294967295,
                             bits & 4294967295)


def sha512(data):
    h = list(_H)
    data = data + _pad(len(data))
    i = 0
    while i < len(data):
        h = _compress(h, data[i:i + 128])
        i = i + 128
    return _pack(h)


# a 64-byte message after a 128-byte key block: fixed padding for the 2nd block
_TAIL64 = _pad(192)


class PasswordHash:
    """x for SRP, computed in slices: while not done: step(200)."""

    def __init__(self, password, salt1, salt2, iterations=100000):
        if type(password) is type(u""):
            password = password.encode("utf-8")
        self.salt2 = salt2
        sh = lambda d, s: sha256(s + d + s)
        ph1 = sh(sh(password, salt1), salt2)
        self.native = None
        import tgcrypto
        if tgcrypto.NATIVE:
            # compiled PBKDF2: seconds instead of an hour
            self.native = tgcrypto.tgnative.pbkdf2_sha512(ph1, salt1, iterations)
            self.total = iterations
            self.done_n = 0
            self.result = None
            return
        key = ph1
        if len(key) > 128:
            key = sha512(key)
        key = key + "\x00" * (128 - len(key))
        ipad = []
        opad = []
        for ch in key:
            ipad.append(chr(ord(ch) ^ 54))
            opad.append(chr(ord(ch) ^ 92))
        self.istate = _compress(list(_H), "".join(ipad))
        self.ostate = _compress(list(_H), "".join(opad))
        self.total = iterations
        self.done_n = 0
        self.result = None
        # PBKDF2 block 1: U1 = HMAC(P, salt1 || INT(1))
        msg = salt1 + "\x00\x00\x00\x01"
        inner = self._finish(self.istate, msg, 128)
        u = self._finish(self.ostate, inner, 128)
        self.u = u
        self.t = self._words(u)
        self.done_n = 1

    def _finish(self, state, msg, prefix_len):
        data = msg + _pad(prefix_len + len(msg))
        h = list(state)
        i = 0
        while i < len(data):
            h = _compress(h, data[i:i + 128])
            i = i + 128
        return _pack(h)

    def _words(self, s):
        w = struct.unpack(">16I", s)
        out = []
        i = 0
        while i < 16:
            out.append(w[i] * 4294967296 + w[i + 1])
            i = i + 2
        return out

    def step(self, n):
        """Runs up to n PBKDF2 iterations; returns 1 when finished."""
        if self.result is not None:
            return 1
        if self.native is not None:
            hashed = self.native
            s = self.salt2
            self.done_n = self.total
            self.result = sha256(s + hashed + s)
            return 1
        u = self.u
        t = self.t
        ist = self.istate
        ost = self.ostate
        tail = _TAIL64
        comp = _compress
        k = 0
        while k < n and self.done_n < self.total:
            inner = _pack(comp(list(ist), u + tail))
            uh = comp(list(ost), inner + tail)
            u = _pack(uh)
            t = [t[0] ^ uh[0], t[1] ^ uh[1], t[2] ^ uh[2], t[3] ^ uh[3],
                 t[4] ^ uh[4], t[5] ^ uh[5], t[6] ^ uh[6], t[7] ^ uh[7]]
            self.done_n = self.done_n + 1
            k = k + 1
        self.u = u
        self.t = t
        if self.done_n >= self.total:
            hashed = _pack(t)
            s = self.salt2
            self.result = sha256(s + hashed + s)
            return 1
        return 0
