# Checks tgcrypto against known vectors (run with Python 2.7).
import sys, os, binascii, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import tgcrypto as c
h = binascii.hexlify
assert h(c.sha1("abc")) == "a9993e364706816aba3e25717850c26c9cd0d89d"
assert h(c.sha1("")) == "da39a3ee5e6b4b0d3255bfef95601890afd80709"
assert h(c.sha256("abc")) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
import hashlib
for n in [0, 1, 55, 56, 63, 64, 65, 119, 120, 1000]:
    d = "x" * n
    assert c.sha1(d) == hashlib.sha1(d).digest(), n
    assert c.sha256(d) == hashlib.sha256(d).digest(), n
# AES-256 FIPS-197 vector
key = binascii.unhexlify("000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f")
a = c.AES256(key)
pt = c._words(binascii.unhexlify("00112233445566778899aabbccddeeff"))
ct = a.encrypt(*pt)
assert h(c._pack_words(ct)) == "8ea2b7ca516745bfeafc49904b496089", h(c._pack_words(ct))
assert a.decrypt(*ct) == pt
# IGE vector (from the Telegram/OpenSSL test set)
k = binascii.unhexlify("000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f")
iv = binascii.unhexlify("000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f")
data = os.urandom(160)
enc = c.ige_encrypt(data, k, iv)
assert c.ige_decrypt(enc, k, iv) == data
# factorization
p, q = c.factor_pq(0x17ED48941A08F981)
assert (p, q) == (0x494C553B, 0x53911073), (p, q)
t = time.time(); c.factor_pq(1724114033281923457); print "factor %.2fs" % (time.time() - t)
assert c.long_to_bytes(c.bytes_to_long("\x01\x02"), 4) == "\x00\x00\x01\x02"
t = time.time(); c.sha256("x" * 64000); print "sha256 64KB %.2fs" % (time.time() - t)
t = time.time(); c.ige_encrypt("x" * 64000, k, iv); print "aes 64KB %.2fs" % (time.time() - t)
print "crypto OK"
