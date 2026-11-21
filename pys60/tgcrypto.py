# Pure-Python crypto for RetroTele (PyS60 1.4.5 = Python 2.2; no sha/hashlib/AES).
# SHA-1, SHA-256, AES-256 in IGE mode, big-integer helpers and a random source.
#
# Python 2.2 integer rules, followed everywhere in this file:
#   * hex literals >= 0x80000000 are NEGATIVE ints on 2.2 -> only decimal for big masks
#   * int << n silently drops bits on 2.2 (no promotion to long) -> never use <<;
#     multiply by a power of two instead (multiplication promotes to long)
#   * values are kept in 0 .. 2**32-1 and masked with M32 after + and *
# The file also parses as Python 3 for the PC checker (tools/check_py22.py).

import struct
import binascii
import time

M32 = 4294967295          # 2**32 - 1 (a long on 32-bit Python 2.2)
P32 = 4294967296          # 2**32
_POW2 = []
_i = 0
while _i <= 32:
    _POW2.append(pow(2, _i) + 0 * M32)  # 0*M32 forces a long on 2.2 when needed
    _i = _i + 1
del _i


def _rotl(x, n):
    return ((x * _POW2[n]) & M32) | (x >> (32 - n))


def _rotr(x, n):
    return (x >> n) | ((x * _POW2[32 - n]) & M32)


def _md_pad(msglen):
    """Merkle-Damgard padding for a message of msglen bytes (64-bit big-endian length)."""
    bits = msglen * 8
    pad = "\x80" + "\x00" * ((55 - msglen) % 64)
    hi = (bits / P32) & M32
    lo = bits & M32
    return pad + struct.pack(">II", hi, lo)


# ---------------------------------------------------------------- SHA-1

def sha1(data):
    h0 = 1732584193
    h1 = 4023233417
    h2 = 2562383102
    h3 = 271733878
    h4 = 3285377520
    data = data + _md_pad(len(data))
    i = 0
    n = len(data)
    rotl = _rotl
    while i < n:
        w = list(struct.unpack(">16I", data[i:i + 64]))
        j = 16
        while j < 80:
            w.append(rotl(w[j - 3] ^ w[j - 8] ^ w[j - 14] ^ w[j - 16], 1))
            j = j + 1
        a = h0
        b = h1
        c = h2
        d = h3
        e = h4
        j = 0
        while j < 20:
            t = (rotl(a, 5) + ((b & c) | ((M32 ^ b) & d)) + e + 1518500249 + w[j]) & M32
            e = d
            d = c
            c = rotl(b, 30)
            b = a
            a = t
            j = j + 1
        while j < 40:
            t = (rotl(a, 5) + (b ^ c ^ d) + e + 1859775393 + w[j]) & M32
            e = d
            d = c
            c = rotl(b, 30)
            b = a
            a = t
            j = j + 1
        while j < 60:
            t = (rotl(a, 5) + ((b & c) | (b & d) | (c & d)) + e + 2400959708 + w[j]) & M32
            e = d
            d = c
            c = rotl(b, 30)
            b = a
            a = t
            j = j + 1
        while j < 80:
            t = (rotl(a, 5) + (b ^ c ^ d) + e + 3395469782 + w[j]) & M32
            e = d
            d = c
            c = rotl(b, 30)
            b = a
            a = t
            j = j + 1
        h0 = (h0 + a) & M32
        h1 = (h1 + b) & M32
        h2 = (h2 + c) & M32
        h3 = (h3 + d) & M32
        h4 = (h4 + e) & M32
        i = i + 64
    return struct.pack(">5I", h0, h1, h2, h3, h4)


# ---------------------------------------------------------------- SHA-256

