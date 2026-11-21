# RetroTele screens drawn on a Canvas: chat list with tabs, chat view with
# bubbles, welcome screen. Telegram-like colours, round avatars (initials or
# the tiny photo thumbnail Telegram sends with every chat).
# Python 2.2 compatible: no conditional expressions, no sorted/enumerate.

import appuifw
import e32
import graphics
import key_codes

# ---------------------------------------------------------------- look

BLUE = 0x3390EC          # header, selection, badges
BLUE_DARK = 0x2A7BCB
BLUE_SOFT = 0xD6E8FB
WHITE = 0xFFFFFF
TEXT = 0x101418
GREY = 0x707579
GREY_LIGHT = 0xA7ABB0
LINE = 0xE7EAED
BG_CHAT = 0xC9DDEC       # chat background
BUBBLE_IN = 0xFFFFFF
BUBBLE_OUT = 0xE3FBC8
TIME_IN = 0x8D969C
TIME_OUT = 0x4FAE4E
SERVICE = 0x6F8BA1
MUTED = 0xC4C9CC
GREEN = 0x4DCD5E
HEADER_SUB = 0xD5E6FA

AVATAR_COLOURS = [0xFF516A, 0xFF885E, 0x665FFF, 0x54CB68, 0x28C9B7, 0x2A9EF1, 0xD669ED]
NAME_COLOURS = [0xE5464B, 0xE08A14, 0x8E59D8, 0x3BA83E, 0x1E9EA8, 0x2E86D6, 0xC2467F]

try:
    _AA = graphics.FONT_ANTIALIAS
    _BOLD = graphics.FONT_BOLD
except:
    _AA = 0
    _BOLD = 0

FONTS = {
    "title": (None, 18, _BOLD | _AA),
    "name": (None, 15, _BOLD | _AA),
    "text": (None, 15, _AA),
    "small": (None, 12, _AA),
    "smallb": (None, 12, _BOLD | _AA),
    "tab": (None, 13, _BOLD | _AA),
    "avatar": (None, 15, _BOLD | _AA),
    "big": (None, 26, _BOLD | _AA),
}
FALLBACK = {"title": "title", "name": "title", "text": "normal", "small": "dense",
            "smallb": "dense", "tab": "dense", "avatar": "title", "big": "title"}
_font_ok = [None]


def font(name):
    if _font_ok[0] == 0:
        return FALLBACK[name]
    return FONTS[name]


def check_fonts(img):
    """Scalable fonts given as (name, size, flags) need S60 3rd FP1+; fall back."""
    if _font_ok[0] is not None:
        return
    try:
        img.text((0, 10), u"x", fill=0, font=FONTS["text"])
        img.measure_text(u"x", font=FONTS["text"])
        _font_ok[0] = 1
    except:
        _font_ok[0] = 0


def to_u(s):
    if type(s) is type(u""):
        return s
    if s is None:
        return u""
    try:
        return unicode(s, "utf-8")
    except:
        return unicode(s, "latin-1")


# ---------------------------------------------------------------- emoji
# The phone's fonts have no emoji. Known emoji are swapped for a private-use
# character (U+E000 + sheet index) by prep(); width/fit/wrap count each one as
# EMW pixels and txt() draws it from a sprite sheet pre-blended on the
# background ("w" white, "o" outgoing green, "b" blue, "t" toast).

ASSET_DIR = [""]
EMW = 17          # emoji advance in text
_emoji = {"index": None, "sheets": {}}
SENT = 57344      # 0xE000
SENT_END = 57855


def set_asset_dir(d):
    ASSET_DIR[0] = d
    _emoji["index"] = None
    _emoji["sheets"] = {}


def emoji_index():
    idx = _emoji["index"]
    if idx is None:
        idx = {}
        try:
            f = open(ASSET_DIR[0] + "emoji.txt", "rb")
            n = 0
            for line in f.read().split("\n"):
                if line.strip():
                    idx[int(line.strip(), 16)] = n
                    n = n + 1
            f.close()
        except:
            pass
        _emoji["index"] = idx
    return idx


def emoji_sheet(name):
    sh = _emoji["sheets"].get(name, 0)
    if sh == 0:
        try:
            sh = graphics.Image.open(ASSET_DIR[0] + "emoji%s.png" % name)
        except:
            sh = None
        _emoji["sheets"][name] = sh
    return sh


def prep(text):
    """Unicode text with known emoji replaced by sheet characters."""
    t = to_u(text)
    if not t or max(t) < u"\u00a9":
        return t
    idx = emoji_index()
    out = []
    i = 0
    n = len(t)
    joined = 0
    while i < n:
        o = ord(t[i])
        step = 1
        cp = o
        if 55296 <= o <= 56319 and i + 1 < n:
            lo = ord(t[i + 1])
            if 56320 <= lo <= 57343:
                cp = 65536 + (o - 55296) * 1024 + (lo - 56320)
                step = 2
        i = i + step
        if cp == 65039 or (127995 <= cp <= 127999) or (917504 <= cp <= 917631):
            continue          # variation selector, skin tones, tags
        if cp == 8205:
            joined = 1        # zero width joiner: skip the next part
            continue
        if joined and (cp > 65535 or idx.has_key(cp)):
            joined = 0
            continue
        joined = 0
        k = idx.get(cp)
        if k is not None:
            out.append(unichr(SENT + k))
        elif cp > 65535:
            continue          # emoji we have no picture for
        elif SENT <= cp <= SENT_END:
            out.append(u" ")
        else:
            out.append(t[i - step:i])
    return u"".join(out)


def has_emoji(t):
    return t and max(t) >= u"\ue000"


