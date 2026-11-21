# TL (Telegram's type language) reader/writer driven by schema.txt.
# Python 2.2 compatible (see tgcrypto.py for the integer rules).
#
# Objects are dicts: {"_": "constructorName", field: value, ...}.
# Primitive mapping: int -> int, long -> signed long, double -> float,
# string/bytes -> str (raw UTF-8), int128/int256 -> raw str, Bool -> 1/0,
# true flags -> 1 when set, Vector<T> -> list.

import struct
import zlib

M32 = 4294967295
P32 = 4294967296
P63 = 9223372036854775808
P64 = 18446744073709551616

ID_VECTOR = 481674261        # 0x1cb5c415
ID_GZIP = 812830625          # 0x3072cfa1
ID_TRUE = 2574415285         # boolTrue
ID_FALSE = 3162085175        # boolFalse

PRIMITIVE = {"int": 1, "long": 1, "double": 1, "string": 1, "bytes": 1,
             "int128": 1, "int256": 1, "Bool": 1, "true": 1, "#": 1}


class TLError(Exception):
    pass


class Raw:
    """Pre-serialized TL bytes (for a query:!X parameter)."""
    def __init__(self, data):
        self.data = data


class Schema:
    def __init__(self, path):
        self.by_id = {}     # id -> line (constructors)
        self.by_name = {}   # name -> (id, line) (constructors and functions)
        self.parsed = {}    # name -> (id, name, params, result, is_func)
        self.layer = 0
        f = open(path, "rb")
        text = f.read()
        f.close()
        for line in text.split("\n"):
            if not line:
                continue
            if line[:6] == "LAYER ":
                self.layer = int(line[6:])
                continue
            kind = line[0]
            sp = line.find(" ", 2)
            cid = long(line[2:sp], 16)
            sp2 = line.find(" ", sp + 1)
            name = line[sp + 1:sp2]
            if kind == "C":
                self.by_id[cid] = line
            self.by_name[name] = (cid, line)

    def _parse(self, line):
        parts = line.split(" ")
        kind = parts[0]
        cid = long(parts[1], 16)
        name = parts[2]
        params = []
        result = ""
        for p in parts[3:]:
            if not p:
                continue
            if p[0] == "=":
                result = " ".join([p[1:]] + parts[parts.index(p) + 1:])
                break
            c = p.find(":")
            pname = p[:c]
            ptype = p[c + 1:]
            flag = None
            bit = 0
            q = ptype.find("?")
            if q >= 0:
                cond = ptype[:q]
                ptype = ptype[q + 1:]
                d = cond.find(".")
                flag = cond[:d]
                bit = int(cond[d + 1:])
            params.append((pname, ptype, flag, bit))
        entry = (cid, name, params, result, kind == "F")
        self.parsed[name] = entry
        return entry

    def by_cid(self, cid):
        line = self.by_id.get(cid)
        if line is None:
            return None
        sp = line.find(" ", 2)
        name = line[sp + 1:line.find(" ", sp + 1)]
        e = self.parsed.get(name)
        if e is None:
            e = self._parse(line)
        return e

    def get(self, name):
        e = self.parsed.get(name)
        if e is None:
            x = self.by_name.get(name)
            if x is None:
                raise TLError("unknown TL name " + name)
            e = self._parse(x[1])
        return e

    def result_type(self, func):
        return self.get(func)[3]


def _is_bare(t):
    """Bare object type: lowercase final segment, not a primitive (e.g. future_salt)."""
    last = t.split(".")[-1]
    if last[:1] == "%":
        return 1
    return last[:1].islower() and not PRIMITIVE.has_key(t)


# ---------------------------------------------------------------- writing

def pack_int(v):
    return struct.pack("<i", v)


def pack_uint(v):
    return struct.pack("<I", v & M32)


def pack_long(v):
    v = long(v)
    if v < 0:
        v = v + P64
    return struct.pack("<II", v & M32, (v / P32) & M32)


def pack_bytes(s):
    if type(s) is type(u""):
        s = s.encode("utf-8")
    n = len(s)
    if n < 254:
        head = chr(n)
        total = n + 1
    else:
        head = "\xfe" + struct.pack("<I", n)[:3]
        total = n + 4
    pad = (4 - total % 4) % 4
    return head + s + "\x00" * pad


