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
print "native OK"