def _split(t):
    """[(is_emoji, text or index)]"""
    runs = []
    cur = []
    for c in t:
        o = ord(c)
        if SENT <= o <= SENT_END:
            if cur:
                runs.append((0, u"".join(cur)))
                cur = []
            runs.append((1, o - SENT))
        else:
            cur.append(c)
    if cur:
        runs.append((0, u"".join(cur)))
    return runs


def txt(g, x, y, t, fill, f, bg="w"):
    """Draws prepped text with emoji at baseline y."""
    if not has_emoji(t):
        g.text((x, y), t, fill=fill, font=font(f))
        return
    sheet = emoji_sheet("16_" + bg)
    for is_e, v in _split(t):
        if is_e:
            if sheet is not None:
                sx = (v % 20) * 16
                sy = (v / 20) * 16
                try:
                    g.blit(sheet, target=(x, y - 13), source=((sx, sy), (sx + 16, sy + 16)))
                except:
                    pass
            x = x + EMW
        else:
            g.text((x, y), v, fill=fill, font=font(f))
            x = x + _plain_width(g, v, f)


def big_emoji(g, x, y, k):
    sheet = emoji_sheet("40_c")
    if sheet is None:
        return 0
    sx = (k % 20) * 40
    sy = (k / 20) * 40
    try:
        g.blit(sheet, target=(x, y), source=((sx, sy), (sx + 40, sy + 40)))
        return 1
    except:
        return 0


def _plain_width(g, text, f):
    try:
        return g.measure_text(text, font=font(f))[1]
    except:
        return len(text) * 7


def width(g, text, f):
    if has_emoji(text):
        w = 0
        for is_e, v in _split(text):
            if is_e:
                w = w + EMW
            else:
                w = w + _plain_width(g, v, f)
        return w
    return _plain_width(g, text, f)


def _fit_count(g, text, f, maxw):
    """How many characters of text fit in maxw pixels."""
    if not has_emoji(text):
        try:
            return g.measure_text(text, font=font(f), maxwidth=maxw)[2]
        except:
            return maxw / 7
    lo = 0
    hi = len(text)
    while lo < hi:
        mid = (lo + hi + 1) / 2
        if width(g, text[:mid], f) <= maxw:
            lo = mid
        else:
            hi = mid - 1
    return lo


def fit(g, text, f, maxw):
    """text (emoji prepared) shortened with an ellipsis to fit maxw pixels."""
    text = prep(text).replace(u"\n", u" ")
    if maxw <= 0:
        return u""
    n = _fit_count(g, text, f, maxw)
    if n >= len(text):
        return text
    if n < 2:
        return u""
    n = _fit_count(g, text, f, maxw - _plain_width(g, u"\u2026", f))
    return text[:n].rstrip() + u"\u2026"


def wrap(g, text, f, maxw, max_lines=200):
    """Word-wraps text (emoji prepared) into lines of at most maxw pixels."""
    out = []
    for para in prep(text).split(u"\n"):
        while 1:
            if len(out) >= max_lines:
                return out
            if not para:
                out.append(u"")
                break
            n = _fit_count(g, para, f, maxw)
            if n >= len(para):
                out.append(para)
                break
            if n < 1:
                n = 1
            cut = para.rfind(u" ", 0, n + 1)
            if cut <= 0:
                cut = n
                out.append(para[:cut])
                para = para[cut:]
            else:
                out.append(para[:cut])
                para = para[cut + 1:]
    return out


def rrect(g, x1, y1, x2, y2, r, fill):
    """Filled rounded rectangle."""
    if r * 2 > y2 - y1:
        r = (y2 - y1) / 2
    if r * 2 > x2 - x1:
        r = (x2 - x1) / 2
    if r < 1:
        g.rectangle((x1, y1, x2, y2), fill=fill)
        return
    d = r * 2
    g.rectangle((x1 + r, y1, x2 - r, y2), fill=fill)
    g.rectangle((x1, y1 + r, x2, y2 - r), fill=fill)
    g.ellipse((x1, y1, x1 + d, y1 + d), fill=fill)
    g.ellipse((x2 - d, y1, x2, y1 + d), fill=fill)
    g.ellipse((x1, y2 - d, x1 + d, y2), fill=fill)
    g.ellipse((x2 - d, y2 - d, x2, y2), fill=fill)


def tick(g, x, y, colour, double):
    """Sent (one tick) or read (two ticks) mark, 12x8 px from (x, y)."""
    g.line((x, y + 4, x + 3, y + 7), outline=colour, width=2)
    g.line((x + 3, y + 7, x + 8, y + 1), outline=colour, width=2)
    if double:
        g.line((x + 5, y + 6, x + 6, y + 7), outline=colour, width=2)
        g.line((x + 6, y + 7, x + 11, y + 1), outline=colour, width=2)


def plane(g, cx, cy, s, colour):
    """A paper plane of size s centred at (cx, cy)."""
    g.polygon([(cx - s / 2, cy - s / 10), (cx + s / 2, cy - s / 2), (cx + s / 5, cy + s / 2),
               (cx, cy + s / 8)], fill=colour)
    g.polygon([(cx, cy + s / 8), (cx - s / 12, cy + s / 3), (cx + s / 10, cy + s / 5)],
              fill=colour)


def bookmark(g, cx, cy, s, colour):
    w = s * 2 / 5
    g.polygon([(cx - w / 2, cy - s / 2), (cx + w / 2, cy - s / 2), (cx + w / 2, cy + s / 2),
               (cx, cy + s / 4), (cx - w / 2, cy + s / 2)], fill=colour)