class Writer:
    def __init__(self, schema):
        self.schema = schema

    def obj(self, value, boxed=1):
        """Serializes a {"_": name, ...} dict (constructor or function)."""
        if isinstance(value, Raw):
            return value.data
        e = self.schema.get(value["_"])
        cid, name, params, result, is_func = e
        out = []
        if boxed or is_func:
            out.append(pack_uint(cid))
        # compute flags fields first
        flags = {}
        for pname, ptype, flag, bit in params:
            if ptype == "#":
                flags[pname] = 0
        for pname, ptype, flag, bit in params:
            if flag is not None:
                v = value.get(pname)
                if v is not None and not (ptype == "true" and not v):
                    flags[flag] = flags[flag] | pow(2, bit)
        for pname, ptype, flag, bit in params:
            if ptype == "#":
                out.append(pack_uint(flags[pname]))
                continue
            if flag is not None:
                if not (flags[flag] & pow(2, bit)):
                    continue
                if ptype == "true":
                    continue
            if not value.has_key(pname):
                raise TLError("%s: missing %s" % (name, pname))
            out.append(self.value(ptype, value[pname]))
        return "".join(out)

    def value(self, t, v):
        if t == "int":
            return pack_int(v)
        if t == "long":
            return pack_long(v)
        if t == "string" or t == "bytes":
            return pack_bytes(v)
        if t == "Bool":
            if v:
                return pack_uint(ID_TRUE)
            return pack_uint(ID_FALSE)
        if t == "double":
            return struct.pack("<d", v)
        if t == "int128" or t == "int256":
            return v
        if t == "!X" or t == "X" or t == "Object":
            if isinstance(v, Raw):
                return v.data
            return self.obj(v)
        if t[:7] == "Vector<" or t[:7] == "vector<":
            inner = t[7:-1]
            out = []
            if t[0] == "V":
                out.append(pack_uint(ID_VECTOR))
            out.append(pack_int(len(v)))
            for x in v:
                out.append(self.value(inner, x))
            return "".join(out)
        if _is_bare(t):
            return self.obj(v, 0)
        return self.obj(v)


# ---------------------------------------------------------------- reading

def gunzip(data):
    """gzip_packed payload -> bytes (raw inflate; old zlib has no gzip mode)."""
    if data[:2] != "\x1f\x8b":
        return zlib.decompress(data)
    flg = ord(data[3])
    i = 10
    if flg & 4:
        xlen = ord(data[i]) + 256 * ord(data[i + 1])
        i = i + 2 + xlen
    if flg & 8:
        i = data.index("\x00", i) + 1
    if flg & 16:
        i = data.index("\x00", i) + 1
    if flg & 2:
        i = i + 2
    return zlib.decompressobj(-15).decompress(data[i:])


class Reader:
    def __init__(self, schema, data, pos=0):
        self.schema = schema
        self.data = data
        self.pos = pos

    def raw(self, n):
        p = self.pos
        if p + n > len(self.data):
            raise TLError("TL data ended early")
        self.pos = p + n
        return self.data[p:p + n]

    def int(self):
        return struct.unpack("<i", self.raw(4))[0]

    def uint(self):
        return struct.unpack("<I", self.raw(4))[0]

    def long(self):
        lo, hi = struct.unpack("<II", self.raw(8))
        v = hi * P32 + lo
        if v >= P63:
            v = v - P64
        return v

    def double(self):
        return struct.unpack("<d", self.raw(8))[0]

    def bytes(self):
        n = ord(self.raw(1))
        if n >= 254:
            n = struct.unpack("<I", self.raw(3) + "\x00")[0]
            head = 4
        else:
            head = 1
        s = self.raw(n)
        total = n + head
        self.pos = self.pos + (4 - total % 4) % 4
        return s

    def obj(self, cid=None):
        """Reads a boxed object; gzip_packed is unpacked transparently."""
        if cid is None:
            cid = self.uint()
        if cid == ID_GZIP:
            inner = Reader(self.schema, gunzip(self.bytes()))
            return inner.obj()
        if cid == ID_TRUE:
            return 1
        if cid == ID_FALSE:
            return 0
        e = self.schema.by_cid(cid)
        if e is None:
            raise TLError("unknown constructor %08x at %d" % (cid, self.pos - 4))
        return self.fields(e)

    def fields(self, e):
        cid, name, params, result, is_func = e
        o = {"_": name}
        for pname, ptype, flag, bit in params:
            if flag is not None:
                if not (o[flag] & pow(2, bit)):
                    continue
                if ptype == "true":
                    o[pname] = 1
                    continue
            o[pname] = self.value(ptype)
        return o

    def value(self, t):
        if t == "int":
            return self.int()
        if t == "#":
            return self.uint()
        if t == "long":
            return self.long()
        if t == "string" or t == "bytes":
            return self.bytes()
        if t == "Bool":
            return self.obj()
        if t == "int128":
            return self.raw(16)
        if t == "int256":
            return self.raw(32)
        if t == "double":
            return self.double()
        if t[:7] == "Vector<" or t[:7] == "vector<":
            inner = t[7:-1]
            if t[0] == "V":
                cid = self.uint()
                if cid == ID_GZIP:
                    r = Reader(self.schema, gunzip(self.bytes()))
                    return r.value(t)
                if cid != ID_VECTOR:
                    raise TLError("expected vector, got %08x" % cid)
            n = self.int()
            out = []
            i = 0
            while i < n:
                out.append(self.value(inner))
                i = i + 1
            return out
        if _is_bare(t):
            name = t.split(" ")[0]
            if name[:1] == "%":
                name = name[1:]
                name = name[0].lower() + name[1:]
            return self.fields(self.schema.get(name))
        return self.obj()
