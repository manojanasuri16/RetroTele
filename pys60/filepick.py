# File manager for "Attach file" (Python 2.2 / PyS60 1.4.5).
# A canvas screen in the chat-list style: drive list, folders first, then files.

import os
import time
import e32

import fileinfo

SEP = "\\"
HIDDEN = ["sys", "private", "resource"]
CACHE_MAX = 200
SORTS = ["name", "size", "date"]


def drives():
    try:
        return e32.drive_list()
    except:
        return [u"C:", u"E:"]


def drive_path(d):
    return d + SEP


def is_root(path):
    """True for a drive root such as E:\\ ."""
    return len(path) == 3 and path[1:2] == ":"


def parent(path):
    """Parent folder of path; the drive list is u''."""
    if is_root(path):
        return u""
    p = path
    if p[-1:] == SEP:
        p = p[:-1]
    i = p.rfind(SEP)
    if i < 0:
        return u""
    return p[:i + 1]


def join(path, name):
    if path[-1:] == SEP:
        return path + name
    return path + SEP + name


def folder(path):
    """path with one trailing separator."""
    if path[-1:] == SEP:
        return path
    return path + SEP


def strip(path):
    if path[-1:] == SEP and not is_root(path):
        return path[:-1]
    return path


def list_dir(path):
    """Returns (dirs, files): sorted name lists, files as (name, size)."""
    names = os.listdir(path)
    dirs = []
    files = []
    root = is_root(path)
    for n in names:
        if root and n.lower() in HIDDEN:
            continue
        full = join(path, n)
        try:
            if os.path.isdir(full):
                dirs.append((n.lower(), n))
            else:
                files.append((n.lower(), n, int(os.path.getsize(full))))
        except:
            pass
    dirs.sort()
    files.sort()
    out_d = []
    for k, n in dirs:
        out_d.append(n)
    out_f = []
    for k, n, size in files:
        out_f.append((n, size))
    return out_d, out_f


DRIVE_NAMES = {u"C:": u"Phone memory", u"D:": u"RAM drive", u"E:": u"Memory card"}


def drive_label(d):
    d = d.upper()
    if DRIVE_NAMES.has_key(d):
        return DRIVE_NAMES[d]
    return u"Drive " + d


def free_space():
    """{u'C:': bytes free} when sysinfo can tell, else {}."""
    try:
        import sysinfo
        r = sysinfo.free_drivespace()
        out = {}
        for k in r.keys():
            out[unicode(k).upper()] = r[k]
        return out
    except:
        return {}


def type_colour(name):
    if fileinfo.is_image(name):
        return 0x3FAE4E
    if fileinfo.is_audio(name):
        return 0x8E59D8
    if fileinfo.is_video(name):
        return 0xE5464B
    e = fileinfo.ext_of(name)
    if e in ("zip", "rar", "7z", "gz", "tar", "sis", "sisx", "jar"):
        return 0xE08A14
    if e in ("txt", "doc", "docx", "pdf", "rtf", "xls", "ppt", "odt", "log", "csv"):
        return 0x2E86D6
    return 0x9AA3AA


def fmt_date(t):
    try:
        lt = time.localtime(t)
        return u"%02d.%02d.%02d %02d:%02d" % (lt[2], lt[1], lt[0] % 100, lt[3], lt[4])
    except:
        return u""


THUMB_EXT = ["jpg", "jpeg", "png", "gif", "bmp"]
THUMB_MAX = 40
THUMB_BIG = 1536 * 1024
THUMB_SIZE = 28


def temp_dir():
    for d in [u"D:\\", u"C:\\Data\\", u"E:\\"]:
        try:
            if os.path.isdir(d):
                return d
        except:
            pass
    return u""