def initials(name):
    words = []
    for w in to_u(name).split(u" "):
        if w and (w[0].isalnum()):
            words.append(w)
    if not words:
        n = to_u(name).strip()
        if n:
            return n[0].upper()
        return u"?"
    s = words[0][0]
    if len(words) > 1:
        s = s + words[1][0]
    return s.upper()


def colour_for(key, palette):
    try:
        n = long(key[1:])
    except:
        n = 0
    return palette[int(n % len(palette))]


def short_time(ts, now, tz):
    """12:34 today, Mon this week, 21.11.24 older."""
    import time
    if not ts:
        return u""
    t = time.gmtime(ts + tz)
    n = time.gmtime(now + tz)
    if t[:3] == n[:3]:
        return unicode(time.strftime("%H:%M", t))
    if now - ts < 6 * 86400:
        return unicode(time.strftime("%a", t))
    return unicode(time.strftime("%d.%m.%y", t))


def day_label(ts, now, tz):
    import time
    t = time.gmtime(ts + tz)
    n = time.gmtime(now + tz)
    if t[:3] == n[:3]:
        return u"Today"
    y = time.gmtime(now - 86400 + tz)
    if t[:3] == y[:3]:
        return u"Yesterday"
    if t[0] == n[0]:
        return unicode(time.strftime("%d %B", t)).lstrip(u"0")
    return unicode(time.strftime("%d %B %Y", t)).lstrip(u"0")


# ---------------------------------------------------------------- avatars

class Avatars:
    """Round avatars: initials on a colour, replaced by the photo thumbnail
    once decoded. Thumbnails are decoded one per timer tick (keys stay
    responsive) and kept for at most LIMIT chats."""
    LIMIT = 60

    def __init__(self, app, tmp_path):
        self.app = app
        self.tmp = tmp_path
        self.images = {}       # (key, size) -> Image or None (no photo)
        self.order = []
        self.queue = []
        self.masks = {}
        self.busy = 0

    def mask(self, s):
        m = self.masks.get(s)
        if m is None:
            m = graphics.Image.new((s, s), "1")
            m.clear(0)
            m.ellipse((0, 0, s, s), fill=0xFFFFFF)
            self.masks[s] = m
        return m

    def draw(self, g, key, name, photo, x, y, s, special=None):
        img = self.images.get((key, s), 0)
        if img:
            try:
                g.blit(img, target=(x, y), mask=self.mask(s))
                return
            except:
                pass
        g.ellipse((x, y, x + s, y + s), fill=colour_for(key, AVATAR_COLOURS))
        if special == "saved":
            bookmark(g, x + s / 2, y + s / 2, s / 2, WHITE)
            return
        t = initials(name)
        f = "avatar"
        w = width(g, t, f)
        g.text((x + (s - w) / 2, y + s / 2 + 5), t, fill=WHITE, font=font(f))
        if img == 0 and photo:
            self.images[(key, s)] = None
            self.queue.append((key, s, photo))
            if not self.busy:
                self.busy = 1
                self.app.net.later(0.05, self.work)

    def work(self):
        if not self.queue:
            self.busy = 0
            return
        key, s, photo = self.queue.pop(0)
        try:
            import tgclient
            jpg = tgclient.stripped_to_jpeg(photo)
            if jpg:
                f = open(self.tmp, "wb")
                f.write(jpg)
                f.close()
                img = graphics.Image.open(self.tmp)
                img = img.resize((s, s))
                self.images[(key, s)] = img
                self.order.append((key, s))
                if len(self.order) > self.LIMIT:
                    old = self.order.pop(0)
                    self.images[old] = None
                self.app.avatar_ready()
        except:
            pass
        self.app.net.later(0.05, self.work)


# ---------------------------------------------------------------- base view

class CanvasView:
    HEADER_H = 46

    def __init__(self, app):
        self.app = app
        self.canvas = None
        self.buf = None

    def show(self):
        self.canvas = appuifw.Canvas(redraw_callback=self.on_redraw)
        appuifw.app.body = self.canvas
        c = self.canvas
        c.bind(key_codes.EKeyUpArrow, lambda self=self: self.key("up"))
        c.bind(key_codes.EKeyDownArrow, lambda self=self: self.key("down"))
        c.bind(key_codes.EKeyLeftArrow, lambda self=self: self.key("left"))
        c.bind(key_codes.EKeyRightArrow, lambda self=self: self.key("right"))
        c.bind(key_codes.EKeySelect, lambda self=self: self.key("select"))
        for ch in "0123456789*#":
            try:
                c.bind(ord(ch), lambda self=self, ch=ch: self.key(ch))
            except:
                pass
        self.draw()

    def size(self):
        try:
            return self.canvas.size
        except:
            return (240, 292)

    def on_redraw(self, rect):
        if self.buf is not None:
            try:
                self.canvas.blit(self.buf)
                return
            except:
                pass
        self.draw()

    def draw(self):
        if self.canvas is None:
            return
        import time
        t0 = time.clock()
        w, h = self.size()
        if self.buf is None or self.buf.size != (w, h):
            self.buf = graphics.Image.new((w, h))
        g = self.buf
        check_fonts(g)
        try:
            self.paint(g, w, h)
        except:
            import sys
            self.app.log("paint: " + str(sys.exc_info()[1]))
            try:
                import traceback
                self.app.log("".join(traceback.format_exception(
                    sys.exc_info()[0], sys.exc_info()[1], sys.exc_info()[2])))
            except:
                pass
        try:
            self.canvas.blit(g)
        except:
            pass
        dt = time.clock() - t0
        if dt > 0.4:
            self.app.log("slow paint %s %.2fs" % (self.__class__.__name__, dt))

    def key(self, k):
        pass

    def paint(self, g, w, h):
        pass

    def header(self, g, w, title, sub, key=None, special=None, online=0):
        H = self.HEADER_H
        g.rectangle((0, 0, w, H), fill=BLUE)
        x = 10
        if key is not None:
            self.app.avatars.draw(g, key, title, self.app.client.peer(key).get("photo"),
                                  8, 7, 32, special)
            if online:
                g.ellipse((31, 30, 41, 40), fill=BLUE)
                g.ellipse((33, 32, 39, 38), fill=GREEN)
            x = 48
        busy = self.app.busy
        if busy:
            sub = busy
        if sub:
            txt(g, x, 21, fit(g, title, "name", w - x - 8), WHITE, "name", "b")
            txt(g, x, 38, fit(g, sub, "small", w - x - 8), HEADER_SUB, "small", "b")
        else:
            txt(g, x, 30, fit(g, title, "title", w - x - 8), WHITE, "title", "b")

    def toast(self, g, w, h):
        t = self.app.toast_text
        if not t:
            return
        y = self.HEADER_H + 4
        rrect(g, 6, y, w - 6, y + 40, 8, 0x25303A)
        txt(g, 14, y + 17, fit(g, t[0], "smallb", w - 28), 0x8CC8FF, "smallb", "t")
        txt(g, 14, y + 34, fit(g, t[1], "small", w - 28), WHITE, "small", "t")

    def scrollbar(self, g, w, y1, y2, first, shown, total):
        if total <= shown or total <= 0:
            return
        span = y2 - y1
        th = max(span * shown / total, 12)
        ty = y1 + (span - th) * first / max(total - shown, 1)
        rrect(g, w - 4, ty, w - 1, ty + th, 1, 0xB9C3CC)