_K256 = [
    1116352408, 1899447441, 3049323471, 3921009573, 961987163, 1508970993,
    2453635748, 2870763221, 3624381080, 310598401, 607225278, 1426881987,
    1925078388, 2162078206, 2614888103, 3248222580, 3835390401, 4022224774,
    264347078, 604807628, 770255983, 1249150122, 1555081692, 1996064986,
    2554220882, 2821834349, 2952996808, 3210313671, 3336571891, 3584528711,
    113926993, 338241895, 666307205, 773529912, 1294757372, 1396182291,
    1695183700, 1986661051, 2177026350, 2456956037, 2730485921, 2820302411,
    3259730800, 3345764771, 3516065817, 3600352804, 4094571909, 275423344,
    430227734, 506948616, 659060556, 883997877, 958139571, 1322822218,
    1537002063, 1747873779, 1955562222, 2024104815, 2227730452, 2361852424,
    2428436474, 2756734187, 3204031479, 3329325298]
_H256 = [1779033703, 3144134277, 1013904242, 2773480762, 1359893119,
         2600822924, 528734635, 1541459225]


def _sha256_blocks(h, data):
    rotr = _rotr
    K = _K256
    i = 0
    n = len(data)
    while i < n:
        w = list(struct.unpack(">16I", data[i:i + 64]))
        j = 16
        while j < 64:
            x = w[j - 15]
            y = w[j - 2]
            s0 = rotr(x, 7) ^ rotr(x, 18) ^ (x >> 3)
            s1 = rotr(y, 17) ^ rotr(y, 19) ^ (y >> 10)
            w.append((w[j - 16] + s0 + w[j - 7] + s1) & M32)
            j = j + 1
        a, b, c, d, e, f, g, hh = h
        j = 0
        while j < 64:
            S1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25)
            ch = (e & f) ^ ((M32 ^ e) & g)
            t1 = (hh + S1 + ch + K[j] + w[j]) & M32
            S0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22)
            maj = (a & b) ^ (a & c) ^ (b & c)
            hh = g
            g = f
            f = e
            e = (d + t1) & M32
            d = c
            c = b
            b = a
            a = (t1 + S0 + maj) & M32
            j = j + 1
        h = [(h[0] + a) & M32, (h[1] + b) & M32, (h[2] + c) & M32, (h[3] + d) & M32,
             (h[4] + e) & M32, (h[5] + f) & M32, (h[6] + g) & M32, (h[7] + hh) & M32]
        i = i + 64
    return h


def sha256(data):
    h = _sha256_blocks(list(_H256), data + _md_pad(len(data)))
    return struct.pack(">8I", h[0], h[1], h[2], h[3], h[4], h[5], h[6], h[7])


# ---------------------------------------------------------------- AES-256 (T-tables)

def _build_aes_tables():
    # GF(2^8) log/antilog tables
    exp = [0] * 512
    log = [0] * 256
    x = 1
    i = 0
    while i < 255:
        exp[i] = x
        log[x] = i
        # multiply x by 3
        y = x * 2
        if y & 256:
            y = y ^ 283
        x = x ^ y
        i = i + 1
    i = 255
    while i < 512:
        exp[i] = exp[i - 255]
        i = i + 1

    def mul(a, b, exp=exp, log=log):
        if a == 0 or b == 0:
            return 0
        return exp[log[a] + log[b]]

    sbox = [0] * 256
    inv = [0] * 256
    i = 0
    while i < 256:
        if i == 0:
            v = 0
        else:
            v = exp[255 - log[i]]
        s = v
        r = v
        k = 0
        while k < 4:
            r = ((r * 2) | (r >> 7)) & 255
            s = s ^ r
            k = k + 1
        s = s ^ 99
        sbox[i] = s
        inv[s] = i
        i = i + 1
    te = [[], [], [], []]
    td = [[], [], [], []]
    i = 0
    while i < 256:
        s = sbox[i]
        a = mul(s, 2)
        b = s
        c = s
        d = mul(s, 3)
        w = a * 16777216 + b * 65536 + c * 256 + d
        te[0].append(w)
        te[1].append(_rotr(w, 8))
        te[2].append(_rotr(w, 16))
        te[3].append(_rotr(w, 24))
        s = inv[i]
        w = (mul(s, 14) * 16777216 + mul(s, 9) * 65536 + mul(s, 13) * 256 + mul(s, 11))
        td[0].append(w)
        td[1].append(_rotr(w, 8))
        td[2].append(_rotr(w, 16))
        td[3].append(_rotr(w, 24))
        i = i + 1
    return sbox, inv, te, td