def load_thumb(path, name, size):
    """A small Image for an image file, or None (never raises)."""
    import graphics
    ext = fileinfo.ext_of(name)
    tmp = temp_dir() + u"rt_thumb.jpg"
    img = None
    if ext in ("jpg", "jpeg"):
        data = fileinfo.exif_thumb(path)
        if data:
            try:
                f = open(tmp, "wb")
                f.write(data)
                f.close()
                img = graphics.Image.open(tmp)
            except:
                img = None
            try:
                os.remove(tmp)
            except:
                pass
    if img is None:
        if size > THUMB_BIG:
            return None
        img = graphics.Image.open(path)
    return img.resize((THUMB_SIZE, THUMB_SIZE), keepaspect=1)


_CLS = []


def make_view(*a):
    if _CLS:
        return _CLS[0](*a)
    import tgui

    class FilePickView(tgui.CanvasView):
        HEADER_H = 50
        ROW_H = 40
        FOOT_H = 24

        def __init__(self, app, start, on_pick, on_cancel, on_dir=None):
            tgui.CanvasView.__init__(self, app)
            self.on_pick = on_pick
            self.on_cancel = on_cancel
            self.on_dir = on_dir
            self.path = u""
            self.entries = []     # (kind, name, full)
            self.cur = 0
            self.top = 0
            self.sort = 0
            self.msg = u""
            self.cache = {}
            self.free = {}
            self.marks = {}       # full path -> 1, kept across folders
            self.thumbs = {}      # path -> Image
            self.thumb_order = []
            self.thumb_fail = {}
            self.gen = 0
            self.tpending = 0
            self.vis = (0, 0)
            if start and self.can_list(start):
                self.path = folder(start)
            self.load(u"")

        # ------------------------------------------------ data
        def can_list(self, path):
            try:
                os.listdir(path)
                return 1
            except:
                return 0

        def load(self, select):
            """Fill entries for self.path; select = full path to highlight."""
            ents = []
            self.gen = self.gen + 1
            self.thumb_fail = {}
            if self.path == u"":
                self.free = free_space()
                for d in drives():
                    d = unicode(d)
                    if d.upper() == u"Z:":
                        continue
                    ents.append(("drive", d, drive_path(d)))
            else:
                try:
                    names = os.listdir(self.path)
                except:
                    return 0
                dirs = []
                files = []
                root = is_root(self.path)
                for n in names:
                    n = tgui.to_u(n)
                    if root and n.lower() in HIDDEN:
                        continue
                    full = join(self.path, n)
                    try:
                        isd = os.path.isdir(full)
                    except:
                        continue
                    if isd:
                        dirs.append((n.lower(), n, folder(full)))
                    else:
                        files.append((n.lower(), n, full))
                dirs.sort()
                keyed = files
                if self.sort > 0:
                    keyed = []
                    for k, n, full in files:
                        size, mt = self.stat(full, 0)
                        if self.sort == 1:
                            keyed.append((-size, k, n, full))
                        else:
                            keyed.append((-mt, k, n, full))
                    keyed.sort()
                    files = []
                    for a, k, n, full in keyed:
                        files.append((k, n, full))
                else:
                    files.sort()
                for k, n, full in dirs:
                    ents.append(("dir", n, full))
                for k, n, full in files:
                    ents.append(("file", n, full))
            self.entries = ents
            self.cur = 0
            self.top = 0
            if select:
                s = strip(select)
                i = 0
                for kind, n, full in ents:
                    if strip(full) == s:
                        self.cur = i
                        break
                    i = i + 1
            return 1

        def stat(self, full, cache=1):
            """(size, mtime) of a file; cached by path."""
            if self.cache.has_key(full):
                return self.cache[full]
            try:
                st = os.stat(full)
                r = (int(st[6]), int(st[8]))
            except:
                r = (0, 0)
            if cache:
                if len(self.cache) >= CACHE_MAX:
                    self.cache = {}
                self.cache[full] = r
            return r

        # ------------------------------------------------ navigation
        def show(self):
            import appuifw
            tgui.CanvasView.show(self)
            self.set_menu()
            appuifw.app.exit_key_handler = self.up

        def set_menu(self):
            import appuifw
            appuifw.app.menu = [
                (u"Open / mark", self.open_cur),
                (u"Send marked (%d)" % len(self.marks), self.send),
                (u"Mark all files here", self.mark_all),
                (u"Unmark all", self.unmark_all),
                (u"Up", self.up),
                (u"Go to memory card", lambda self=self: self.goto([u"E:" + SEP])),
                (u"Go to phone memory", lambda self=self: self.goto(
                    [u"C:" + SEP + u"Data" + SEP])),
                (u"Go to Images", lambda self=self: self.goto([
                    u"E:" + SEP + u"Images" + SEP, u"C:" + SEP + u"Data" + SEP + u"Images" + SEP])),
                (u"Go to Videos", lambda self=self: self.goto([
                    u"E:" + SEP + u"Videos" + SEP, u"C:" + SEP + u"Data" + SEP + u"Videos" + SEP])),
                (u"Go to Music/Sounds", lambda self=self: self.goto([
                    u"E:" + SEP + u"Music" + SEP, u"E:" + SEP + u"Sounds" + SEP,
                    u"C:" + SEP + u"Data" + SEP + u"Sounds" + SEP])),
                (u"Sort by name/size/date", self.cycle_sort),
                (u"Cancel", self.cancel)]

        def mark_all(self):
            for kind, n, full in self.entries:
                if kind == "file":
                    self.marks[full] = 1
            self.set_menu()
            self.draw()

        def unmark_all(self):
            self.marks = {}
            self.set_menu()
            self.draw()

        def send(self):
            paths = []
            if self.marks:
                keys = self.marks.keys()
                keys.sort()
                paths = keys
            elif 0 <= self.cur < len(self.entries) and self.entries[self.cur][0] == "file":
                paths = [self.entries[self.cur][2]]
            if not paths:
                self.toast_msg(u"Select a file first")
                return
            self.on_pick(paths)

        def toast_msg(self, t):
            self.msg = t
            self.draw()

        def enter(self, path, select=u""):
            old = (self.path, self.entries, self.cur, self.top)
            self.path = path
            self.msg = u""
            if not self.load(select):
                self.path, self.entries, self.cur, self.top = old
                self.toast_msg(u"Cannot open this folder")
                return 0
            if self.on_dir is not None and self.path:
                self.on_dir(self.path)
            self.draw()
            return 1

        def goto(self, paths):
            for p in paths:
                try:
                    ok = os.path.isdir(p)
                except:
                    ok = 0
                if ok:
                    self.enter(p)
                    return
            self.toast_msg(u"Folder not found")

        def up(self):
            if self.path == u"":
                self.cancel()
                return
            old = self.path
            self.enter(parent(self.path), old)

        def cancel(self):
            self.on_cancel()

        def cycle_sort(self):
            self.sort = (self.sort + 1) % 3
            sel = u""
            if 0 <= self.cur < len(self.entries):
                sel = self.entries[self.cur][2]
            if self.path != u"":
                self.load(sel)
            self.toast_msg(u"Sort by " + unicode(SORTS[self.sort]))

        def open_cur(self):
            if not (0 <= self.cur < len(self.entries)):
                return
            kind, name, full = self.entries[self.cur]
            if kind == "file":
                if self.marks.has_key(full):
                    del self.marks[full]
                else:
                    self.marks[full] = 1
                self.set_menu()
                self.draw()
            else:
                self.enter(full)

        def key(self, k):
            n = len(self.entries)
            self.msg = u""
            if k == "up" or k == "2":
                if self.cur > 0:
                    self.cur = self.cur - 1
                elif n:
                    self.cur = n - 1
            elif k == "down" or k == "8":
                if self.cur < n - 1:
                    self.cur = self.cur + 1
                else:
                    self.cur = 0
            elif k == "0":
                return self.send()
            elif k == "select" or k == "5":
                return self.open_cur()
            elif k == "right" or k == "6":
                if 0 <= self.cur < n and self.entries[self.cur][0] != "file":
                    return self.open_cur()
            elif k == "left" or k == "4":
                return self.up()
            self.draw()

        # ------------------------------------------------ drawing
        def title(self):
            if self.path == u"":
                return u"Attach file"
            p = tgui.to_u(strip(self.path))
            if is_root(self.path):
                return drive_label(self.path[:2])
            return p[p.rfind(SEP) + 1:]

        def paint(self, g, w, h):
            T = tgui
            g.clear(T.WHITE)
            H = self.HEADER_H
            g.rectangle((0, 0, w, H), fill=T.BLUE)
            T.txt(g, 10, 22, T.fit(g, self.title(), "name", w - 20), T.WHITE, "name", "b")
            path = T.to_u(self.path)
            if self.marks:
                path = u"%d selected" % len(self.marks)
            if path == u"":
                path = u"Choose a drive"
            while not self.marks and len(path) > 4 and T.width(g, path, "small") > w - 20:
                path = u"..." + path[4:]
            T.txt(g, 10, 41, path, T.HEADER_SUB, "small", "b")
            top = H
            bottom = h - self.FOOT_H
            RH = self.ROW_H
            rows = self.entries
            visible = max((bottom - top) / RH, 1)
            if self.cur >= len(rows):
                self.cur = max(len(rows) - 1, 0)
            if self.cur < self.top:
                self.top = self.cur
            if self.cur >= self.top + visible:
                self.top = self.cur - visible + 1
            if not rows:
                m = u"Empty folder"
                g.text(((w - T.width(g, m, "text")) / 2, top + 50), m, fill=T.GREY,
                       font=T.font("text"))
            y = top
            i = self.top
            while i < len(rows) and y + RH <= bottom + 1:
                self.paint_row(g, w, y, rows[i], i == self.cur)
                y = y + RH
                i = i + 1
            self.scrollbar(g, w, top, bottom, self.top, visible, len(rows))
            # footer
            g.rectangle((0, bottom, w, h), fill=T.BLUE_SOFT)
            hints = [(u"Open", 6), (u"Up", 58), (u"0: Send %d" % len(self.marks), None),
                     (u"Back", -6)]
            for label, x in hints:
                tw = T.width(g, label, "small")
                if x is None:
                    x = (w - tw) / 2 + 28
                elif x < 0:
                    x = w + x - tw
                T.txt(g, x, h - 8, label, T.BLUE_DARK, "small", "w")
            self.vis = (self.top, self.top + visible)
            self.want_thumbs()
            if self.msg:
                y0 = H + 4
                T.rrect(g, 6, y0, w - 6, y0 + 26, 8, 0x25303A)
                T.txt(g, 14, y0 + 18, T.fit(g, self.msg, "smallb", w - 28), T.WHITE,
                      "smallb", "t")

        def paint_row(self, g, w, y, ent, sel):
            T = tgui
            kind, name, full = ent
            RH = self.ROW_H
            if sel:
                g.rectangle((0, y, w, y + RH), fill=T.BLUE)
                c1 = T.WHITE
                c2 = T.WHITE
                bg = "b"
            else:
                c1 = T.TEXT
                c2 = T.GREY
                bg = "w"
            if kind == "file":
                sub = u""
                size, mt = self.stat(full)
                sub = fileinfo.human_size(size)
                d = fmt_date(mt)
                if d:
                    sub = sub + u", " + d
                th = self.thumbs.get(full)
                if th is not None:
                    self.icon_thumb(g, 8, y + 6, th)
                else:
                    self.icon_file(g, 10, y + 7, name, sel)
                if self.marks.has_key(full):
                    self.icon_mark(g, 8, y + 6)
            elif kind == "dir":
                sub = u"Folder"
                self.icon_folder(g, 8, y + 9)
            else:
                d = name.upper()
                sub = drive_label(d)
                if self.free.has_key(d):
                    sub = sub + u" " + fileinfo.human_size(self.free[d]) + u" free"
                self.icon_drive(g, 8, y + 9, sel)
                name = d
            x = 44
            T.txt(g, x, y + 17, T.fit(g, name, "name", w - x - 10), c1, "name", bg)
            T.txt(g, x, y + 34, T.fit(g, sub, "small", w - x - 10), c2, "small", bg)
            if not sel:
                g.line((x, y + RH - 1, w, y + RH - 1), outline=T.LINE)

        def icon_folder(self, g, x, y):
            g.rectangle((x, y, x + 12, y + 5), fill=0xE0A21B)
            g.rectangle((x, y + 3, x + 26, y + 22), fill=0xF5B83D)
            g.rectangle((x, y + 8, x + 26, y + 22), fill=0xFFCB57)

        def icon_thumb(self, g, x, y, img):
            g.rectangle((x, y, x + 28, y + 28), fill=0xDCE3EA)
            try:
                iw, ih = img.size
                g.blit(img, target=(x + (28 - iw) / 2, y + (28 - ih) / 2))
            except:
                pass

        def icon_mark(self, g, x, y):
            g.ellipse((x + 12, y + 14, x + 30, y + 32), fill=0x4DCD5E, outline=0xFFFFFF)
            g.line((x + 16, y + 23, x + 20, y + 27), outline=0xFFFFFF, width=2)
            g.line((x + 20, y + 27, x + 26, y + 19), outline=0xFFFFFF, width=2)

        # ------------------------------------------------ thumbnails
        def thumb_ok(self, ent):
            kind, name, full = ent
            if kind != "file" or self.thumbs.has_key(full) or self.thumb_fail.has_key(full):
                return 0
            return fileinfo.ext_of(name) in THUMB_EXT

        def want_thumbs(self):
            if self.tpending:
                return
            i = self.vis[0]
            while i < self.vis[1] and i < len(self.entries):
                if self.thumb_ok(self.entries[i]):
                    self.tpending = 1
                    self.app.net.later(0.05, self.thumb_tick)
                    return
                i = i + 1

        def thumb_tick(self):
            self.tpending = 0
            if self.app.view is not self:
                return
            gen = self.gen
            i = self.vis[0]
            while i < self.vis[1] and i < len(self.entries):
                ent = self.entries[i]
                if self.thumb_ok(ent):
                    img = None
                    try:
                        img = load_thumb(ent[2], ent[1], self.stat(ent[2])[0])
                    except:
                        img = None
                    if gen != self.gen:
                        return
                    if img is None:
                        self.thumb_fail[ent[2]] = 1
                    else:
                        self.thumbs[ent[2]] = img
                        self.thumb_order.append(ent[2])
                        while len(self.thumb_order) > THUMB_MAX:
                            old = self.thumb_order[0]
                            del self.thumb_order[0]
                            if self.thumbs.has_key(old):
                                del self.thumbs[old]
                    self.draw()
                    return
                i = i + 1

        def icon_drive(self, g, x, y, sel):
            c = 0x9AA3AA
            if sel:
                c = 0xD6E8FB
            g.rectangle((x, y + 4, x + 26, y + 20), fill=c)
            g.rectangle((x + 3, y + 14, x + 23, y + 17), fill=0x5E666C)
            g.rectangle((x + 20, y + 8, x + 22, y + 10), fill=0x4DCD5E)

        def icon_file(self, g, x, y, name, sel):
            fill = 0xDCE3EA
            g.polygon([(x, y), (x + 14, y), (x + 20, y + 6), (x + 20, y + 26), (x, y + 26)],
                      fill=fill, outline=0x8D969C)
            g.polygon([(x + 14, y), (x + 14, y + 6), (x + 20, y + 6)], fill=0xC4C9CC)
            g.rectangle((x + 3, y + 15, x + 17, y + 22), fill=type_colour(name))
            g.rectangle((x + 4, y + 10, x + 12, y + 11), fill=0xC4C9CC)

    _CLS.append(FilePickView)
    return FilePickView(*a)


def FilePickView(app, start, on_pick, on_cancel, on_dir=None):
    return make_view(app, start, on_pick, on_cancel, on_dir)