# ---------------------------------------------------------------- chat list

class ChatListView(CanvasView):
    ROW_H = 54
    TABS_H = 30

    def __init__(self, app):
        CanvasView.__init__(self, app)
        self.tab = 0
        self.cur = 0
        self.top = 0
        self.tab_scroll = 0

    def rows(self):
        return self.app.tab_rows(self.tab)

    def key(self, k):
        rows = self.rows()
        n = len(rows)
        if k == "up":
            if self.cur > 0:
                self.cur = self.cur - 1
            elif n:
                self.cur = n - 1
        elif k == "down":
            if self.cur < n - 1:
                self.cur = self.cur + 1
            else:
                self.cur = 0
            if self.cur >= n - 3:
                self.app.near_end(self.tab)
        elif k == "left" or k == "right":
            tabs = self.app.tabs()
            if k == "left":
                self.tab = (self.tab - 1) % len(tabs)
            else:
                self.tab = (self.tab + 1) % len(tabs)
            self.cur = 0
            self.top = 0
            self.app.tab_changed(self.tab)
        elif k == "select":
            if 0 <= self.cur < n:
                self.app.open_row(rows[self.cur])
            return
        elif k in ("2",):
            return self.key("up")
        elif k in ("8",):
            return self.key("down")
        elif k == "4":
            return self.key("left")
        elif k == "6":
            return self.key("right")
        elif k == "5":
            return self.key("select")
        self.draw()

    def current(self):
        rows = self.rows()
        if 0 <= self.cur < len(rows):
            return rows[self.cur]
        return None

    def paint(self, g, w, h):
        app = self.app
        g.clear(WHITE)
        sub = None
        if not app.is_online:
            sub = u"Waiting for network..."
        self.header(g, w, u"RetroTele", sub)
        # tabs
        tabs = app.tabs()
        ty = self.HEADER_H
        g.rectangle((0, ty, w, ty + self.TABS_H), fill=BLUE)
        xs = []
        x = 0
        for t in tabs:
            label = to_u(t[0])
            tw = width(g, label, "tab") + 20
            xs.append((x, tw, label, t))
            x = x + tw
        if self.tab >= len(xs):
            self.tab = 0
        sx, sw, sl, st = xs[self.tab]
        if sx - self.tab_scroll < 0:
            self.tab_scroll = sx
        if sx + sw - self.tab_scroll > w:
            self.tab_scroll = sx + sw - w
        i = 0
        for x, tw, label, t in xs:
            xx = x - self.tab_scroll
            if xx + tw >= 0 and xx <= w:
                colour = HEADER_SUB
                if i == self.tab:
                    colour = WHITE
                    g.rectangle((xx + 6, ty + self.TABS_H - 3, xx + tw - 6, ty + self.TABS_H),
                                fill=WHITE)
                g.text((xx + 10, ty + 19), label, fill=colour, font=font("tab"))
                badge = t[1]
                if badge:
                    pass
            i = i + 1
        # rows
        rows = self.rows()
        y0 = ty + self.TABS_H
        visible = max((h - y0) / self.ROW_H, 1)
        if self.cur >= len(rows):
            self.cur = max(len(rows) - 1, 0)
        if self.cur < self.top:
            self.top = self.cur
        if self.cur >= self.top + visible:
            self.top = self.cur - visible + 1
        if not rows:
            msg = app.empty_text(self.tab)
            g.text(((w - width(g, msg, "text")) / 2, y0 + 60), msg, fill=GREY,
                   font=font("text"))
        y = y0
        i = self.top
        while i < len(rows) and y < h:
            self.paint_row(g, w, y, rows[i], i == self.cur)
            y = y + self.ROW_H
            i = i + 1
        self.scrollbar(g, w, y0, h, self.top, visible, len(rows))
        self.toast(g, w, h)

    def paint_row(self, g, w, y, r, sel):
        app = self.app
        cl = app.client
        key = r["key"]
        RH = self.ROW_H
        if sel:
            g.rectangle((0, y, w, y + RH), fill=BLUE)
            c_name = WHITE
            c_sub = WHITE
            c_time = WHITE
            c_sender = WHITE
        else:
            c_name = TEXT
            c_sub = GREY
            c_time = GREY
            c_sender = BLUE
        p = cl.peer(key)
        special = None
        name = cl.peer_name(key)
        if p["kind"] == "self":
            special = "saved"
        app.avatars.draw(g, key, name, p.get("photo"), 8, y + 7, 40, special)
        if r.get("online"):
            g.ellipse((37, y + 36, 49, y + 48), fill=(sel and BLUE) or WHITE)
            g.ellipse((39, y + 38, 47, y + 46), fill=GREEN)
        x = 58
        # right column: time and ticks
        rt = r.get("time", u"")
        tw = width(g, rt, "small")
        g.text((w - 8 - tw, y + 20), rt, fill=c_time, font=font("small"))
        right = tw + 14
        if r.get("out") and r.get("read_out") is not None and not r.get("contact_row"):
            read = r["top"] <= r.get("read_out", 0)
            tc = TIME_OUT
            if sel:
                tc = WHITE
            tick(g, w - 8 - tw - 15, y + 11, tc, read)
            right = right + 16
        kind = p["kind"]
        nx = x
        if kind in ("group", "supergroup", "channel") and not r.get("contact_row"):
            # a small group / channel marker before the name
            ic = GREY
            if sel:
                ic = WHITE
            if kind == "channel":
                g.polygon([(nx, y + 13), (nx + 4, y + 13), (nx + 9, y + 9), (nx + 9, y + 21),
                           (nx + 4, y + 17), (nx, y + 17)], fill=ic)
            else:
                g.ellipse((nx + 1, y + 9, nx + 6, y + 14), fill=ic)
                g.ellipse((nx, y + 15, nx + 7, y + 22), fill=ic)
                g.ellipse((nx + 6, y + 10, nx + 10, y + 14), fill=ic)
            nx = nx + 13
        bg = "w"
        if sel:
            bg = "b"
        txt(g, nx, y + 21, fit(g, name, "name", w - nx - right), c_name, "name", bg)
        # second line: sender, preview, unread badge
        badge = u""
        if r.get("unread"):
            badge = unicode(str(r["unread"]))
        elif r.get("mark"):
            badge = u" "
        bw = 0
        if badge:
            bw = max(width(g, badge, "smallb") + 12, 22)
            bc = BLUE
            if r.get("muted"):
                bc = MUTED
            fc = WHITE
            if sel:
                bc = WHITE
                fc = BLUE
            rrect(g, w - 8 - bw, y + 30, w - 8, y + 50, 10, bc)
            g.text((w - 8 - bw + (bw - width(g, badge, "smallb")) / 2, y + 45), badge,
                   fill=fc, font=font("smallb"))
            bw = bw + 6
        px = x
        maxw = w - 8 - bw - px
        sender = prep(r.get("sender", u""))
        if sender:
            s = sender + u": "
            sw = width(g, s, "text")
            if sw < maxw / 2:
                txt(g, px, y + 44, s, c_sender, "text", bg)
                px = px + sw
                maxw = maxw - sw
        txt(g, px, y + 44, fit(g, r.get("preview", u""), "text", maxw), c_sub, "text", bg)
        if not sel:
            g.line((x, y + RH - 1, w, y + RH - 1), outline=LINE)