_SBOX, _INV, _TE, _TD = _build_aes_tables()


class AES256:
    """AES-256 block cipher; blocks are tuples of four 32-bit words."""
    def __init__(self, key):
        sbox = _SBOX
        w = list(struct.unpack(">8I", key))
        rcon = 1
        i = 8
        while i < 60:
            t = w[i - 1]
            if i % 8 == 0:
                t = _rotl(t, 8)
                t = (sbox[t >> 24] * 16777216 + sbox[(t >> 16) & 255] * 65536 +
                     sbox[(t >> 8) & 255] * 256 + sbox[t & 255])
                t = t ^ (rcon * 16777216)
                rcon = rcon * 2
                if rcon & 256:
                    rcon = rcon ^ 283
            elif i % 8 == 4:
                t = (sbox[t >> 24] * 16777216 + sbox[(t >> 16) & 255] * 65536 +
                     sbox[(t >> 8) & 255] * 256 + sbox[t & 255])
            w.append(w[i - 8] ^ t)
            i = i + 1
        self.ek = w
        # decryption key schedule (equivalent inverse cipher)
        dk = []
        r = 14
        while r >= 0:
            k = w[r * 4:r * 4 + 4]
            if 0 < r < 14:
                kk = []
                for v in k:
                    kk.append(_TD[0][sbox[v >> 24]] ^ _TD[1][sbox[(v >> 16) & 255]] ^
                              _TD[2][sbox[(v >> 8) & 255]] ^ _TD[3][sbox[v & 255]])
                k = kk
            dk.extend(k)
            r = r - 1
        self.dk = dk

    def encrypt(self, s0, s1, s2, s3):
        k = self.ek
        T0, T1, T2, T3 = _TE
        s0 = s0 ^ k[0]
        s1 = s1 ^ k[1]
        s2 = s2 ^ k[2]
        s3 = s3 ^ k[3]
        i = 4
        while i < 56:
            t0 = T0[s0 >> 24] ^ T1[(s1 >> 16) & 255] ^ T2[(s2 >> 8) & 255] ^ T3[s3 & 255] ^ k[i]
            t1 = T0[s1 >> 24] ^ T1[(s2 >> 16) & 255] ^ T2[(s3 >> 8) & 255] ^ T3[s0 & 255] ^ k[i + 1]
            t2 = T0[s2 >> 24] ^ T1[(s3 >> 16) & 255] ^ T2[(s0 >> 8) & 255] ^ T3[s1 & 255] ^ k[i + 2]
            t3 = T0[s3 >> 24] ^ T1[(s0 >> 16) & 255] ^ T2[(s1 >> 8) & 255] ^ T3[s2 & 255] ^ k[i + 3]
            s0 = t0
            s1 = t1
            s2 = t2
            s3 = t3
            i = i + 4
        S = _SBOX
        r0 = (S[s0 >> 24] * 16777216 + S[(s1 >> 16) & 255] * 65536 +
              S[(s2 >> 8) & 255] * 256 + S[s3 & 255]) ^ k[56]
        r1 = (S[s1 >> 24] * 16777216 + S[(s2 >> 16) & 255] * 65536 +
              S[(s3 >> 8) & 255] * 256 + S[s0 & 255]) ^ k[57]
        r2 = (S[s2 >> 24] * 16777216 + S[(s3 >> 16) & 255] * 65536 +
              S[(s0 >> 8) & 255] * 256 + S[s1 & 255]) ^ k[58]
        r3 = (S[s3 >> 24] * 16777216 + S[(s0 >> 16) & 255] * 65536 +
              S[(s1 >> 8) & 255] * 256 + S[s2 & 255]) ^ k[59]
        return r0, r1, r2, r3

    def decrypt(self, s0, s1, s2, s3):
        k = self.dk
        T0, T1, T2, T3 = _TD
        s0 = s0 ^ k[0]
        s1 = s1 ^ k[1]
        s2 = s2 ^ k[2]
        s3 = s3 ^ k[3]
        i = 4
        while i < 56:
            t0 = T0[s0 >> 24] ^ T1[(s3 >> 16) & 255] ^ T2[(s2 >> 8) & 255] ^ T3[s1 & 255] ^ k[i]
            t1 = T0[s1 >> 24] ^ T1[(s0 >> 16) & 255] ^ T2[(s3 >> 8) & 255] ^ T3[s2 & 255] ^ k[i + 1]
            t2 = T0[s2 >> 24] ^ T1[(s1 >> 16) & 255] ^ T2[(s0 >> 8) & 255] ^ T3[s3 & 255] ^ k[i + 2]
            t3 = T0[s3 >> 24] ^ T1[(s2 >> 16) & 255] ^ T2[(s1 >> 8) & 255] ^ T3[s0 & 255] ^ k[i + 3]
            s0 = t0
            s1 = t1
            s2 = t2
            s3 = t3
            i = i + 4
        S = _INV
        r0 = (S[s0 >> 24] * 16777216 + S[(s3 >> 16) & 255] * 65536 +
              S[(s2 >> 8) & 255] * 256 + S[s1 & 255]) ^ k[56]
        r1 = (S[s1 >> 24] * 16777216 + S[(s0 >> 16) & 255] * 65536 +
              S[(s3 >> 8) & 255] * 256 + S[s2 & 255]) ^ k[57]
        r2 = (S[s2 >> 24] * 16777216 + S[(s1 >> 16) & 255] * 65536 +
              S[(s0 >> 8) & 255] * 256 + S[s3 & 255]) ^ k[58]
        r3 = (S[s3 >> 24] * 16777216 + S[(s2 >> 16) & 255] * 65536 +
              S[(s1 >> 8) & 255] * 256 + S[s0 & 255]) ^ k[59]
        return r0, r1, r2, r3


