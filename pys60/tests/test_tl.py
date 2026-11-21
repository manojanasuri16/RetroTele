# TL writer/reader round trips (Python 2.7).
import sys, os
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import tl, zlib, struct, gzip, StringIO
s = tl.Schema(os.path.join(HERE, "..", "schema.txt"))
w = tl.Writer(s)
assert s.layer > 200
msg = {"_": "message", "out": 1, "id": 5, "peer_id": {"_": "peerUser", "user_id": 123456789012},
       "date": 1700000000, "message": "hello \xe2\x9c\x93", "entities": [],
       "from_id": {"_": "peerChannel", "channel_id": 77}}
data = w.obj(msg)
r = tl.Reader(s, data)
o = r.obj()
assert r.pos == len(data)
assert o["out"] == 1 and o["id"] == 5 and o["message"] == msg["message"], o
assert o["peer_id"]["user_id"] == 123456789012
assert not o.has_key("media") and o["entities"] == []
# negative longs and Bool
d = w.value("Vector<long>", [-1, 0, 2 ** 63 - 1, -2 ** 63])
assert tl.Reader(s, d).value("Vector<long>") == [-1, 0, 2 ** 63 - 1, -2 ** 63]
assert tl.Reader(s, w.value("Bool", 1)).value("Bool") == 1
assert tl.Reader(s, w.value("Bool", 0)).value("Bool") == 0
# long strings (>= 254 bytes)
for n in [0, 1, 253, 254, 255, 1000]:
    b = tl.pack_bytes("x" * n)
    assert len(b) % 4 == 0
    assert tl.Reader(s, b).bytes() == "x" * n
# gzip_packed transparently
buf = StringIO.StringIO()
g = gzip.GzipFile(fileobj=buf, mode="wb"); g.write(data); g.close()
packed = tl.pack_uint(tl.ID_GZIP) + tl.pack_bytes(buf.getvalue())
assert tl.Reader(s, packed).obj()["message"] == msg["message"]
# function with flags + nested object
f = w.obj({"_": "messages.sendMessage", "peer": {"_": "inputPeerSelf"}, "message": u"hi",
           "random_id": -5, "silent": 1})
flags = struct.unpack("<I", f[4:8])[0]
assert flags == 32, flags
assert s.result_type("messages.getDialogs") == "messages.Dialogs"
print "tl OK"