# ---------------------------------------------------------------- chat view

class ChatView(CanvasView):
    INPUT_H = 38
    PAD = 7

    def __init__(self, app, key):
        CanvasView.__init__(self, app)
        self.key_ = key
        self.sel = -1          # index into messages; len(messages) = input bar
        self.layout_cache = {}  # (id, text, width) -> layout
        self.scroll_to_sel = 1

    def messages(self):
        return self.app.chat_messages(self.key_)

    def key(self, k):
        msgs = self.messages()
        n = len(msgs)
        if self.sel < 0 or self.sel > n:
            self.sel = n
        if k == "up" or k == "2":
            if self.sel > 0:
                self.sel = self.sel - 1
                if self.sel < 3:
                    self.app.load_older()
            else:
                self.app.load_older()
        elif k == "down" or k == "8":
            if self.sel < n:
                self.sel = self.sel + 1
        elif k == "select" or k == "5":
            if self.sel >= n:
                self.app.compose()
            else:
                self.app.message_menu(msgs[self.sel])
            return
        elif k == "left":
            self.app.back_to_chats()
            return
        elif k == "right":
            pass
        elif k in "0134679*#":
            self.app.compose()
            return
        self.draw()

    def selected(self):
        msgs = self.messages()
        if 0 <= self.sel < len(msgs):
            return msgs[self.sel]
        return None

    def at_bottom(self):
        return self.sel < 0 or self.sel >= len(self.messages())

    def layout(self, g, m, maxw, group):
        """Lines and size of one bubble (cached)."""
        ck = (m["id"], m["text"], m["media"], maxw, m.get("edited", 0))
        lay = self.layout_cache.get(ck)
        if lay is not None:
            return lay
        lines = []
        if m["service"]:
            lines = wrap(g, m["text"], "small", maxw - 16, 4)
            lw = 0
            for l in lines:
                lw = max(lw, width(g, l, "small"))
            lay = {"service": 1, "lines": lines, "w": lw + 16, "h": len(lines) * 15 + 8}
            self.layout_cache[ck] = lay
            return lay
        inner = maxw - 2 * self.PAD
        if m.get("sticker") is not None and not m.get("reply_to"):
            e = prep(m["sticker"])
            if e and has_emoji(e[:1]):
                meta = self.app.hhmm(m["date"])
                lay = {"service": 0, "sticker": ord(e[0]) - SENT, "w": 48, "h": 66,
                       "meta": meta, "mw": width(g, meta, "small") + 12}
                self.layout_cache[ck] = lay
                return lay
        head = []
        if group and not m["out"]:
            head.append(("name", fit(g, m["from"], "smallb", inner)))
        if m.get("fwd"):
            head.append(("fwd", fit(g, u"Forwarded from " + to_u(m["fwd"]), "small", inner)))
        if m.get("reply_to"):
            q = self.app.quote_for(self.key_, m["reply_to"])
            head.append(("reply", (fit(g, q[0], "smallb", inner - 8),
                                   fit(g, q[1], "small", inner - 8))))
        body = []
        photo = None
        if m.get("photo"):
            pi = m["photo"]
            pw = min(maxw - 6, 180)
            ph = 120
            if pi.get("w") and pi.get("h"):
                ph = pw * pi["h"] / pi["w"]
            if ph > 200:
                pw = max(pw * 200 / ph, 60)
                ph = 200
            ph = max(ph, 50)
            photo = (pw, ph)
        elif m["media"]:
            for l in wrap(g, m["media"], "text", inner, 3):
                body.append(("media", l))
        if m["text"]:
            for l in wrap(g, m["text"], "text", inner, 120):
                body.append(("text", l))
        meta = self.app.hhmm(m["date"])
        if m.get("edited"):
            meta = u"edited " + meta
        mw = width(g, meta, "small") + 4
        if m["out"]:
            mw = mw + 16
        bw = mw
        for kind, l in head:
            if kind == "reply":
                bw = max(bw, max(width(g, l[0], "smallb"), width(g, l[1], "small")) + 8)
            else:
                bw = max(bw, width(g, l, "small"))
        last_w = 0
        for kind, l in body:
            last_w = width(g, l, "text")
            bw = max(bw, last_w)
        h = self.PAD
        for kind, l in head:
            if kind == "reply":
                h = h + 34
            else:
                h = h + 15
        if photo is not None:
            bw = max(bw, photo[0] + 6 - 2 * self.PAD)
            h = h + photo[1] + 4
            if not head:
                h = h - self.PAD + 3
        h = h + len(body) * 18
        # time on the last line if it fits, else on its own line
        meta_own_line = 1
        if body and last_w + mw + 8 <= inner:
            meta_own_line = 0
            bw = max(bw, last_w + mw + 8)
        if meta_own_line:
            h = h + 15
        h = h + 6
        lay = {"service": 0, "head": head, "body": body, "meta": meta, "mw": mw,
               "own": meta_own_line, "w": bw + 2 * self.PAD, "h": h, "photo": photo}
        self.layout_cache[ck] = lay
        return lay

    def items(self, g, w):
        """[(kind, data, height)] for the whole conversation."""
        app = self.app
        msgs = self.messages()
        maxw = w * 4 / 5
        group = app.client.is_group(self.key_)
        out = []
        last_day = None
        import time
        i = 0
        for m in msgs:
            day = time.gmtime(m["date"] + app.tz)[:3]
            if day != last_day:
                out.append(("day", day_label(m["date"], app.client.server_time(), app.tz),
                            30, -1))
                last_day = day
            lay = self.layout(g, m, maxw, group)
            out.append(("msg", (m, lay), lay["h"] + 6, i))
            i = i + 1
        return out

    def paint(self, g, w, h):
        app = self.app
        cl = app.client
        key = self.key_
        g.clear(BG_CHAT)
        msgs = self.messages()
        n = len(msgs)
        if self.sel < 0 or self.sel > n:
            self.sel = n
        top = self.HEADER_H
        bottom = h - self.INPUT_H
        items = self.items(g, w)
        # total height and position of the selected item
        total = 0
        sel_y = None
        sel_h = 0
        for kind, data, ih, idx in items:
            if idx == self.sel:
                sel_y = total
                sel_h = ih
            total = total + ih
        total = total + 6
        view = bottom - top
        # the end of the conversation sits at the bottom; scroll to keep the
        # selection visible
        if sel_y is None:
            off = max(total - view, 0)
        else:
            off = max(total - view, 0)
            if sel_y < off:
                off = sel_y
            if sel_y + sel_h > off + view:
                off = sel_y + sel_h - view
            if sel_h > view:
                off = sel_y
            off = max(min(off, max(total - view, 0)), 0)
        base = top + max(view - total, 0) - off
        y = base + 4
        for kind, data, ih, idx in items:
            if y + ih >= top and y <= bottom:
                if kind == "day":
                    tw = width(g, data, "smallb") + 20
                    rrect(g, (w - tw) / 2, y + 6, (w + tw) / 2, y + 24, 9, 0x8FA9BE)
                    g.text(((w - tw) / 2 + 10, y + 20), data, fill=WHITE, font=font("smallb"))
                else:
                    self.paint_msg(g, w, y, data[0], data[1], idx == self.sel)
            y = y + ih
        if not msgs:
            t = app.chat_empty_text()
            tw = width(g, t, "small") + 24
            rrect(g, (w - tw) / 2, top + 60, (w + tw) / 2, top + 84, 12, 0x8FA9BE)
            g.text(((w - tw) / 2 + 12, top + 77), t, fill=WHITE, font=font("small"))
        # input bar
        g.rectangle((0, bottom, w, h), fill=WHITE)
        g.line((0, bottom, w, bottom), outline=LINE)
        focus = self.sel >= n
        if cl.can_write(key):
            fc = 0xF1F3F5
            if focus:
                rrect(g, 5, bottom + 4, w - 5, h - 4, 15, BLUE)
                rrect(g, 7, bottom + 6, w - 7, h - 6, 13, WHITE)
            else:
                rrect(g, 6, bottom + 5, w - 6, h - 5, 14, fc)
            hint = app.draft_preview(key)
            colour = TEXT
            if not hint:
                hint = u"Message"
                colour = GREY_LIGHT
            txt(g, 18, bottom + 25, fit(g, hint, "text", w - 64), colour, "text", "w")
            plane(g, w - 24, bottom + self.INPUT_H / 2, 16, (focus and BLUE) or GREY_LIGHT)
        else:
            t = u"Only admins can post here"
            g.text(((w - width(g, t, "small")) / 2, bottom + 24), t, fill=GREY,
                   font=font("small"))
        # header last so it covers scrolled bubbles
        p = cl.peer(key)
        special = None
        if p["kind"] == "self":
            special = "saved"
        self.header(g, w, cl.peer_name(key), cl.status_text(key), key, special,
                    cl.is_online(key))
        self.toast(g, w, h)

    def paint_msg(self, g, w, y, m, lay, sel):
        if lay["service"]:
            bw = lay["w"]
            x1 = (w - bw) / 2
            bg = 0x8FA9BE
            if sel:
                bg = BLUE
            rrect(g, x1, y + 2, x1 + bw, y + 2 + lay["h"], 9, bg)
            ly = y + 17
            for l in lay["lines"]:
                g.text(((w - width(g, l, "small")) / 2, ly), l, fill=WHITE, font=font("small"))
                ly = ly + 15
            return
        bw = lay["w"]
        bh = lay["h"]
        if lay.get("sticker") is not None:
            self.paint_sticker(g, w, y, m, lay, sel)
            return
        bg = "w"
        if m["out"]:
            x1 = w - 8 - bw
            fill = BUBBLE_OUT
            bg = "o"
        else:
            x1 = 8
            fill = BUBBLE_IN
        x2 = x1 + bw
        y1 = y + 2
        y2 = y1 + bh
        if sel:
            rrect(g, x1 - 2, y1 - 2, x2 + 2, y2 + 2, 12, BLUE)
        # tail
        if m["out"]:
            g.polygon([(x2 - 6, y2 - 10), (x2 + 5, y2), (x2 - 8, y2)], fill=fill)
        else:
            g.polygon([(x1 + 6, y2 - 10), (x1 - 5, y2), (x1 + 8, y2)], fill=fill)
        rrect(g, x1, y1, x2, y2, 10, fill)
        P = self.PAD
        ty = y1 + P
        for kind, l in lay["head"]:
            if kind == "name":
                txt(g, x1 + P, ty + 11, l, colour_for(m.get("from_key") or "u0", NAME_COLOURS),
                    "smallb", bg)
                ty = ty + 15
            elif kind == "fwd":
                txt(g, x1 + P, ty + 11, l, BLUE, "small", bg)
                ty = ty + 15
            else:
                qc = BLUE
                if m["out"]:
                    qc = TIME_OUT
                g.rectangle((x1 + P, ty + 2, x1 + P + 2, ty + 31), fill=qc)
                txt(g, x1 + P + 7, ty + 13, l[0], qc, "smallb", bg)
                txt(g, x1 + P + 7, ty + 28, l[1], GREY, "small", bg)
                ty = ty + 34
        if lay.get("photo"):
            pw, ph = lay["photo"]
            if lay["head"]:
                self.paint_photo(g, x1 + 3, ty, pw, ph, m["photo"])
                ty = ty + ph + 4
            else:
                self.paint_photo(g, x1 + 3, ty - P + 3, pw, ph, m["photo"])
                ty = ty - P + 3 + ph + 4
        for kind, l in lay["body"]:
            colour = TEXT
            if kind == "media":
                colour = BLUE_DARK
                if m["out"]:
                    colour = 0x3A8E3B
            txt(g, x1 + P, ty + 14, l, colour, "text", bg)
            ty = ty + 18
        mc = TIME_IN
        if m["out"]:
            mc = TIME_OUT
        mx = x2 - P - lay["mw"]
        my = y2 - 6
        g.text((mx, my), lay["meta"], fill=mc, font=font("small"))
        if m["out"]:
            read = m["id"] <= self.app.read_out(self.key_)
            tick(g, x2 - P - 13, my - 9, mc, read)