def _words(s):
    n = len(s) / 4
    return struct.unpack(">%dI" % n, s)


def _pack_words(w):
    return struct.pack(">%dI" % len(w), *w)


def ige_encrypt(data, key, iv):
    if len(data) % 16:
        raise ValueError("IGE data must be a multiple of 16 bytes")
    aes = AES256(key)
    enc = aes.encrypt
    ivw = _words(iv)
    c0, c1, c2, c3 = ivw[0:4]    # previous ciphertext
    p0, p1, p2, p3 = ivw[4:8]    # previous plaintext
    w = _words(data)
    out = []
    i = 0
    n = len(w)
    while i < n:
        x0 = w[i]
        x1 = w[i + 1]
        x2 = w[i + 2]
        x3 = w[i + 3]
        y0, y1, y2, y3 = enc(x0 ^ c0, x1 ^ c1, x2 ^ c2, x3 ^ c3)
        c0 = y0 ^ p0
        c1 = y1 ^ p1
        c2 = y2 ^ p2
        c3 = y3 ^ p3
        out.append(c0)
        out.append(c1)
        out.append(c2)
        out.append(c3)
        p0 = x0
        p1 = x1
        p2 = x2
        p3 = x3
        i = i + 4
    return _pack_words(out)


def ige_decrypt(data, key, iv):
    if len(data) % 16:
        raise ValueError("IGE data must be a multiple of 16 bytes")
    aes = AES256(key)
    dec = aes.decrypt
    ivw = _words(iv)
    c0, c1, c2, c3 = ivw[0:4]
    p0, p1, p2, p3 = ivw[4:8]
    w = _words(data)
    out = []
    i = 0
    n = len(w)
    while i < n:
        x0 = w[i]
        x1 = w[i + 1]
        x2 = w[i + 2]
        x3 = w[i + 3]
        y0, y1, y2, y3 = dec(x0 ^ p0, x1 ^ p1, x2 ^ p2, x3 ^ p3)
        p0 = y0 ^ c0
        p1 = y1 ^ c1
        p2 = y2 ^ c2
        p3 = y3 ^ c3
        out.append(p0)
        out.append(p1)
        out.append(p2)
        out.append(p3)
        c0 = x0
        c1 = x1
        c2 = x2
        c3 = x3
        i = i + 4
    return _pack_words(out)


