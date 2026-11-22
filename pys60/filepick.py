# Simple file browser for "Attach file" (Python 2.2 / PyS60 1.4.5).
# Starts at the drive list; folders first, then files with their size.

import os
import appuifw
import e32

import fileinfo

SEP = "\\"
HIDDEN = ["sys", "private", "resource"]


def drives():
    try:
        return e32.drive_list()
    except:
        return [u"C:", u"E:"]


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
    if i <= 2 and p[1:2] == ":":
        return p[:i + 1]
    return p[:i + 1]


def join(path, name):
    if path[-1:] == SEP:
        return path + name
    return path + SEP + name


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


class FilePicker:
    """app: the RetroTele App (for title/menu restore); start: folder or u'';
    on_pick(path), on_cancel(), on_dir(path) (remember the folder)."""

    def __init__(self, start, on_pick, on_cancel, on_dir=None):
        self.path = u""
        self.on_pick = on_pick
        self.on_cancel = on_cancel
        self.on_dir = on_dir
        self.rows = []       # parallel to the list: ("up"|"dir"|"drive"|"file", name)
        self.box = None
        if start and self.can_list(start):
            self.path = start

    def can_list(self, path):
        try:
            os.listdir(path)
            return 1
        except:
            return 0

    def show(self):
        self.refresh(0)
        appuifw.app.exit_key_handler = self.back

    def build(self):
        items = []
        self.rows = []
        if self.path == u"":
            for d in drives():
                items.append((u"Drive " + d, u"Memory"))
                self.rows.append(("drive", d + SEP))
            return items
        items.append((u"..", u"Up"))
        self.rows.append(("up", u""))
        try:
            dirs, files = list_dir(self.path)
        except:
            appuifw.note(u"Cannot open this folder.", "error")
            self.path = parent(self.path)
            if self.path == u"":
                return self.build()
            return self.build()
        for n in dirs:
            items.append((n, u"Folder"))
            self.rows.append(("dir", n))
        for n, size in files:
            items.append((n, fileinfo.human_size(size)))
            self.rows.append(("file", n))
        return items

    def refresh(self, cur):
        items = self.build()
        if self.on_dir is not None and self.path:
            self.on_dir(self.path)
        title = self.path
        if not title:
            title = u"Attach file"
        if len(title) > 28:
            title = u"..." + title[-25:]
        appuifw.app.title = title
        appuifw.app.menu = [(u"Open", self.opened), (u"Cancel", self.on_cancel)]
        if self.box is None:
            self.box = appuifw.Listbox(items, self.opened)
            appuifw.app.body = self.box
        else:
            self.box.set_list(items, cur)
            appuifw.app.body = self.box

    def opened(self):
        i = self.box.current()
        if i < 0 or i >= len(self.rows):
            return
        kind, name = self.rows[i]
        if kind == "up":
            self.back()
        elif kind == "drive":
            self.enter(name)
        elif kind == "dir":
            self.enter(join(self.path, name))
        else:
            self.on_pick(join(self.path, name))

    def enter(self, path):
        if not self.can_list(path):
            appuifw.note(u"Cannot open this folder.", "error")
            return
        self.path = path
        self.refresh(0)

    def back(self):
        if self.path == u"":
            self.on_cancel()
            return
        old = self.path
        self.path = parent(self.path)
        self.refresh(0)