# ---------------------------------------------------------------- photos


def _photo_methods():
    def paint_photo(self, g, x, y, pw, ph, info):
        img = self.app.media.image(info, pw, ph)
        if img is not None:
            g.blit(img, target=(x, y))
        else:
            g.rectangle((x, y, x + pw, y + ph), fill=0xB8C7D3)
            t = u"Photo"
            if info.get("badge"):
                t = u""
            g.text((x + (pw - width(g, t, "small")) / 2, y + ph / 2 + 4), t, fill=WHITE,
                   font=font("small"))
        b = info.get("badge")
        if b:
            b = fit(g, b, "small", pw - 16)
            bw = width(g, b, "small") + 10
            rrect(g, x + 4, y + 4, x + 4 + bw, y + 21, 8, 0x404850)
            g.text((x + 9, y + 17), b, fill=WHITE, font=font("small"))

    def paint_sticker(self, g, w, y, m, lay, sel):
        if m["out"]:
            x = w - 12 - 44
        else:
            x = 12
        if sel:
            rrect(g, x - 4, y, x + 48, y + 48, 10, BLUE_SOFT)
        if not big_emoji(g, x + 2, y + 4, lay["sticker"]):
            g.text((x, y + 30), u"Sticker", fill=GREY, font=font("small"))
        meta = lay["meta"]
        mw = lay["mw"]
        rrect(g, x + 46 - mw, y + 48, x + 46, y + 63, 7, 0x8FA9BE)
        g.text((x + 52 - mw, y + 60), meta, fill=WHITE, font=font("small"))

    ChatView.paint_photo = paint_photo
    ChatView.paint_sticker = paint_sticker