# ---------------------------------------------------------------- big integers

def bytes_to_long(s):
    if not s:
        return 0 * M32
    return long(binascii.hexlify(s), 16)


def long_to_bytes(n, length=0):
    h = "%x" % n
    if len(h) % 2:
        h = "0" + h
    s = binascii.unhexlify(h)
    if length:
        if len(s) > length:
            raise ValueError("number too large")
        s = "\x00" * (length - len(s)) + s
    return s


def xor_bytes(a, b):
    out = []
    i = 0
    n = len(a)
    while i < n:
        out.append(chr(ord(a[i]) ^ ord(b[i])))
        i = i + 1
    return "".join(out)


def _gcd(a, b):
    while b:
        a, b = b, a % b
    return a


def factor_pq(pq):
    """Splits Telegram's pq (product of two ~31-bit primes) with Pollard-Brent."""
    pq = long(pq)
    if pq % 2 == 0:
        return 2, pq / 2
    c = 1
    while 1:
        y = 2 + c * 0
        r = 1
        q = 1
        g = 1
        m = 128
        x = y
        ys = y
        while g == 1:
            x = y
            k = 0
            while k < r:
                y = (y * y + c) % pq
                k = k + 1
            k = 0
            while k < r and g == 1:
                ys = y
                j = 0
                lim = min(m, r - k)
                while j < lim:
                    y = (y * y + c) % pq
                    q = (q * abs(x - y)) % pq
                    j = j + 1
                g = _gcd(q, pq)
                k = k + m
            r = r * 2
        if g == pq:
            g = 1
            while g == 1:
                ys = (ys * ys + c) % pq
                g = _gcd(abs(x - ys), pq)
        if g != pq:
            p = min(g, pq / g)
            return p, pq / p
        c = c + 1


# ---------------------------------------------------------------- randomness
# No os.urandom on Python 2.2. A SHA-256 based generator is seeded from the
# clock, the CPU timer, object addresses and a seed file that is updated every
# time the app runs, so restarts never reuse a state.

class _Rand:
    def __init__(self):
        self.state = sha256(repr((time.time(), time.clock(), id(self), id([]))))
        self.counter = 0

    def mix(self, data):
        self.state = sha256(self.state + str(data) + repr((time.time(), time.clock())))

    def get(self, n):
        out = []
        have = 0
        while have < n:
            self.counter = self.counter + 1
            block = sha256(self.state + struct.pack(">I", self.counter & M32) +
                           repr(time.clock()))
            out.append(block)
            have = have + 32
        self.state = sha256("next" + self.state)
        return "".join(out)[:n]


_rand = _Rand()


def random_bytes(n):
    return _rand.get(n)


def add_entropy(data):
    _rand.mix(data)


def load_seed(path):
    try:
        f = open(path, "rb")
        add_entropy(f.read())
        f.close()
    except:
        pass
    try:
        f = open(path, "wb")
        f.write(random_bytes(64))
        f.close()
    except:
        pass


def random_long():
    """Random signed 64-bit number (TL long)."""
    v = bytes_to_long(random_bytes(8))
    if v >= pow(2 + 0 * M32, 63):
        v = v - pow(2 + 0 * M32, 64)
    return v
