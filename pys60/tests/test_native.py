# Checks the compiled crypto (native/tgnative) against the Python reference.
# Run with Python 2.7: TGNATIVE_DIR=<folder with tgnative.so> python2 test_native.py
import sys, os, time, hashlib
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.environ.get("TGNATIVE_DIR", "."))
sys.path.insert(0, os.path.join(HERE, ".."))
import tgnative, tgcrypto
for n in [0, 1, 55, 56, 63, 64, 65, 119, 120, 1000, 70000]:
    d = os.urandom(n)
    assert tgnative.sha256(d) == hashlib.sha256(d).digest(), n
    assert tgnative.sha1(d) == hashlib.sha1(d).digest(), n
for t in range(50):
    k = os.urandom(32); iv = os.urandom(32); d = os.urandom(16 * (t + 1))
    e = tgnative.ige_encrypt(d, k, iv)
    assert e == tgcrypto.ige_encrypt_ref(d, k, iv), t
    assert tgnative.ige_decrypt(e, k, iv) == d
for it in [1, 2, 1000]:
    assert tgnative.pbkdf2_sha512("pw", "s" * 40, it) == hashlib.pbkdf2_hmac("sha512", "pw", "s" * 40, it)
assert tgnative.pbkdf2_sha512("x" * 200, "salt", 3) == hashlib.pbkdf2_hmac("sha512", "x" * 200, "salt", 3)
d = os.urandom(1 << 20); k = os.urandom(32)
t = time.time(); tgnative.ige_decrypt(d, k, k); t1 = time.time() - t
t = time.time(); tgnative.sha256(d); t2 = time.time() - t
print "native: ige %.0f MB/s, sha256 %.0f MB/s (PC)" % (1 / t1, 1 / t2)
import random
def _b2l(s):
    return long(s.encode("hex"), 16) if s else 0L
def _l2b(n, ln):
    h = "%x" % n
    if len(h) % 2: h = "0" + h
    return ("\x00" * ln + h.decode("hex"))[-ln:] if ln else h.decode("hex")
import mtproto
P = long(mtproto.DH_PRIME, 16)
def npow(b, e, m):
    ln = (m.bit_length() + 7) // 8
    return _b2l(tgnative.powmod(_l2b(b, (b.bit_length() + 7) // 8), _l2b(e, (e.bit_length() + 7) // 8), _l2b(m, ln)))
tn = tp = 0.0
for t in range(30):
    e = random.getrandbits(2048)
    t0 = time.time(); a = npow(3, e, P); tn += time.time() - t0
    t0 = time.time(); b = pow(3, e, P); tp += time.time() - t0
    assert a == b, t
    g = random.getrandbits(2048)
    assert npow(g, e, P) == pow(g, e, P)
for bits in [8, 31, 32, 33, 64, 100, 512, 1000, 1024, 2047, 2048]:
    for t in range(10):
        m = random.getrandbits(bits) | 1 | (1 << (bits - 1))
        for e in [0, 1, 2, 65537, random.getrandbits(bits), random.getrandbits(256)]:
            for b in [0, 1, 2, m - 1, m, m + 5, random.getrandbits(bits), random.getrandbits(2048)]:
                assert npow(b, e, m) == pow(b, e, m), (bits, b, e, m)
assert tgnative.powmod("", "", "\x01") == "\x00"
for bad in [("\x02", "\x03", "\x04"), ("\x02", "\x03", ""), ("\x02", "\x03", "\x00"), ("\x02", "\x03", "\x01" + "\x00" * 256), ("2", "3" * 257, "\x05")]:
    try:
        tgnative.powmod(*bad); assert 0, bad
    except ValueError:
        pass
print "powmod 2048-bit: native %.1f ms, python pow %.1f ms (PC)" % (tn / 30 * 1000, tp / 30 * 1000)
print "native OK"