_photo_methods()


class Media:
    """Pictures in chats: the tiny preview Telegram sends inside the message
    is decoded at once (blurry), the real ~320 px picture is downloaded in the
    background (one at a time) and kept on the memory card."""
    LIMIT = 10

    def __init__(self, app, folder):
        self.app = app
        self.folder = folder
        self.mem = {}           # (id, w, h) -> (Image, quality)
        self.order = []
        self.jobs = []
        self.queued = {}
        self.running = 0
        self.downloading = 0
        self.failed = {}

    def path(self, info):
        return self.folder + info["id"] + ".jpg"

    def image(self, info, w, h):
        k = (info["id"], w, h)
        e = self.mem.get(k)
        if e is None or e[1] < 2:
            if not self.queued.has_key(k):
                self.queued[k] = 1
                if e is None and info.get("stripped"):
                    self.jobs.insert(0, ("strip", info, w, h))
                if not self.failed.has_key(info["id"]):
                    self.jobs.append(("full", info, w, h))
                self.kick()
        if e is None:
            return None
        return e[0]

    def kick(self):
        if not self.running:
            self.running = 1
            self.app.net.later(0.05, self.work)

    def store(self, k, img, q):
        self.mem[k] = (img, q)
        if k in self.order:
            self.order.remove(k)
        self.order.append(k)
        while len(self.order) > self.LIMIT:
            old = self.order.pop(0)
            if self.mem.has_key(old):
                del self.mem[old]
            if self.queued.has_key(old):
                del self.queued[old]
        self.app.redraw_soon()

    def work(self):
        self.running = 0
        if not self.jobs or self.downloading:
            return
        kind, info, w, h = self.jobs.pop(0)
        k = (info["id"], w, h)
        try:
            if kind == "strip":
                import tgclient
                jpg = tgclient.stripped_to_jpeg(info["stripped"])
                if jpg:
                    tmp = self.folder + "strip.jpg"
                    f = open(tmp, "wb")
                    f.write(jpg)
                    f.close()
                    self.store(k, graphics.Image.open(tmp).resize((w, h)), 1)
            else:
                p = self.path(info)
                import os
                if os.path.exists(p):
                    self.store(k, graphics.Image.open(p).resize((w, h)), 2)
                elif self.app.auto_photos():
                    self.downloading = 1
                    self.app.client.download(
                        info, p, lambda path, self=self, info=info, w=w, h=h: self.done(info, w, h),
                        lambda e, self=self, info=info: self.fail(info, e))
                    return
                else:
                    if self.queued.has_key(k):
                        del self.queued[k]
        except:
            import sys
            self.app.log("media: " + str(sys.exc_info()[1]))
        self.kick()

    def done(self, info, w, h):
        self.downloading = 0
        try:
            self.store((info["id"], w, h), graphics.Image.open(self.path(info)).resize((w, h)), 2)
        except:
            import sys
            self.app.log("media open: " + str(sys.exc_info()[1]))
        self.kick()

    def fail(self, info, e):
        self.downloading = 0
        self.failed[info["id"]] = 1
        self.app.log("download failed: " + str(e))
        self.kick()

    def drop_jobs(self):
        """Leaving a chat: forget pending work for pictures no longer shown."""
        self.jobs = []
        self.queued = {}


