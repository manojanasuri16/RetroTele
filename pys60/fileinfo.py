# File helpers for "Attach file" (Python 2.2 / PyS60 1.4.5 compatible).
# Mime types, human sizes, ID3 title/artist, MP3 and MP4/3GP/M4A durations.
# Nothing here raises: unknown values come back as None.

import os

MIMES = {
    "mp3": "audio/mpeg", "m4a": "audio/mp4", "aac": "audio/aac", "amr": "audio/amr",
    "wav": "audio/x-wav", "ogg": "audio/ogg", "mp4": "video/mp4", "3gp": "video/3gpp",
    "avi": "video/x-msvideo", "mkv": "video/x-matroska", "pdf": "application/pdf",
    "txt": "text/plain", "zip": "application/zip", "rar": "application/x-rar-compressed",
    "7z": "application/x-7z-compressed", "apk": "application/vnd.android.package-archive",
    "sis": "application/vnd.symbian.install", "sisx": "application/vnd.symbian.install",
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xls": "application/vnd.ms-excel",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "ppt": "application/vnd.ms-powerpoint",
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "gif": "image/gif",
    "bmp": "image/bmp",
}
IMAGE_EXT = ["jpg", "jpeg", "png", "gif", "bmp"]
AUDIO_EXT = ["mp3", "m4a", "aac", "amr", "wav", "ogg"]
VIDEO_EXT = ["mp4", "3gp"]
MP4_EXT = ["mp4", "3gp", "m4a"]


def base_name(path):
    i = max(path.rfind("\\"), path.rfind("/"))
    return path[i + 1:]


def ext_of(name):
    i = name.rfind(".")
    if i < 0:
        return ""
    return name[i + 1:].lower()


def mime_for(name):
    return MIMES.get(ext_of(name), "application/octet-stream")


def is_image(name):
    return ext_of(name) in IMAGE_EXT


def is_audio(name):
    return ext_of(name) in AUDIO_EXT


def is_video(name):
    return ext_of(name) in VIDEO_EXT


def human_size(n):
    n = float(n)
    if n >= 1048576.0:
        return u"%.1f MB" % (n / 1048576.0)
    if n >= 1024.0:
        return u"%d KB" % int(n / 1024.0 + 0.5)
    return u"%d B" % int(n)


def progress_sizes(done, total):
    """'1.2/3.4 MB' (or KB for small files)."""
    if total >= 1048576:
        return u"%.1f/%.1f MB" % (done / 1048576.0, total / 1048576.0)
    return u"%d/%d KB" % (int(done / 1024.0), int(total / 1024.0 + 0.5))


def human_duration(seconds):
    try:
        s = int(seconds + 0.5)
    except:
        return u"?"
    h = s / 3600
    m = (s % 3600) / 60
    sec = s % 60
    if h:
        return u"%d:%02d:%02d" % (h, m, sec)
    return u"%d:%02d" % (m, sec)


def _be32(b):
    return (ord(b[0]) * 16777216) + (ord(b[1]) * 65536) + (ord(b[2]) * 256) + ord(b[3])


def _syncsafe(b):
    return (ord(b[0]) & 0x7f) * 2097152 + (ord(b[1]) & 0x7f) * 16384 + \
           (ord(b[2]) & 0x7f) * 128 + (ord(b[3]) & 0x7f)


def _decode(enc, data):
    try:
        if enc == 1:
            s = unicode(data, "utf-16")
        elif enc == 2:
            s = unicode(data, "utf-16-be")
        elif enc == 3:
            s = unicode(data, "utf-8")
        else:
            s = unicode(data, "latin-1")
    except:
        return None
    while s[-1:] == u"\x00":
        s = s[:-1]
    s = s.strip()
    if not s:
        return None
    return s


def _id3v1(f, size, out):
    if size < 128:
        return
    f.seek(size - 128)
    b = f.read(128)
    if b[:3] != "TAG":
        return
    out["title"] = _decode(0, b[3:33].split("\x00")[0])
    out["artist"] = _decode(0, b[33:63].split("\x00")[0])


def read_id3(path):
    """Returns {"title": u or None, "artist": u or None}."""
    out = {"title": None, "artist": None}
    f = None
    try:
        try:
            f = open(path, "rb")
            f.seek(0, 2)
            size = f.tell()
            f.seek(0)
            head = f.read(10)
            if len(head) < 10 or head[:3] != "ID3":
                _id3v1(f, size, out)
                return out
            ver = ord(head[3])
            tsize = _syncsafe(head[6:10])
            if tsize > 262144:
                tsize = 262144
            data = f.read(tsize)
            if ver < 4 and (ord(head[5]) & 0x80):
                data = data.replace("\xff\x00", "\xff")
            if ver == 2:
                hlen = 6
                names = {"TT2": "title", "TP1": "artist"}
            else:
                hlen = 10
                names = {"TIT2": "title", "TPE1": "artist"}
            pos = 0
            while pos + hlen <= len(data):
                if data[pos] == "\x00":
                    break
                if ver == 2:
                    fid = data[pos:pos + 3]
                    fs = ord(data[pos + 3]) * 65536 + ord(data[pos + 4]) * 256 + ord(data[pos + 5])
                elif ver == 4:
                    fid = data[pos:pos + 4]
                    fs = _syncsafe(data[pos + 4:pos + 8])
                else:
                    fid = data[pos:pos + 4]
                    fs = _be32(data[pos + 4:pos + 8])
                pos = pos + hlen
                if fs <= 0 or pos + fs > len(data):
                    break
                body = data[pos:pos + fs]
                pos = pos + fs
                if names.has_key(fid) and out[names[fid]] is None and body:
                    enc = ord(body[0])
                    t = body[1:]
                    if enc == 1 or enc == 2:
                        k = 0
                        while k + 1 < len(t):
                            if t[k] == "\x00" and t[k + 1] == "\x00":
                                t = t[:k]
                                break
                            k = k + 2
                    else:
                        k = t.find("\x00")
                        if k >= 0:
                            t = t[:k]
                    out[names[fid]] = _decode(enc, t)
            if out["title"] is None and out["artist"] is None:
                _id3v1(f, size, out)
        except:
            pass
    finally:
        if f is not None:
            try:
                f.close()
            except:
                pass
    return out