class PhotoView(CanvasView):
    def __init__(self, app, info):
        CanvasView.__init__(self, app)
        self.info = info
        self.img = None

    def key(self, k):
        if k in ("select", "5", "left", "right"):
            self.app.back_to_chat()

    def paint(self, g, w, h):
        g.clear(0x101418)
        if self.img is None:
            import os
            p = self.app.media.path(self.info)
            try:
                if os.path.exists(p):
                    self.img = graphics.Image.open(p).resize((w, h), keepaspect=1)
            except:
                self.img = None
        if self.img is not None:
            iw, ih = self.img.size
            g.blit(self.img, target=((w - iw) / 2, (h - ih) / 2))
        else:
            t = u"Downloading picture..."
            g.text(((w - width(g, t, "text")) / 2, h / 2), t, fill=WHITE, font=font("text"))


# ---------------------------------------------------------------- welcome

class WelcomeView(CanvasView):
    def __init__(self, app, lines):
        CanvasView.__init__(self, app)
        self.lines = lines

    def key(self, k):
        if k == "select" or k == "5":
            self.app.login_phone()

    def paint(self, g, w, h):
        g.clear(WHITE)
        cx = w / 2
        r = 36
        top = max((h - 250) / 2, 8)
        g.ellipse((cx - r, top, cx + r, top + 2 * r), fill=0x2AABEE)
        plane(g, cx - 2, top + r, 38, WHITE)
        t = u"RetroTele"
        y = top + 2 * r + 38
        g.text((cx - width(g, t, "big") / 2, y), t, fill=TEXT, font=font("big"))
        y = y + 26
        for l in self.lines:
            for ll in wrap(g, l, "text", w - 30, 3):
                if y > h - 64:
                    break
                g.text((cx - width(g, ll, "text") / 2, y), ll, fill=GREY, font=font("text"))
                y = y + 19
        if self.app.busy:
            b = self.app.busy
            g.text((cx - width(g, b, "small") / 2, h - 50), b, fill=BLUE, font=font("small"))
        lbl = u"Start messaging"
        bw = width(g, lbl, "name") + 40
        rrect(g, cx - bw / 2, h - 40, cx + bw / 2, h - 8, 16, BLUE)
        g.text((cx - width(g, lbl, "name") / 2, h - 19), lbl, fill=WHITE, font=font("name"))