MP3_RATES = [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0]


def mp3_duration(path):
    """Seconds, estimated from the first MPEG-1 layer 3 frame (exact for CBR)."""
    f = None
    try:
        try:
            f = open(path, "rb")
            f.seek(0, 2)
            size = f.tell()
            f.seek(0)
            head = f.read(10)
            start = 0
            if head[:3] == "ID3" and len(head) == 10:
                start = _syncsafe(head[6:10]) + 10
            f.seek(start)
            buf = f.read(4096)
            i = 0
            while i + 4 <= len(buf):
                if buf[i] == "\xff" and (ord(buf[i + 1]) & 0xfe) == 0xfa:
                    rate = MP3_RATES[ord(buf[i + 2]) / 16]
                    srate = (ord(buf[i + 2]) / 4) % 4
                    if rate and srate < 3:
                        return float(size - start) * 8.0 / (rate * 1000.0)
                i = i + 1
        except:
            pass
    finally:
        if f is not None:
            try:
                f.close()
            except:
                pass
    return None


def _box_header(f, pos, end):
    """(size, kind, header_len) of the MP4 box at pos, or None."""
    f.seek(pos)
    h = f.read(8)
    if len(h) < 8:
        return None
    size = _be32(h[0:4])
    hdr = 8
    if size == 1:
        big = f.read(8)
        if len(big) < 8:
            return None
        size = _be32(big[0:4]) * 4294967296 + _be32(big[4:8])
        hdr = 16
    elif size == 0:
        size = end - pos
    if size < hdr:
        return None
    return size, h[4:8], hdr


def _mp4_walk(f, start, end, depth, info):
    pos = start
    while pos + 8 <= end:
        b = _box_header(f, pos, end)
        if b is None:
            return
        size, kind, hdr = b
        if kind == "mvhd" and info["dur"] is None:
            f.seek(pos + hdr)
            d = f.read(32)
            if len(d) >= 20:
                if ord(d[0]) == 1 and len(d) >= 32:
                    scale = _be32(d[20:24])
                    dur = _be32(d[24:28]) * 4294967296.0 + _be32(d[28:32])
                else:
                    scale = _be32(d[12:16])
                    dur = float(_be32(d[16:20]))
                if scale:
                    info["dur"] = dur / scale
        elif kind == "tkhd" and info["w"] == 0:
            f.seek(pos + hdr)
            d = f.read(96)
            if ord(d[0:1] or "\x00") == 1:
                wo = 88
            else:
                wo = 76
            if len(d) >= wo + 8:
                w = _be32(d[wo:wo + 4]) / 65536
                h = _be32(d[wo + 4:wo + 8]) / 65536
                if w and h:
                    info["w"] = int(w)
                    info["h"] = int(h)
        elif (kind == "moov" or kind == "trak") and depth < 3:
            _mp4_walk(f, pos + hdr, pos + size, depth + 1, info)
        pos = pos + size


def mp4_info(path):
    """(duration seconds or None, width, height) of an MP4/3GP/M4A file."""
    info = {"dur": None, "w": 0, "h": 0}
    f = None
    try:
        try:
            f = open(path, "rb")
            f.seek(0, 2)
            end = f.tell()
            f.seek(4)
            if f.read(4) in ("ftyp", "moov", "mdat", "free", "wide", "skip"):
                _mp4_walk(f, 0, end, 0, info)
        except:
            pass
    finally:
        if f is not None:
            try:
                f.close()
            except:
                pass
    return info["dur"], info["w"], info["h"]


def media_info(name, path):
    """{"duration": int or 0, "w": int, "h": int, "title": u/None, "performer": u/None}
    for audio and video files (zeros / None when unknown)."""
    out = {"duration": 0, "w": 0, "h": 0, "title": None, "performer": None}
    e = ext_of(name)
    try:
        if e == "mp3":
            tags = read_id3(path)
            out["title"] = tags["title"]
            out["performer"] = tags["artist"]
            d = mp3_duration(path)
            if d:
                out["duration"] = int(d + 0.5)
        elif e in MP4_EXT:
            d, w, h = mp4_info(path)
            if d:
                out["duration"] = int(d + 0.5)
            out["w"] = w
            out["h"] = h
    except:
        pass
    return out


def exif_thumb(path):
    """The small JPEG preview that cameras store inside the photo (bytes), or None."""
    try:
        f = open(path, "rb")
        head = f.read(65536)
        f.close()
    except:
        return None
    if head[:2] != "\xff\xd8":
        return None
    i = head.find("\xff\xd8\xff", 2)
    if i < 0:
        return None
    j = head.find("\xff\xd9", i)
    if j < 0:
        return None
    return head[i:j + 2]
