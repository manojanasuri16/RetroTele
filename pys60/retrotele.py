# RetroTele: a small Telegram client for Python for S60 1.4.5 (Nokia N79 and
# other S60 3rd Edition phones). Talks MTProto 2.0 directly to Telegram's
# servers, no PC or proxy needed: chats, folders, contacts, read and write.
#
# Written for Python 2.2: no enumerate/sorted/sets/generators, no
# conditional expressions, no "with", no "except X as e", and substring
# tests use find(). The file also parses as Python 3 so it can be checked on
# a PC (tools/check_py22.py).

import sys
import appuifw
import e32

VERSION = u"0.19.3"  # single source of truth: build_sis.sh reads this
APP = u"RetroTele"

_LOGFILE = None
for _d in ["E:\\", "C:\\Data\\", "C:\\"]:
    try:
        _name = _d + "retrotele_log.txt"
        _mode = "a"
        try:
            import os as _os
            if _os.path.getsize(_name) > 60000:
                _mode = "w"
        except:
            pass
        _LOGFILE = open(_name, _mode)
        break
    except:
        pass


def boot_log(msg):
    if _LOGFILE is not None:
        try:
            try:
                import time as _t
                msg = _t.strftime("%H:%M:%S ") + msg
            except:
                pass
            _LOGFILE.write(msg + "\n")
            _LOGFILE.flush()
        except:
            pass


def show_crash(where):
    try:
        import traceback
        text = "".join(traceback.format_exception(sys.exc_info()[0], sys.exc_info()[1],
                                                  sys.exc_info()[2]))
    except:
        text = str(sys.exc_info()[1])
    boot_log("CRASH in " + where + ":\n" + text)
    try:
        appuifw.note(unicode("RetroTele error (" + where + "): " + str(sys.exc_info()[1]),
                             "latin-1"), "error")
        appuifw.query(u"Error details (also in retrotele_log.txt)", "text",
                      unicode(text, "latin-1"))
    except:
        pass


boot_log("")
boot_log("========== RetroTele started, python " + sys.version.split(" ")[0])

import os
import time
import types
import socket
import calendar

import tgcrypto
import tl
import tgclient
import tgsrp
import tgui
import fileinfo
import filepick
from mtproto import RpcError

UID = "e7a3d5c2"


def err_text():
    try:
        return unicode(str(sys.exc_info()[1]), "utf-8", "replace")
    except:
        return u"error"


def to_u(s):
    if type(s) is types.UnicodeType:
        return s
    if s is None:
        return u""
    try:
        return unicode(s, "utf-8")
    except:
        return unicode(s, "latin-1")


def to_b(s):
    if type(s) is types.UnicodeType:
        return s.encode("utf-8")
    return str(s)


def one_line(s, n=80):
    s = to_u(s).replace(u"\r", u" ").replace(u"\n", u" ").replace(u"\t", u" ")
    if len(s) > n:
        s = s[:n - 1] + u"\u2026"
    return s


def find_dir(name):
    for d in ["E:\\", "C:\\Data\\", "C:\\"]:
        if os.path.isdir(d):
            p = d + name + "\\"
            try:
                if not os.path.isdir(p):
                    os.mkdir(p)
                return p
            except:
                pass
    return ""


def find_schema():
    cands = []
    for drive in ["C", "E"]:
        cands.append(drive + ":\\private\\" + UID + "\\schema.txt")
    try:
        cands.append(os.path.join(os.path.dirname(__file__), "schema.txt"))
    except:
        pass
    cands.append("schema.txt")
    for c in cands:
        if os.path.exists(c):
            return c
    raise IOError("schema.txt not found")


ERRORS = {
    "REACTION_INVALID": u"This chat does not allow that reaction.",
    "FILE_PARTS_INVALID": u"The file could not be split for upload. Try again.",
    "FILE_PART_INVALID": u"Telegram rejected a part of the file. Try again.",
    "FILE_PART_TOO_BIG": u"Telegram rejected a part of the file as too big.",
    "FILE_PART_EMPTY": u"Telegram received an empty part of the file.",
    "FILE_PART_SIZE_INVALID": u"Telegram rejected the upload part size.",
    "FILE_PART_SIZE_CHANGED": u"The file changed while uploading. Try again.",
    "FILE_PART_LENGTH_INVALID": u"Telegram rejected the upload part length.",
    "FILE_EMPTY": u"The file is empty.",
    "FILE_TOO_BIG": u"The file is too big (2000 MB at most).",
    "PHOTO_INVALID_DIMENSIONS": u"This picture has unsupported dimensions.",
    "PHOTO_SAVE_FILE_INVALID": u"Telegram could not use this picture.",
    "PHOTO_EXT_INVALID": u"This picture type is not supported.",
    "IMAGE_PROCESS_FAILED": u"Telegram could not process this picture.",
    "MEDIA_EMPTY": u"Telegram says the file is empty.",
    "MEDIA_INVALID": u"Telegram does not accept this file.",
    "MEDIA_CAPTION_TOO_LONG": u"The caption is too long.",
    "CHAT_SEND_MEDIA_FORBIDDEN": u"You cannot send files in this chat.",
    "CHAT_SEND_DOCS_FORBIDDEN": u"You cannot send files in this chat.",
    "CHAT_SEND_PHOTOS_FORBIDDEN": u"You cannot send photos in this chat.",
    "PHONE_NUMBER_INVALID": u"That phone number is not valid. Use the +country code format.",
    "PHONE_CODE_INVALID": u"Wrong code. Try again.",
    "PHONE_CODE_EXPIRED": u"The code has expired. Ask for a new one.",
    "PASSWORD_HASH_INVALID": u"Wrong two-step verification password.",
    "API_ID_INVALID": u"api_id/api_hash are wrong. Fix them in Options > Settings.",
    "API_ID_PUBLISHED_FLOOD": u"This api_id is blocked. Create your own at my.telegram.org.",
    "PHONE_NUMBER_BANNED": u"This phone number is banned by Telegram.",
    "SIGN_UP_REQUIRED": u"This number has no Telegram account. Sign up in an official app first.",
    "PHONE_NUMBER_UNOCCUPIED": u"This number has no Telegram account. Sign up in an official app first.",
    "PEER_ID_INVALID": u"Telegram does not know this chat (open the chat list again).",
    "CHAT_WRITE_FORBIDDEN": u"You cannot write in this chat.",
    "USERNAME_NOT_OCCUPIED": u"No one has this username.",
    "USERNAME_INVALID": u"That username is not valid.",
}


def err_msg(e):
    if isinstance(e, RpcError):
        m = e.message
        if m[:11] == "FLOOD_WAIT_":
            return u"Telegram asks to wait %s seconds before trying again." % m[11:]
        if ERRORS.has_key(m):
            return ERRORS[m]
        if m[:10] == "FILE_PART_" and m[-8:] == "_MISSING":
            return u"Telegram lost part of the file. Try again."
        if m == "cannot read file":
            return u"Cannot read the file."
        return to_u("%s (%d)" % (m, e.code))
    return to_u(str(e))


def is_err(res):
    return (type(res) is types.TupleType and len(res) == 2 and
            type(res[0]) in (types.ClassType, types.TypeType))


def raw(sock):
    return getattr(sock, "_sock", sock)


# IMPORTANT (PyS60 e32socket, see RetroSend's docs/PYS60-NOTES.md):
# socket.close() also stops the network connection for every socket, so
# sockets are never close()d while the app runs; they get shutdown(2) and
# are then dropped.

class PhoneConn:
    def __init__(self, sock, app):
        self.sock = sock
        self.app = app

    def recv(self, on_data):
        def cb(res, on_data=on_data, app=self.app):
            if is_err(res) or res is None:
                res = ""
            app.safe(on_data, res)
        try:
            if self.sock is None:
                raise IOError("closed")
            self.sock.recv(16384, 0, cb)
        except:
            self.app.net.later(0, lambda on_data=on_data: on_data(""))

    def send(self, data, on_done, on_err):
        state = {"data": data}

        def cb(res, self=self, state=state, on_done=on_done, on_err=on_err):
            if is_err(res):
                self.app.safe(on_err, str(res[1]))
                return
            n = len(state["data"])
            try:
                if type(res) in (types.IntType, types.LongType) and 0 < res < n:
                    n = int(res)
            except:
                pass
            state["data"] = state["data"][n:]
            if state["data"]:
                go()
            else:
                self.app.safe(on_done)

        def go(self=self, state=state, cb=cb, on_err=on_err):
            try:
                if self.sock is None:
                    raise IOError("closed")
                self.sock.send(state["data"], 0, cb)
            except:
                self.app.safe(on_err, str(sys.exc_info()[1]))
        go()

    def close(self):
        s = self.sock
        self.sock = None
        if s is not None:
            try:
                s.shutdown(2)
            except:
                pass

    def hard_close(self):
        """Only when the app exits: really close (also ends pending reads)."""
        s = self.sock
        self.sock = None
        if s is not None:
            try:
                s.close()
            except:
                pass


class PhoneNet:
    """Callback-based sockets and timers on the main thread."""
    def __init__(self, app):
        self.app = app
        self.timers = []
        self.socks = []

    def later(self, seconds, func):
        t = e32.Ao_timer()
        box = [t]

        def fire(self=self, box=box, func=func):
            try:
                self.timers.remove(box[0])
            except:
                pass
            self.app.safe(func)
        self.timers.append(t)
        t.after(seconds, fire)

    def connect(self, host, port, on_ok, on_err):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        except:
            msg = err_text()
            self.later(0, lambda on_err=on_err, msg=msg: on_err(msg))
            return
        self.socks.append(s)
        if len(self.socks) > 8:
            del self.socks[0]

        def cb(res, self=self, s=s, on_ok=on_ok, on_err=on_err):
            if is_err(res):
                self.app.safe(on_err, to_u(str(res[1])))
                return
            self.app.safe(on_ok, PhoneConn(raw(s), self.app))
        try:
            raw(s).connect((host, port), cb)
        except:
            msg = err_text()
            self.later(0, lambda on_err=on_err, msg=msg: on_err(msg))

    def close_all(self):
        """App exit: close every socket so no read is left pending."""
        for s in self.socks:
            try:
                s.close()
            except:
                pass
        self.socks = []

    def cancel_all(self):
        for t in self.timers:
            try:
                t.cancel()
            except:
                pass
        self.timers = []


def local_offset(server_now):
    """Seconds to add to a UTC timestamp to get the phone's wall clock.

    The phone's own clock is the authority: localtime() and gmtime() of the same
    instant differ by exactly the zone offset (+19800 in India), so the chat
    times follow the phone even when time.time() is UTC. time.timezone is the
    fallback (Symbian usually leaves it at 0), and the server time is the last
    resort.
    """
    try:
        t = time.time()
        off = int(round((calendar.timegm(time.localtime(t)) -
                         calendar.timegm(time.gmtime(t))) / 900.0)) * 900
        if off:
            return off
    except:
        pass
    try:
        tz = time.timezone
        if time.daylight and time.localtime(time.time())[8]:
            tz = time.altzone
        if tz:
            return int(round(-tz / 900.0)) * 900
    except:
        pass
    try:
        wall = calendar.timegm(time.localtime(time.time()))
        return int(round((wall - server_now) / 900.0)) * 900
    except:
        return 0


BUILTIN_TABS = [(u"All", "all"), (u"Unread", "unread"), (u"Personal", "personal"),
                (u"Groups", "groups"), (u"Channels", "channels")]


class App:
    def __init__(self):
        self.lock = e32.Ao_lock()
        self.net = PhoneNet(self)
        self.dir = find_dir("RetroTele")
        tgcrypto.load_seed(self.dir + "seed.bin")
        self.cfg = tgclient.Store(self.dir + "settings.txt")
        self.store = tgclient.Store(self.dir + "session.txt")
        self.schema = None
        self.client = None
        self.screen = None          # "welcome", "chats", "chat", "compose", "text"
        self.dialogs = []           # chat list rows (tgclient.dialog_row)
        self.more_dialogs = 0
        self.loading_dialogs = 0
        self.archived = None
        self.filters = []
        self.contacts = None
        self.msgs = {}              # key -> [message] (oldest first)
        self.older = {}             # key -> 1 while older messages may exist
        self.loading_older = 0
        self.drafts = {}
        self.read_outs = {}
        self.rows_cache = {}
        self.chat_key = None
        self.reply_to = 0
        self.upload = None
        self.queue = None
        self.picker = None
        self.is_online = 0
        self.busy = u""
        self.apo = None
        self.tz = local_offset(time.time())   # India: +19800, from the phone's clock
        self.note_mode = None     # None, "voice" or "video": the next pick is a note
        self.clipboard = u""        # last text copied (PyS60 has no system clipboard)
        self.reaction_list = list(self.REACTION_FALLBACK)
        self.hash_job = None
        self.toast_text = None
        self.toast_gen = 0
        self.call_gen = 0
        self.call_timer = 0
        self.call_audio = None
        self.call_video = None
        self.call_show_self = 0    # own picture in calls: hidden until key 7 (kept for this run only)
        self.call_video_sig = None
        self.pending_sig = []
        self.audio_state = ""
        self.call_return = "chats"
        self.redraw_armed = 0
        self.cache_armed = 0
        self.focused = 1           # 0 while RetroTele is in the background
        self.jump_mid = None       # (chat, message id) to scroll to after loading
        self.poll_msg = None       # message whose poll the "poll" screen shows
        self.avatars = tgui.Avatars(self, self.dir + "avatar.jpg")
        mdir = self.dir + "media\\"
        try:
            if not os.path.isdir(mdir):
                os.mkdir(mdir)
        except:
            mdir = self.dir
        self.media = tgui.Media(self, mdir)
        self.chat_view = None
        self.list_view = tgui.ChatListView(self)
        self.view = None

    # ---------------------------------------------------------- helpers

    def safe(self, func, *args):
        try:
            apply(func, args)
        except:
            self.log("error: " + str(sys.exc_info()[1]))
            try:
                import traceback
                boot_log("".join(traceback.format_exception(sys.exc_info()[0],
                                                            sys.exc_info()[1],
                                                            sys.exc_info()[2])))
            except:
                pass

    def log(self, msg):
        boot_log(to_b(msg))

    def status(self, text):
        self.busy = to_u(text)
        self.redraw()
        try:
            e32.ao_yield()
        except:
            pass

    def done_wait(self):
        self.busy = u""
        self.redraw()

    def redraw(self):
        if self.view is not None:
            self.view.draw()

    def redraw_soon(self):
        if self.redraw_armed:
            return
        self.redraw_armed = 1

        def fire(self=self):
            self.redraw_armed = 0
            self.redraw()
        self.net.later(0.3, fire)

    def avatar_ready(self):
        self.redraw_soon()

    def online(self, flag):
        self.is_online = flag
        if flag:
            self.busy = u""
            s = self.client.session()
            self.tz = local_offset(time.time() + s.time_offset)
            self.log("timezone offset %d s" % self.tz)
        self.redraw()

    def now(self):
        if self.client is None:
            return int(time.time())
        return self.client.server_time()
    def hhmm(self, ts):
        if not ts:
            return u""
        return to_u(time.strftime("%H:%M", time.gmtime(ts + self.tz)))

    def show_toast(self, title, text):
        self.toast_text = (one_line(title, 60), one_line(text, 100))
        self.toast_gen = self.toast_gen + 1
        gen = self.toast_gen

        def clear(self=self, gen=gen):
            if self.toast_gen == gen:
                self.toast_text = None
                self.redraw()
        self.net.later(3.5, clear)
        self.redraw()

    def app_focus(self, fg):
        """appuifw.app.focus: 1 = in front, 0 = background. Notifications for new messages
        switch to a system popup while RetroTele is in the background."""
        now = 0
        if fg:
            now = 1
        if now != self.focused:
            # this line in E:\retrotele_log.txt is the proof the handler runs
            boot_log("focus: %d (screen %s, notify %d)" % (
                now, getattr(self, "screen", "?"), self.notify_mode()))
        self.focused = now

    def notify_mode(self):
        """0 off, 1 in-app banner, 2 system popup (Settings > Notifications)."""
        try:
            m = int(self.cfg.get("notify", "1"))
        except:
            m = 1
        if m < 0 or m > 2:
            m = 1
        return m

    def set_screen(self, mode):
        boot_log("screen %s (%s)" % (self.screen, mode))
        try:
            appuifw.app.screen = mode
        except:
            pass

    # ---------------------------------------------------------- cache
    # The chat list, names and folders are kept in cache.bin so the app
    # shows your chats instantly at start, then refreshes them.

    def load_cache(self):
        try:
            import marshal
            f = open(self.dir + "cache.bin", "rb")
            d = marshal.loads(f.read())
            f.close()
            if d.get("me") != self.client.me:
                return
            self.client.peers = d.get("peers", {})
            self.dialogs = d.get("dialogs", [])
            self.filters = d.get("filters", [])
            self.rows_cache = {}
        except:
            pass

    def save_cache(self):
        self.cache_armed = 0
        if self.client is None or self.client.me is None:
            return
        try:
            import marshal
            keep = {}
            for r in self.dialogs:
                p = self.client.peers.get(r["key"])
                if p is not None:
                    keep[r["key"]] = p
            for r in self.dialogs:
                s = r.get("sender_key")
                if s and self.client.peers.has_key(s):
                    keep[s] = self.client.peers[s]
            data = marshal.dumps({"me": self.client.me, "peers": keep,
                                  "dialogs": self.dialogs[:150], "filters": self.filters})
            f = open(self.dir + "cache.bin", "wb")
            f.write(data)
            f.close()
        except:
            self.log("cache: " + str(sys.exc_info()[1]))

    def save_cache_soon(self):
        if not self.cache_armed:
            self.cache_armed = 1
            self.net.later(8, self.save_cache)

    # ---------------------------------------------------------- start-up

    def setup_ap(self, force=0):
        apid = self.cfg.get("apid")
        if force or apid is None:
            try:
                apid = socket.select_access_point()
            except:
                apid = None
            if apid is None:
                return 0
            self.cfg.set("apid", int(apid))
            self.cfg.save()
        try:
            self.apo = socket.access_point(int(apid))
            socket.set_default_access_point(self.apo)
            try:
                self.apo.start()
            except:
                boot_log("ap start: " + str(sys.exc_info()[1]))
            return 1
        except:
            self.log("access point: " + str(sys.exc_info()[1]))
            self.cfg.set("apid", None)
            self.cfg.save()
            return 0

    def ask_api(self):
        appuifw.note(u"RetroTele needs your own Telegram API key. On a computer, "
                     u"open my.telegram.org > API development tools and create an app. "
                     u"Then enter api_id and api_hash here.", "info")
        api_id = appuifw.query(u"api_id (a number)", "number")
        if not api_id:
            return 0
        api_hash = appuifw.query(u"api_hash (32 letters and digits)", "text")
        if not api_hash:
            return 0
        api_hash = to_b(api_hash).strip().lower()
        if len(api_hash) != 32:
            appuifw.note(u"api_hash should be 32 characters long.", "error")
            return 0
        self.cfg.set("api_id", int(api_id))
        self.cfg.set("api_hash", api_hash)
        self.cfg.save()
        return 1

    def start(self):
        try:
            sp = find_schema()
            self.schema = tl.Schema(sp)
            d = os.path.dirname(sp)
            if d:
                d = d + os.sep
            if os.path.exists(d + "emoji.txt"):
                tgui.set_asset_dir(d)
        except:
            show_crash("schema")
            self.exit()
            return
        boot_log("schema layer %d" % self.schema.layer)
        boot_log("timezone offset %d s" % self.tz)
        try:
            # 1 in front, 0 in the background: without this the app never knows
            # it is behind another application, so no global note was shown
            appuifw.app.focus = self.app_focus
            boot_log("focus: handler installed")
        except:
            self.log("focus handler: " + str(sys.exc_info()[1]))
        while not self.cfg.get("api_id") or not self.cfg.get("api_hash"):
            if not self.ask_api():
                if appuifw.query(u"RetroTele cannot work without api_id. Exit?", "query"):
                    self.exit()
                    return
        self.status(u"Connecting to the network...")
        if not self.setup_ap():
            appuifw.note(u"No access point chosen. Options > Settings > Access point.",
                         "error")
        self.client = tgclient.Client(self.net, self.schema, self, self.store,
                                      self.cfg.get("api_id"), self.cfg.get("api_hash"),
                                      to_b(VERSION))
        # the integrity check is cheap with the compiled crypto module, so it
        # is on by default then; without it fast mode skips it
        default = "0"
        if tgcrypto.NATIVE:
            default = "1"
        self.client.verify = self.cfg.get("verify", default) == "1"
        self.client.set_call_version("2.7.7")      # works with official apps
        boot_log("native crypto: %d, full check: %d" % (tgcrypto.NATIVE, self.client.verify))
        self.status(u"Connecting...")
        self.client.start()
        if self.client.logged_in():
            self.load_cache()
            self.show_chats()
            self.load_dialogs()
        else:
            self.show_welcome()

    # ---------------------------------------------------------- login

    def show_welcome(self):
        self.screen = "welcome"
        self.set_screen("large")
        self.view = tgui.WelcomeView(self, [
            u"Telegram for your Nokia.",
            u"Press the centre key to log in."])
        self.view.show()
        appuifw.app.menu = [(u"Log in", self.login_phone),
                            (u"Settings", self.settings),
                            (u"Exit", self.exit)]
        appuifw.app.exit_key_handler = self.exit
        self.done_wait()

    def login_phone(self):
        phone = appuifw.query(u"Phone number with country code", "text",
                              to_u(self.store.get("phone", "+")))
        if not phone:
            return
        phone = to_b(phone).replace(" ", "").replace("-", "")
        self.store.set("phone", phone)
        self.store.save()
        self.phone = phone
        self.status(u"Sending code...")
        self.client.send_code(phone, self.code_sent, self.login_failed)

    def code_sent(self, sent):
        self.done_wait()
        if sent["_"] == "auth.sentCodeSuccess":
            self.client.authorized(sent["authorization"])
            self.logged_in()
            return
        self.code_hash = sent["phone_code_hash"]
        where = sent.get("type", {}).get("_", "")
        msg = u"Code sent"
        if where == "auth.sentCodeTypeApp":
            msg = u"Code sent to your Telegram app"
        elif where == "auth.sentCodeTypeSms":
            msg = u"Code sent by SMS"
        elif where == "auth.sentCodeTypeSetUpEmailRequired":
            appuifw.note(u"Telegram wants an e-mail set up for this account first. "
                         u"Log in once with an official app, then try again.", "error")
            return
        self.net.later(0.2, lambda self=self, msg=msg: self.ask_code(msg))

    def ask_code(self, msg):
        code = appuifw.query(msg + u". Enter it:", "text")
        if not code:
            if appuifw.query(u"Send the code again?", "query"):
                self.status(u"Sending code...")
                self.client.resend_code(self.phone, self.code_hash, self.code_sent,
                                        self.login_failed)
            return
        self.status(u"Checking code...")
        self.client.sign_in(self.phone, self.code_hash, to_b(code).strip(),
                            lambda r, self=self: self.logged_in(), self.code_failed)

    def code_failed(self, e):
        self.done_wait()
        if isinstance(e, RpcError) and e.message == "SESSION_PASSWORD_NEEDED":
            self.net.later(0.2, self.two_step)
            return
        appuifw.note(err_msg(e), "error")
        if isinstance(e, RpcError) and e.message == "PHONE_CODE_INVALID":
            self.net.later(0.2, lambda self=self: self.ask_code(u"Code"))

    def login_failed(self, e):
        self.done_wait()
        appuifw.note(err_msg(e), "error")

    def two_step(self):
        self.status(u"Two-step verification...")
        self.client.get_password(self.got_password_info, self.login_failed)

    def got_password_info(self, pw):
        self.done_wait()
        algo = pw.get("current_algo") or {}
        if algo.get("_") != "passwordKdfAlgoSHA256SHA256PBKDF2HMACSHA512iter100000SHA256ModPow":
            appuifw.note(u"Unsupported password type: " + to_u(algo.get("_", "?")), "error")
            return
        hint = to_u(pw.get("hint") or "")
        slow = u"Enter password (phone, about 1 hour)"
        if tgcrypto.NATIVE:
            slow = u"Enter password"
        choice = appuifw.popup_menu([slow,
                                     u"Use hash from PC helper"],
                                    u"Two-step verification")
        if choice is None:
            return
        if choice == 1:
            self.pc_helper(algo)
            return
        label = u"Password"
        if hint:
            label = u"Password (hint: " + hint + u")"
        pw_text = appuifw.query(label, "code")
        if not pw_text:
            return
        if not tgcrypto.NATIVE:
            appuifw.note(u"Computing the password key. This takes a long time on the "
                         u"phone: keep RetroTele open and the phone charging.", "info")
        self.hash_job = tgsrp.PasswordHash(to_b(pw_text), algo["salt1"], algo["salt2"])
        self.hash_t0 = time.time()
        self.net.later(0.05, self.hash_tick)

    def hash_tick(self):
        job = self.hash_job
        if job is None:
            return
        if job.step(40):
            self.hash_job = None
            self.status(u"Checking password...")
            self.finish_srp(job.result)
            return
        pct = job.done_n * 100 / job.total
        el = time.time() - self.hash_t0
        left = u""
        if job.done_n > 200:
            rest = el * (job.total - job.done_n) / job.done_n
            left = u", ~%d min left" % int(rest / 60 + 1)
        self.status(u"Password %d%%%s" % (pct, left))
        self.net.later(0.01, self.hash_tick)

    def pc_helper(self, algo):
        path = self.dir + "2fa_salts.txt"
        try:
            f = open(path, "wb")
            f.write("salt1=" + tgclient.hexs(algo["salt1"]) + "\n")
            f.write("salt2=" + tgclient.hexs(algo["salt2"]) + "\n")
            f.close()
        except:
            appuifw.note(u"Cannot write " + to_u(path), "error")
            return
        appuifw.note(u"Saved " + to_u(path) + u". Connect the phone to a PC (mass storage), "
                     u"run: python3 tg2fa.py <card>/RetroTele, then come back and "
                     u"select Continue.", "info")
        appuifw.app.menu = [(u"Continue (read hash from PC)", self.pc_helper_done),
                            (u"Log in", self.login_phone), (u"Exit", self.exit)]

    def pc_helper_done(self):
        path = self.dir + "2fa_hash.txt"
        try:
            f = open(path, "rb")
            x = tgclient.unhex(f.read().strip())
            f.close()
        except:
            appuifw.note(u"No hash yet in " + to_u(path), "error")
            return
        try:
            os.remove(path)
        except:
            pass
        self.status(u"Checking password...")
        self.finish_srp(x)

    def finish_srp(self, x):
        def got(pw, self=self, x=x):
            try:
                ans = tgclient.srp_answer(pw, x)
            except:
                self.login_failed(err_text())
                return
            self.client.check_password(ans, lambda r, self=self: self.logged_in(),
                                       self.password_failed)
        self.client.get_password(got, self.login_failed)

    def password_failed(self, e):
        self.done_wait()
        appuifw.note(err_msg(e), "error")
        self.show_welcome()

    def logged_in(self):
        self.done_wait()
        try:
            os.remove(self.dir + "2fa_salts.txt")
        except:
            pass
        self.show_chats()
        self.load_dialogs()

    def logged_out(self):
        self.dialogs = []
        self.msgs = {}
        self.rows_cache = {}
        try:
            os.remove(self.dir + "cache.bin")
        except:
            pass
        appuifw.note(u"You were logged out of Telegram.", "error")
        self.show_welcome()

    # ---------------------------------------------------------- chat list data

    def tabs(self):
        """The tab bar, in the order the Telegram app on the phone shows them:
        All first, then your folders in the server's order, then our own tabs.
        Archived is not a tab: it is the first row of All chats."""
        tabs = [(u"All", "all")]
        have = {"all": 1}
        for f in self.filters:
            title = to_u(f["title"]).strip()
            if not title:
                title = u"Folder"
            if have.has_key(title.lower()):
                continue
            have[title.lower()] = 1
            tabs.append((title, ("folder", f)))
        for t in BUILTIN_TABS:
            if not have.has_key(t[0].lower()):
                tabs.append(t)
        tabs.append((u"Contacts", "contacts"))
        return tabs

    def decorate(self, r):
        """Adds what the chat list draws (time text, online dot)."""
        d = {}
        d.update(r)
        d["time"] = tgui.short_time(r.get("date", 0), self.now(), self.tz)
        d["online"] = r["key"][0] == "u" and self.client.is_online(r["key"])
        d["sender"] = to_u(r.get("sender", ""))
        d["preview"] = to_u(r.get("preview", ""))
        t = self.client.typing_text(r["key"])
        if t is not None:
            d["preview"] = to_u(t)
        return d

    def tab_match(self, spec, r):
        """Does this chat belong in this tab? (the badges count kinds directly)"""
        if spec == "all" or spec == "archived":
            return 1
        if spec == "unread":
            return bool(r.get("unread") or r.get("mark"))
        if spec == "personal" or spec == "groups" or spec == "channels":
            kind = self.client.peer(r["key"])["kind"]
            if spec == "personal":
                return kind in ("user", "bot", "self")
            if spec == "groups":
                return kind in ("group", "supergroup")
            return kind == "channel"
        if type(spec) is types.TupleType:
            return self.client.in_filter(spec[1], r)
        return 1

    def tab_badges(self):
        """Unread chats per folder tab, in one pass over the chats.

        The tab bar asks for all of them once per repaint: asking per tab walked
        the chat list once per folder, which is slow on the N79.
        """
        tabs = self.tabs()
        cl = self.client
        need_kind = 0
        fidx = []
        i = 0
        for t in tabs:
            spec = t[1]
            if spec == "personal" or spec == "groups" or spec == "channels":
                need_kind = 1
            elif type(spec) is types.TupleType:
                fidx.append(i)
            i = i + 1
        by_kind = {}
        hits = {}
        n_all = 0
        for r in self.dialogs or []:
            if not (r.get("unread") or r.get("mark")):
                continue
            n_all = n_all + 1
            if need_kind:
                kind = cl.peer(r["key"])["kind"]
                by_kind[kind] = by_kind.get(kind, 0) + 1
            for i in fidx:
                if cl.in_filter(tabs[i][1][1], r):
                    hits[i] = hits.get(i, 0) + 1
        out = []
        i = 0
        for t in tabs:
            spec = t[1]
            n = 0
            if spec == "all" or spec == "unread":
                n = n_all
            elif spec == "personal":
                n = by_kind.get("user", 0) + by_kind.get("bot", 0) + by_kind.get("self", 0)
            elif spec == "groups":
                n = by_kind.get("group", 0) + by_kind.get("supergroup", 0)
            elif spec == "channels":
                n = by_kind.get("channel", 0)
            elif type(spec) is types.TupleType:
                n = hits.get(i, 0)
            elif spec == "archived":
                # archived chats are not in self.dialogs
                for r in self.archived or []:
                    if r.get("unread"):
                        n = n + 1
            out.append(n)
            i = i + 1
        return out

    def tab_rows(self, i):
        tabs = self.tabs()
        if i >= len(tabs):
            i = 0
        spec = tabs[i][1]
        ck = (i, len(tabs))
        rows = self.rows_cache.get(ck)
        if rows is not None:
            return rows
        cl = self.client
        src = self.dialogs
        rows = []
        if spec == "contacts":
            if self.contacts is not None:
                keys = list(self.contacts)
                online = []
                rest = []
                for k in keys:
                    if cl.is_online(k):
                        online.append(k)
                    else:
                        rest.append(k)
                for k in online + rest:
                    rows.append({"key": k, "preview": to_u(cl.status_text(k)), "sender": u"",
                                 "time": u"", "online": cl.is_online(k), "contact_row": 1,
                                 "unread": 0, "top": 0})
            self.rows_cache[ck] = rows
            return rows
        if spec == "all":
            ar = self.archived_row()
            if ar is not None:
                rows.append(ar)
        for r in src:
            if self.tab_match(spec, r):
                rows.append(self.decorate(r))
        self.rows_cache[ck] = rows
        return rows

    def archived_row(self):
        """The Archived entry at the top of All chats (None when nothing is archived)."""
        rows = self.archived or []
        if not rows:
            return None
        n = 0
        for r in rows:
            n = n + (r.get("unread") or 0)
        label = u"%d chats" % len(rows)
        if len(rows) == 1:
            label = u"1 chat"
        return {"archived_row": 1, "key": "archived", "unread": n, "mark": 0,
                "preview": label, "sender": u"", "time": u"", "top": 0, "out": 0,
                "muted": 0, "read_out": 0}

    def archived_rows(self):
        rows = []
        for r in self.archived or []:
            rows.append(self.decorate(r))
        return rows

    def archived_opened(self):
        self.update_list_menu()
        appuifw.app.exit_key_handler = self.list_view.close_archived
        if self.archived is None:
            self.client.get_dialogs(self.got_archived, self.load_failed, 25, None, 1)

    def archived_closed(self):
        self.update_list_menu()
        appuifw.app.exit_key_handler = self.exit

    def dialogs_changed(self):
        self.rows_cache = {}
        self.save_cache_soon()

    def empty_text(self, tab):
        spec = self.tabs()[tab][1]
        if spec == "contacts" and self.contacts is None:
            return u"Loading contacts..."
        if not self.dialogs and self.busy:
            return u"Loading chats..."
        if spec == "unread":
            return u"All caught up!"
        return u"No chats here"

    def tab_changed(self, tab):
        spec = self.tabs()[tab][1]
        if spec == "contacts" and self.contacts is None:
            self.client.get_contacts(self.got_contacts, self.load_failed)
        elif spec != "all" and spec != "contacts" and len(self.dialogs) < 60:
            self.load_more_dialogs()
        self.update_list_menu()

    def got_contacts(self, keys):
        self.contacts = keys
        self.rows_cache = {}
        self.redraw()

    def got_archived(self, rows, more):
        self.archived = rows
        self.rows_cache = {}
        if self.screen == "chats":
            self.redraw()

    def near_end(self, tab):
        spec = self.tabs()[tab][1]
        if spec != "contacts" and self.more_dialogs:
            self.load_more_dialogs()

    def load_dialogs(self):
        self.status(u"Updating...")
        self.loading_dialogs = 1
        self.client.get_dialogs(self.got_dialogs, self.load_failed, 20)
        self.client.get_filters(self.got_filters, lambda e: None)
        if self.archived is None:
            # needed for the Archived row at the top of All chats
            self.client.get_dialogs(self.got_archived, lambda e: None, 20, None, 1)

    def got_dialogs(self, rows, more):
        self.loading_dialogs = 0
        self.dialogs_time = time.time()
        self.done_wait()
        have = {}
        for r in rows:
            have[r["key"]] = 1
        for r in self.dialogs[len(rows):]:
            if not have.has_key(r["key"]):
                rows.append(r)   # keep chats from pages loaded earlier
        self.dialogs = rows
        self.more_dialogs = more
        self.dialogs_changed()
        self.redraw()

    def load_more_dialogs(self):
        if self.loading_dialogs or not self.more_dialogs or not self.dialogs:
            return
        self.loading_dialogs = 1
        self.status(u"Loading more chats...")
        self.client.get_dialogs(self.got_more_dialogs, self.load_failed, 25, self.dialogs[-1])

    def got_more_dialogs(self, rows, more):
        self.loading_dialogs = 0
        self.busy = u""
        have = {}
        for r in self.dialogs:
            have[r["key"]] = 1
        for r in rows:
            if not have.has_key(r["key"]):
                self.dialogs.append(r)
        self.more_dialogs = more and len(self.dialogs) < 400
        self.dialogs_changed()
        self.redraw()

    def got_filters(self, filters):
        self.filters = filters
        self.dialogs_changed()
        self.redraw()

    def load_failed(self, e):
        self.loading_dialogs = 0
        self.loading_older = 0
        self.done_wait()
        self.log("load failed: " + to_b(err_msg(e)))
        self.show_toast(u"Could not load", err_msg(e))

    def dialog_for(self, key):
        for d in self.dialogs:
            if d["key"] == key:
                return d
        return None

    # ---------------------------------------------------------- chat list screen

    def show_chats(self):
        self.screen = "chats"
        self.chat_key = None
        self.list_view.archived = 0
        self.set_screen("large")
        self.view = self.list_view
        self.view.show()
        self.update_list_menu()
        appuifw.app.exit_key_handler = self.exit

    def update_list_menu(self):
        if self.screen != "chats":
            return
        m = [(u"Open chat", self.open_selected),
             (u"Search chats", self.search),
             (u"New chat (@username)", self.new_chat)]
        r = self.list_view.current()
        if r is not None and not r.get("archived_row") and r["key"][0] == "u" and \
                self.client.peer(r["key"]).get("phone"):
            m.append((u"Call " + one_line(self.client.short_name(r["key"]), 20),
                      lambda self=self, k=r["key"]: self.call_peer(k)))
        if self.upload is not None:
            m.append((u"Cancel upload", self.cancel_upload))
        m = m + [(u"Mark all read", self.mark_tab_read),
                 (u"Refresh", self.refresh_all),
                 (u"Settings", self.settings),
                 (u"About", self.about),
                 (u"Exit", self.exit)]
        appuifw.app.menu = m

    def open_selected(self):
        r = self.list_view.current()
        if r is not None:
            self.open_row(r)

    def open_row(self, r):
        if r.get("archived_row"):
            self.list_view.show_archived()
            return
        self.open_chat(r["key"])

    def refresh_all(self):
        self.contacts = None
        self.archived = None
        self.load_dialogs()

    def search(self):
        q = appuifw.query(u"Search chats and contacts", "text")
        if not q:
            return
        q = to_u(q).lower()
        found = []
        seen = {}
        for r in self.dialogs + (self.archived or []):
            if to_u(self.client.peer_name(r["key"])).lower().find(q) >= 0:
                found.append(r["key"])
                seen[r["key"]] = 1
        for k in (self.contacts or []):
            if not seen.has_key(k) and to_u(self.client.peer_name(k)).lower().find(q) >= 0:
                found.append(k)
        if not found:
            if appuifw.query(u"No chat found. Look up @" + q + u" on Telegram?", "query"):
                self.lookup(to_b(q))
            return
        names = []
        for k in found:
            names.append(one_line(self.client.peer_name(k), 40))
        i = appuifw.selection_list(names, 1)
        if i is not None:
            self.open_chat(found[i])

    def new_chat(self):
        name = appuifw.query(u"Username (without @)", "text")
        if name:
            self.lookup(to_b(name).strip())

    def lookup(self, name):
        self.status(u"Looking up...")
        self.client.resolve_username(name, lambda key, self=self: (self.done_wait(),
                                                                   self.open_chat(key)),
                                     self.load_failed)

    def mark_tab_read(self):
        rows = self.list_view.rows()
        n = 0
        for r in rows:
            if r.get("unread") and not r.get("contact_row") and not r.get("archived_row"):
                self.client.mark_read(r["key"], r.get("top", 0))
                d = self.dialog_for(r["key"])
                if d is not None:
                    d["unread"] = 0
                    d["mark"] = 0
                n = n + 1
        self.dialogs_changed()
        self.redraw()
        self.show_toast(u"Done", u"%d chats marked as read" % n)

    def call_peer(self, key):
        p = self.client.peer(key)
        phone = p.get("phone")
        if not phone:
            appuifw.note(u"This person doesn't share a phone number with you. "
                         u"Telegram voice calls aren't possible on this phone.", "info")
            return
        num = u"+" + to_u(phone)
        if appuifw.query(u"Call " + to_u(p["name"]) + u" at " + num +
                         u" (normal phone call)?", "query"):
            try:
                import telephone
                telephone.dial(num)
            except:
                appuifw.note(u"Cannot dial: " + err_text(), "error")

    # ---------------------------------------------------------- one chat

    def chat_messages(self, key):
        return self.msgs.get(key, [])

    def read_out(self, key):
        d = self.dialog_for(key)
        v = self.read_outs.get(key, 0)
        if d is not None:
            v = max(v, d.get("read_out", 0))
        return v

    def quote_for(self, key, mid):
        for m in self.msgs.get(key, []):
            if m["id"] == mid:
                t = m["text"]
                if m["media"]:
                    t = m["media"]
                return (to_u(m["from"]), to_u(t))
        return (u"Reply", u"to an earlier message")

    def draft_preview(self, key):
        d = self.drafts.get(key)
        if d:
            return one_line(d, 80)
        return u""

    def chat_empty_text(self):
        if self.busy:
            return u"Loading messages..."
        return u"No messages here yet"

    def open_chat(self, key):
        if key is None:
            return
        self.chat_key = key
        self.screen = "chat"
        self.set_screen("large")
        self.view = tgui.ChatView(self, key)
        self.chat_view = self.view
        self.view.show()
        self.update_chat_menu()
        appuifw.app.exit_key_handler = self.back_to_chats
        self.reload_chat()

    def update_chat_menu(self):
        key = self.chat_key
        m = []
        if self.client.can_write(key):
            m.append((u"Write message", self.compose))
        m.append((u"Reply to selected", self.reply_selected))
        m.append((u"Read selected message", self.read_selected))
        m.append((u"Search in chat", self.search_chat))
        if key[0] == "u" and self.client.peer(key)["kind"] == "user":
            m.append((u"Telegram call", lambda self=self, k=key: self.telegram_call(k)))
        if key[0] == "u" and self.client.peer(key).get("phone"):
            m.append((u"Call " + one_line(self.client.short_name(key), 20),
                      lambda self=self, k=key: self.call_peer(k)))
        if self.upload is not None:
            m.append((u"Cancel upload", self.cancel_upload))
        elif self.client.can_write(key):
            m.append((u"Attach file", self.attach_file))
            m.append((u"Send voice note", lambda self=self: self.attach_file("voice")))
            m.append((u"Send video note", lambda self=self: self.attach_file("video")))
        m = m + [(u"Load older messages", self.load_older),
                 (u"Jump to latest", self.jump_latest),
                 (u"View profile", self.view_profile),
                 (u"Refresh", self.reload_chat),
                 (u"Back to chats", self.back_to_chats)]
        appuifw.app.menu = m

    def reload_chat(self):
        key = self.chat_key
        if not self.msgs.get(key):
            self.status(u"Loading messages...")
        self.client.get_history(key, lambda msgs, self=self, key=key:
                                self.got_history(key, msgs, 0), self.load_failed)

    def load_older(self):
        key = self.chat_key
        msgs = self.msgs.get(key, [])
        if self.loading_older or not msgs or not self.older.get(key, 1):
            return
        self.loading_older = 1
        self.status(u"Loading older...")
        self.client.get_history(key, lambda m, self=self, key=key:
                                self.got_history(key, m, 1), self.load_failed,
                                offset_id=msgs[0]["id"])

    def got_history(self, key, msgs, older):
        self.done_wait()
        self.loading_older = 0
        old = self.msgs.get(key, [])
        view = self.view
        if older:
            self.older[key] = len(msgs) >= 20
            self.msgs[key] = msgs + old
            if isinstance(view, tgui.ChatView) and view.key_ == key and view.sel >= 0:
                view.sel = view.sel + len(msgs)
        else:
            if not old:
                self.older[key] = len(msgs) >= 20
            # keep older pages already loaded
            if old and msgs:
                first = msgs[0]["id"]
                keep = []
                for m in old:
                    if m["id"] < first:
                        keep.append(m)
                msgs = keep + msgs
            at_end = not isinstance(view, tgui.ChatView) or view.at_bottom()
            self.msgs[key] = msgs
            if isinstance(view, tgui.ChatView) and view.key_ == key and at_end:
                view.sel = len(msgs)
        # keep at most 12 chats in memory
        if len(self.msgs) > 12:
            for k in self.msgs.keys():
                if k != key and len(self.msgs) > 12:
                    del self.msgs[k]
        if key == self.chat_key:
            self.redraw()
            jm = self.jump_mid
            if jm is not None and jm[0] == key:
                if not self.focus_message(key, jm[1]):
                    self.fetch_around(key, jm[1])
            if msgs and not older:
                d = self.dialog_for(key)
                if d is None or d.get("unread") or d.get("mark"):
                    self.client.mark_read(key, msgs[-1]["id"])
                if d is not None and (d.get("unread") or d.get("mark")):
                    d["unread"] = 0
                    d["mark"] = 0
                    self.dialogs_changed()

    # ---------------------------------------------------------- search in a chat

    def search_chat(self):
        key = self.chat_key
        if key is None:
            return
        q = appuifw.query(u"Search messages in this chat", "text")
        if not q:
            return
        q = to_u(q).strip()
        if not q:
            return
        self.status(u"Searching...")
        self.client.search_messages(key, q, lambda msgs, self=self, key=key:
                                    self.got_search(key, msgs), self.load_failed)

    def got_search(self, key, msgs):
        self.done_wait()
        if key != self.chat_key:
            return
        if not msgs:
            appuifw.note(u"No message found.", "info")
            return
        names = []
        for m in msgs:
            t = to_u(self.client.preview(m))
            if not t:
                t = u"(no text)"
            head = self.hhmm(m["date"])
            if self.client.is_group(key) and m.get("from_key") and not m["out"]:
                head = head + u" " + to_u(self.client.short_name(m["from_key"]))
            names.append(one_line(head + u"  " + t, 70))
        i = appuifw.selection_list(names, 1)
        if i is not None:
            self.jump_to_message(key, msgs[i]["id"])

    def jump_to_message(self, key, mid):
        """Show a message in its chat, loading the page around it when needed."""
        self.jump_mid = (key, mid)
        if self.screen != "chat" or self.chat_key != key:
            self.open_chat(key)
            return
        if self.focus_message(key, mid):
            return
        self.fetch_around(key, mid)

    def focus_message(self, key, mid):
        view = self.view
        if not isinstance(view, tgui.ChatView) or view.key_ != key:
            return 0
        msgs = self.msgs.get(key, [])
        for i in range(len(msgs)):
            if msgs[i]["id"] == mid:
                self.jump_mid = None
                view.sel = i
                view.draw()
                return 1
        return 0

    def fetch_around(self, key, mid):
        self.status(u"Finding message...")
        self.client.get_history(key, lambda msgs, self=self, key=key:
                                self.got_around(key, msgs), self.load_failed,
                                offset_id=mid + 1)

    def got_around(self, key, msgs):
        self.done_wait()
        byid = {}
        for m in self.msgs.get(key, []):
            byid[m["id"]] = m
        for m in msgs:
            byid[m["id"]] = m
        ids = byid.keys()
        ids.sort()
        merged = []
        for i in ids:
            merged.append(byid[i])
        self.msgs[key] = merged
        jm = self.jump_mid
        self.jump_mid = None
        if jm is not None and jm[0] == key and not self.focus_message(key, jm[1]):
            appuifw.note(u"That message is not available any more.", "info")
        if key == self.chat_key:
            self.redraw()

    def jump_latest(self):
        if isinstance(self.view, tgui.ChatView):
            self.view.sel = len(self.chat_messages(self.chat_key))
            self.view.draw()

    def selected_message(self):
        if isinstance(self.view, tgui.ChatView):
            return self.view.selected()
        return None

    def reply_selected(self):
        m = self.selected_message()
        if m is None:
            appuifw.note(u"Select a message with up/down first.", "info")
            return
        self.compose(m["id"])

    def read_selected(self):
        m = self.selected_message()
        if m is None:
            appuifw.note(u"Select a message with up/down first.", "info")
            return
        self.show_text(m)

    def message_menu(self, m):
        items = []
        acts = []
        if self.client.can_write(self.chat_key) and not m["service"]:
            items.append(u"Reply")
            acts.append(lambda self=self, m=m: self.compose(m["id"]))
        # media first: play or open in the phone's own player / reader
        au = m.get("audio")
        fi = m.get("file")
        video = bool(fi and fi.get("mime", "")[:6] == "video/")
        if au and tgclient.audio_playable(au):
            items.insert(0, u"Play audio")
            acts.insert(0, lambda self=self, m=m: self.play_audio(m))
        elif au or video:
            label = u"Play voice message"
            if video:
                label = u"Play video"
            items.insert(0, label)
            acts.insert(0, lambda self=self, m=m: self.open_media(m))
        elif fi:
            items.insert(0, u"Open file")
            acts.insert(0, lambda self=self, m=m: self.open_media(m))
        if m.get("poll"):
            items.append(u"Poll results")
            acts.append(lambda self=self, m=m: self.show_poll(m))
            if not m["poll"].get("closed") and self.client.can_write(self.chat_key):
                items.append(u"Vote in poll")
                acts.append(lambda self=self, m=m: self.vote_poll(m))
        if m.get("buttons"):
            items.append(u"Bot buttons")
            acts.append(lambda self=self, m=m: self.bot_buttons(m))
        if not m["service"]:
            items.append(u"Forward")
            acts.append(lambda self=self, m=m: self.forward_message(m))
        if m.get("photo") and not video:
            items.append(u"View picture")
            acts.append(lambda self=self, m=m: self.view_photo(m))
        if m.get("photo_file"):
            items.append(u"Save picture (original)")
            acts.append(lambda self=self, m=m: self.save_photo(m))
        if au and tgclient.audio_playable(au):
            items.append(u"Save audio")
            acts.append(lambda self=self, m=m: self.save_audio(m))
        elif fi:
            label = u"Save file"
            if au:
                label = u"Save voice message"
            elif video:
                label = u"Save video"
            items.append(label)
            acts.append(lambda self=self, m=m: self.save_file(m))
        items.append(u"Read full message")
        acts.append(lambda self=self, m=m: self.show_text(m))
        if m["out"] and not m["service"] and not m["media"] and m["text"]:
            items.append(u"Edit")
            acts.append(lambda self=self, m=m: self.compose(0, m))
        if not m["service"] or m["out"]:
            items.append(u"Delete")
            acts.append(lambda self=self, m=m: self.delete_message(m))
        if m.get("from_key") and m["from_key"] != self.chat_key and not m["out"] and \
                m["from_key"][0] == "u":
            items.append(u"Message " + to_u(self.client.short_name(m["from_key"])))
            acts.append(lambda self=self, k=m["from_key"]: self.open_chat(k))
        if m["text"] and not m["service"]:
            items.append(u"Copy text")
            acts.append(lambda self=self, m=m: self.copy_text(m))
        if m["id"] and not m["service"]:
            items.append(u"React")
            acts.append(lambda self=self, m=m: self.react(m))
        i = appuifw.popup_menu(items)
        if i is not None:
            acts[i]()

    def copy_text(self, m):
        """Copy into RetroTele's own clipboard: PyS60 1.4.5 has no system one, so
        Copy here and Paste in the message box."""
        text = m.get("text") or u""
        if not text:
            appuifw.note(u"Nothing to copy.", "info")
            return
        self.clipboard = to_u(text)
        try:
            appuifw.app.set_clipboard(self.clipboard)
        except:
            pass                   # no system clipboard on this build
        self.show_toast(u"Copied", u"Paste it with Options > Paste while writing")

    # Telegram's default reactions as UTF-8 bytes: the phone's unicode type is
    # UCS-2, so an astral emoji decoded here would be two bogus code points
    REACTION_FALLBACK = ("\xf0\x9f\x91\x8d", "\xe2\x9d\xa4", "\xf0\x9f\x94\xa5",
                         "\xf0\x9f\xa5\xb0", "\xf0\x9f\x91\x8f", "\xf0\x9f\x98\x81",
                         "\xf0\x9f\xa4\x94", "\xf0\x9f\xa4\xaf", "\xf0\x9f\x98\xb1",
                         "\xf0\x9f\xa4\xac", "\xf0\x9f\x98\xa2", "\xf0\x9f\x98\x8d",
                         "\xf0\x9f\xa4\xa9", "\xf0\x9f\x98\xae", "\xf0\x9f\x98\xa1",
                         "\xf0\x9f\x98\x85", "\xf0\x9f\xa4\xa3", "\xf0\x9f\xa5\xb2",
                         "\xf0\x9f\xa4\x97", "\xf0\x9f\x92\xa9")

    def react(self, m):
        """Open the reaction strip for this message. Replacing the app body while a
        popup menu is still closing crashes S60, so it is queued just after it."""
        self.log("react: opening strip, chat %s message %s" % (self.chat_key, m["id"]))
        self.net.later(0.25, lambda self=self, m=m: self.show_react_strip(m))

    def show_react_strip(self, m):
        try:
            self.screen = "react"
            self.set_screen("large")
            v = tgui.ReactView(self, self.chat_key, m)
            self.view = v
            v.show()
            appuifw.app.menu = [(u"Send reaction", v.choose), (u"Back", self.close_react)]
            appuifw.app.exit_key_handler = self.close_react
            self.log("react: strip shown, %d emoji" % len(v.emojis))
        except:
            self.log("react: " + err_text())
            self.back_to_chat()
            self.show_toast(u"React", u"Could not open the reaction bar")

    def close_react(self):
        self.log("react: closed without sending")
        self.back_to_chat()

    def apply_reaction(self, m, emoji):
        """Show the reaction in the bubble at once; the server's update follows a
        moment later and replaces these counts with the real ones."""
        old = None
        for r in m.get("reactions") or []:
            if r.get("chosen"):
                old = r
        rs = []
        for r in m.get("reactions") or []:
            if r is not old:
                rs.append(r)
        if emoji:
            hit = None
            for r in rs:
                if r.get("emoji") == emoji:
                    hit = r
            if hit is None:
                rs.append({"emoji": emoji, "count": 1, "chosen": 1})
            else:
                hit["chosen"] = 1
        m["reactions"] = rs

    def send_reaction(self, m, emoji):
        """Send one reaction (or remove ours, with an empty emoji)."""
        key = self.chat_key
        mid = m["id"]
        if emoji:
            self.log("react: picked %s for message %s" % (emoji, mid))
        else:
            self.log("react: picked remove for message %s" % mid)
        self.apply_reaction(m, emoji)

        def ok(res, self=self, m=m):
            self.done_wait()
            self.log("react: sent, bubble now has %d reactions" %
                     len(m.get("reactions") or []))
            self.back_to_chat()
        self.status(u"Reacting...")
        self.client.send_reaction(key, mid, emoji, ok, self.send_failed)

    def typing_changed(self, key):
        """Show the typing line at once, then redraw when it expires.
        The chat list caches its rows, so the cache is dropped too."""
        self.rows_cache = {}
        self.log("typing: %s -> %s (screen %s, chat %s)" % (
            key, self.client.typing_text(key), getattr(self, "screen", "?"), self.chat_key))
        self.redraw_soon()
        self.net.later(7, self.typing_expired)

    def typing_expired(self):
        self.rows_cache = {}
        self.log("typing: cleared")
        self.redraw_soon()

    def reactions_changed(self, key, mid, rs):
        n = -1
        for m in self.msgs.get(key, []):
            if m["id"] == mid:
                n = len(rs)
                m["reactions"] = rs
        self.log("react: update %s message %s -> %d reactions (screen %s)" % (
            key, mid, n, getattr(self, "screen", "?")))
        if key == self.chat_key:
            self.redraw_soon()

    def media_path(self, info):
        """Playback cache inside the media folder; saving uses save_path()."""
        return self.media.folder + info["id"] + "." + info["ext"]

    SAVE_FOLDERS = {"image": u"Pictures", "video": u"Videos", "audio": u"Sounds"}

    def save_folder(self, kind):
        """Pictures / Videos / Sounds / Files inside the media folder, made on demand."""
        name = self.SAVE_FOLDERS.get(kind, u"Files")
        base = self.media.folder + name.encode("utf-8")
        try:
            if not os.path.isdir(base):
                os.mkdir(base)
        except:
            self.log("save folder: " + str(sys.exc_info()[1]))
            return self.media.folder
        return base + os.sep

    def save_name(self, name, fallback):
        """The sender's own file name, made safe for a memory card."""
        if not name:
            name = fallback
        name = to_u(name)
        try:
            name = fileinfo.base_name(name)
        except:
            pass
        out = []
        for c in name:
            if c in u"\\/:*?\"<>|" or ord(c) < 32:
                out.append(u"_")
            else:
                out.append(c)
        name = u"".join(out).strip()
        if not name:
            name = to_u(fallback)
        try:
            return name.encode("utf-8")
        except:
            return name

    def save_path(self, info, kind, fallback):
        """Where a saved file goes: Media/Pictures, Videos, Sounds or Files, with
        the name it had. Returns (path, already_saved)."""
        folder = self.save_folder(kind)
        base = self.save_name(info.get("name") or "", fallback)
        path = folder + base
        n = 2
        while os.path.exists(path):
            if os.path.getsize(path) == info.get("size", 0):
                return path, 1
            dot = base.rfind(".")
            if dot > 0:
                path = folder + base[:dot] + " (" + str(n) + ")" + base[dot:]
            else:
                path = folder + base + " (" + str(n) + ")"
            n = n + 1
        return path, 0

    def save_file(self, m):
        """Save a video, document or voice note to Pictures/Videos/Sounds/Files."""
        info = m.get("file")
        if not info:
            appuifw.note(u"This message has no file to save.", "info")
            return
        name = to_u(info.get("name") or "")
        kind = "file"
        if info.get("voice") or fileinfo.is_audio(name):
            kind = "audio"
        elif fileinfo.is_video(name):
            kind = "video"
        elif fileinfo.is_image(name):
            kind = "image"
        fallback = "file_" + str(info.get("id")) + "." + (info.get("ext") or "bin")
        path, saved = self.save_path(info, kind, fallback)
        if saved:
            appuifw.note(u"Already saved:\n" + to_u(path), "info")
            return
        self.download_to(info, path, u"Saved")

    def save_photo(self, m):
        """Save the original-size photo, not the small preview the chat shows."""
        info = m.get("photo_file")
        if not info:
            appuifw.note(u"This message has no picture to save.", "info")
            return
        if (info.get("name") or "") == "photo.jpg":
            # Telegram's generic photo name: number them so two do not collide
            info = dict(info)
            info["name"] = ""
        path, saved = self.save_path(info, "image",
                                     "photo_" + str(info.get("id")) + ".jpg")
        if saved:
            appuifw.note(u"Already saved:\n" + to_u(path), "info")
            return
        self.download_to(info, path, u"Picture saved")

    def save_audio(self, m):
        """Save a music file to Media/Sounds with its own name."""
        info = m.get("audio")
        if not info:
            appuifw.note(u"This message has no audio to save.", "info")
            return
        fallback = to_u(info.get("title") or "audio") + u"." + (info.get("ext") or "mp3")
        path, saved = self.save_path(info, "audio", fallback)
        if saved:
            appuifw.note(u"Already saved:\n" + to_u(path), "info")
            return
        self.download_to(info, path, u"Audio saved")

    def open_media(self, m):
        """Open a video, voice note or document with the phone's own application:
        its video or music player, PDF reader or zip manager."""
        info = m.get("file") or m.get("audio")
        if not info:
            appuifw.note(u"This message has nothing to open.", "info")
            return
        path = self.media_path(info)
        if os.path.exists(path):
            self.open_in_phone(path)
            return
        self.download_to(info, path, u"Saved", self.open_in_phone)

    def open_in_phone(self, path):
        """Hand a saved file to the app the phone has registered for it."""
        try:
            lock = e32.Ao_lock()
            h = appuifw.Content_handler(lambda: lock.signal())
            try:
                h.open_standalone(to_u(path))
            except AttributeError:
                h.open(to_u(path))
            return
        except:
            self.log("open %s: %s" % (path, str(sys.exc_info()[1])))
        appuifw.note(u"No app on this phone opens that file.\nIt is saved in:\n" +
                     to_u(self.media.folder), "info")

    def download_to(self, info, path, title, then=None):
        """Download one file to path, with progress and a guard against saving it twice.
        The big-download warning is the same one play_audio uses on pure-Python crypto."""
        if not hasattr(self, "downloads"):
            self.downloads = {}
        if self.downloads.has_key(info["id"]):
            appuifw.note(u"Still downloading. It finishes in the background; select the "
                         u"message again after that.", "info")
            return
        size = max(info.get("size", 0), 1)
        if not tgcrypto.NATIVE and size > 524288:
            mb = size / 1048576.0
            mins = int(size / 5000 / 60) + 1
            if not appuifw.query(u"Save %.1f MB? On this phone that takes about %d min. "
                                 u"It continues in the background and resumes if you "
                                 u"exit." % (mb, mins), "query"):
                return
        have = 0
        try:
            have = os.path.getsize(path + ".part")
        except:
            pass
        self.downloads[info["id"]] = 1
        t0 = time.time()

        def progress(done, self=self, size=size, t0=t0, have=have):
            el = time.time() - t0
            left = u""
            if el > 5 and done > have:
                rate = (done - have) / el
                left = u", %d min left" % (int((size - done) / max(rate, 1) / 60) + 1)
            self.status(u"Saving %d%% (%.1f/%.1f MB%s)" % (
                min(done * 100 / size, 99), done / 1048576.0, size / 1048576.0, left))

        def ok(p, self=self, info=info, title=title, then=then):
            if self.downloads.has_key(info["id"]):
                del self.downloads[info["id"]]
            self.done_wait()
            name = info.get("name") or u""
            if name:
                title = title + u" " + to_u(name)
            appuifw.note(to_u(title) + u":\n" + to_u(p), "info")
            if then is not None:
                then(p)

        def fail(e, self=self, info=info):
            if self.downloads.has_key(info["id"]):
                del self.downloads[info["id"]]
            self.load_failed(e)
        self.status(u"Saving...")
        self.client.download(info, path, ok, fail, progress)

    def play_audio(self, m):
        info = m["audio"]
        if not tgclient.audio_playable(info):
            appuifw.note(u"This is an Opus/OGG recording, which the N79 can't play yet. "
                         u"You can still save it to the phone: Options > "
                         u"Save voice message.", "info")
            return
        path = self.media_path(info)
        if os.path.exists(path):
            self.open_player(info, path)
            return
        if not hasattr(self, "downloads"):
            self.downloads = {}
        if self.downloads.has_key(info["id"]):
            appuifw.note(u"Still downloading. You can use other chats meanwhile; "
                         u"it plays when you select it again after it's done.", "info")
            return
        mb = info.get("size", 0) / 1048576.0
        have = 0
        try:
            have = os.path.getsize(path + ".part")
        except:
            pass
        if not tgcrypto.NATIVE and mb > 0.5:
            mins = int((info.get("size", 0) - have) / 5000 / 60) + 1
            if not appuifw.query(u"Download %.1f MB? On this phone that takes about %d min. "
                                 u"It continues in the background and resumes if you "
                                 u"exit." % (mb, mins), "query"):
                return
        size = max(info.get("size", 0), 1)
        key = self.chat_key
        t0 = time.time()
        self.downloads[info["id"]] = 1
        title = to_u(info.get("title", u"Audio"))

        def progress(done, self=self, size=size, t0=t0, have=have):
            el = time.time() - t0
            left = u""
            if el > 5 and done > have:
                rate = (done - have) / el
                left = u", %d min left" % (int((size - done) / max(rate, 1) / 60) + 1)
            self.status(u"Downloading %d%% (%.1f/%.1f MB%s)" % (
                min(done * 100 / size, 99), done / 1048576.0, size / 1048576.0, left))

        def ok(p, self=self, info=info, key=key, title=title):
            del self.downloads[info["id"]]
            self.done_wait()
            if self.screen == "chat" and self.chat_key == key:
                self.open_player(info, p)
            else:
                self.show_toast(u"Downloaded", title + u": select it to play")

        def fail(e, self=self, info=info):
            if self.downloads.has_key(info["id"]):
                del self.downloads[info["id"]]
            self.load_failed(e)
        self.status(u"Downloading...")
        self.client.download(info, path, ok, fail, progress)

    def open_player(self, info, path):
        self.screen = "player"
        self.set_screen("large")
        v = tgui.PlayerView(self, info, path)
        self.view = v
        v.show()
        appuifw.app.menu = [(u"Play / pause", v.toggle), (u"Back", self.close_player)]
        appuifw.app.exit_key_handler = self.close_player
        v.start()

    def close_player(self):
        v = self.view
        if isinstance(v, tgui.PlayerView):
            v.close()
        self.back_to_chat()

    def view_photo(self, m):
        info = m["photo"]
        self.screen = "photo"
        self.set_screen("full")
        self.view = tgui.PhotoView(self, info)
        self.view.show()
        appuifw.app.menu = [(u"Back", self.back_to_chat)]
        appuifw.app.exit_key_handler = self.back_to_chat
        if not os.path.exists(self.media.path(info)):
            def ok(path, self=self, info=info):
                v = self.view
                if isinstance(v, tgui.PhotoView) and v.info is info:
                    v.img = None
                    v.draw()
            self.client.download(info, self.media.path(info), ok, self.load_failed)

    def auto_photos(self):
        return self.cfg.get("auto_photos", "1") == "1"

    def show_text(self, m):
        self.screen = "text"
        self.set_screen("normal")
        t = appuifw.Text()
        head = to_u(m["from"]) + u", " + to_u(time.strftime(
            "%d.%m.%Y %H:%M", time.gmtime(m["date"] + self.tz)))
        body = to_u(m["text"])
        if m["media"]:
            body = u"[" + to_u(m["media"]) + u"]\n" + body
        if m.get("fwd"):
            body = u"Forwarded from " + to_u(m["fwd"]) + u"\n" + body
        t.set(head + u"\n\n" + body)
        appuifw.app.body = t
        appuifw.app.title = to_u(self.client.peer_name(self.chat_key))
        menu = []
        if self.client.can_write(self.chat_key):
            menu.append((u"Reply", lambda self=self, m=m: self.compose(m["id"])))
        menu.append((u"Back", self.back_to_chat))
        appuifw.app.menu = menu
        appuifw.app.exit_key_handler = self.back_to_chat

    # ---------------------------------------------------------- polls and bot buttons

    def poll_text(self, m):
        p = m["poll"]
        total = p.get("total", 0)
        lines = [to_u(p.get("question") or u"Poll")]
        if total:
            lines.append(u"%d votes" % total)
        lines.append(u"")
        for a in p.get("answers", []):
            t = u"   " + to_u(a.get("text", ""))
            if a.get("chosen"):
                t = u" * " + to_u(a.get("text", ""))
            if total:
                t = t + u"  %d%% (%d)" % (a.get("voters", 0) * 100 / total,
                                          a.get("voters", 0))
            lines.append(t)
        notes = []
        if p.get("multiple"):
            notes.append(u"multiple choice")
        if p.get("quiz"):
            notes.append(u"quiz")
        if p.get("closed"):
            notes.append(u"closed")
        if notes:
            lines.append(u"")
            lines.append(u", ".join(notes))
        if p.get("chosen"):
            lines.append(u"* is your vote")
        return u"\n".join(lines)

    def show_poll(self, m):
        if m is None or m.get("poll") is None:
            return
        self.poll_msg = m
        self.screen = "poll"
        self.set_screen("normal")
        t = appuifw.Text()
        t.set(self.poll_text(m))
        appuifw.app.body = t
        appuifw.app.title = u"Poll"
        menu = []
        if not m["poll"].get("closed") and self.client.can_write(self.chat_key):
            menu.append((u"Vote", lambda self=self, m=m: self.vote_poll(m)))
        menu.append((u"Back", self.back_to_chat))
        appuifw.app.menu = menu
        appuifw.app.exit_key_handler = self.back_to_chat

    def vote_poll(self, m):
        p = m["poll"]
        names = []
        options = []
        for a in p.get("answers", []):
            t = to_u(a.get("text", ""))
            if p.get("multiple") and a.get("chosen"):
                t = u"[x] " + t
            names.append(one_line(t, 60))
            options.append(a.get("option"))
        if not names:
            return
        i = appuifw.selection_list(names, 1)
        if i is None:
            return
        opt = options[i]
        chosen = []
        if p.get("multiple"):
            for a in p.get("answers", []):
                if a.get("chosen") and a.get("option") != opt:
                    chosen.append(a.get("option"))
            if not (opt in chosen):
                chosen.append(opt)
        else:
            chosen.append(opt)
        self.status(u"Voting...")

        def ok(res, self=self, m=m, chosen=chosen):
            self.done_wait()
            self.voted_locally(m["poll"], chosen)
            self.show_poll(m)
        self.client.send_vote(self.chat_key, m["id"], chosen, ok, self.send_failed)

    def voted_locally(self, p, chosen):
        """Show the vote at once; the server's updateMessagePoll follows a moment later."""
        total = p.get("total", 0)
        for a in p.get("answers", []):
            was = a.get("chosen", 0)
            now = 0
            if a.get("option") in chosen:
                now = 1
            if now and not was:
                a["voters"] = a.get("voters", 0) + 1
                total = total + 1
            elif was and not now:
                a["voters"] = max(a.get("voters", 1) - 1, 0)
                total = max(total - 1, 0)
            a["chosen"] = now
        p["chosen"] = chosen
        p["total"] = total

    def poll_changed(self, poll_id, results):
        hit = 0
        for k in self.msgs.keys():
            for m in self.msgs[k]:
                p = m.get("poll")
                if p is not None and p.get("id") == poll_id:
                    tgclient.apply_poll_results(p, results)
                    self.poll_msg = m
                    hit = 1
        if not hit:
            return
        if self.screen == "poll":
            self.show_poll(self.poll_msg)
        self.redraw_soon()

    def bot_buttons(self, m):
        btns = m.get("buttons") or []
        if not btns:
            return
        names = []
        for b in btns:
            names.append(one_line(to_u(b.get("text", "")), 60))
        i = appuifw.selection_list(names, 1)
        if i is None:
            return
        b = btns[i]
        key = self.chat_key
        if b.get("kind") == "callback":
            self.status(u"Sending...")

            def reload(self=self, key=key):
                if self.screen == "chat" and self.chat_key == key:
                    self.reload_chat()

            def ok(res, self=self, reload=reload):
                self.done_wait()
                t = to_u(res.get("message") or "")
                link = to_u(res.get("url") or "")
                if t:
                    appuifw.note(t, "info")
                elif link:
                    appuifw.note(u"Link:\n" + link, "info")
                # the bot's reply is a separate update: load it in a moment
                self.net.later(1, reload)
            self.client.bot_callback(key, m["id"], b.get("data", ""), ok, self.send_failed)
        else:
            appuifw.note(u"Link:\n" + to_u(b.get("url", "")), "info")

    def view_profile(self):
        key = self.chat_key
        if key is None:
            return
        self.screen = "profile"
        self.set_screen("large")
        v = tgui.ProfileView(self, key)
        self.view = v
        v.show()
        menu = [(u"Send message", self.back_to_chat)]
        if key[0] == "u" and self.client.peer(key)["kind"] == "user":
            menu.append((u"Telegram call", lambda self=self, k=key: self.telegram_call(k)))
        if key[0] == "u" and self.client.peer(key).get("phone"):
            menu.append((u"Call " + one_line(self.client.short_name(key), 20),
                         lambda self=self, k=key: self.call_peer(k)))
        d = self.dialog_for(key)
        if d is not None and self.client.peer(key)["kind"] != "self":
            if d.get("muted"):
                menu.append((u"Unmute", lambda self=self, k=key: self.mute(k, 0)))
            else:
                menu.append((u"Mute", lambda self=self, k=key: self.mute(k, 1)))
        menu.append((u"Back", self.back_to_chat))
        appuifw.app.menu = menu
        appuifw.app.exit_key_handler = self.back_to_chat

        def got(full, self=self, v=v):
            v.full = full
            if self.view is v:
                v.draw()
        self.client.get_profile(key, got, self.load_failed)

    def mute(self, key, flag):
        def ok(res, self=self, key=key, flag=flag):
            d = self.dialog_for(key)
            if d is not None:
                d["muted"] = flag
                self.dialogs_changed()
            if flag:
                self.show_toast(u"Muted", to_u(self.client.peer_name(key)))
            else:
                self.show_toast(u"Unmuted", to_u(self.client.peer_name(key)))
            if self.screen == "profile":
                self.view_profile()
        self.client.set_mute(key, flag, ok, self.load_failed)

    def chat_info(self):
        key = self.chat_key
        p = self.client.peer(key)
        lines = [to_u(self.client.peer_name(key)), to_u(self.client.status_text(key))]
        if p.get("username"):
            lines.append(u"@" + to_u(p["username"]))
        if p.get("phone"):
            lines.append(u"+" + to_u(p["phone"]))
        appuifw.note(u"\n".join(lines), "info")

    def back_to_chat(self):
        if self.chat_key is None:
            self.show_chats()
            return
        self.screen = "chat"
        self.set_screen("large")
        cv = self.chat_view
        if cv is None or cv.key_ != self.chat_key:
            cv = tgui.ChatView(self, self.chat_key)
            self.chat_view = cv
        self.view = cv
        self.view.show()
        self.update_chat_menu()
        appuifw.app.exit_key_handler = self.back_to_chats

    def back_to_chats(self):
        self.media.drop_jobs()
        self.chat_view = None
        self.show_chats()
        self.list_view.draw()

    def compose(self, reply_to=0, editing=None):
        key = self.chat_key
        if key is None or not self.client.can_write(key):
            return
        self.reply_to = reply_to
        self.editing = editing
        self.screen = "compose"
        self.set_screen("normal")
        title = u"To " + one_line(self.client.short_name(key), 24)
        if reply_to:
            q = self.quote_for(key, reply_to)
            title = u"Reply to " + one_line(q[0], 20)
        appuifw.app.title = title
        self.editor = appuifw.Text()
        try:
            self.editor.color = (16, 20, 24)
        except:
            pass
        if editing is not None:
            title = u"Edit message"
            appuifw.app.title = title
            self.editor.set(to_u(editing["text"]))
        else:
            self.editor.set(self.drafts.get(key, u""))
        appuifw.app.body = self.editor
        if not editing:
            self.client.set_typing(key)
            self.net.later(4, self.keep_typing)
        menu = [(u"Send", self.send_now), (u"Cancel", self.cancel_compose)]
        if self.clipboard:
            menu.insert(0, (u"Paste", self.paste))
        appuifw.app.menu = menu
        appuifw.app.exit_key_handler = self.cancel_compose

    def keep_typing(self):
        """messages.setTyping runs out after a few seconds, so renew it while the
        message box stays open with text in it."""
        if self.screen != "compose" or self.chat_key is None:
            return
        try:
            text = self.editor.get().strip()
        except:
            text = u""
        if text:
            self.client.set_typing(self.chat_key)
        self.net.later(4, self.keep_typing)

    def paste(self):
        if not self.clipboard:
            appuifw.note(u"Nothing has been copied yet.", "info")
            return
        try:
            cur = self.editor.get()
        except:
            cur = u""
        self.editor.set(cur + self.clipboard)

    def cancel_compose(self):
        if self.chat_key is not None:
            self.client.set_typing(self.chat_key, 1)
        text = self.editor.get().strip()
        if getattr(self, "editing", None) is not None:
            self.editing = None
            self.back_to_chat()
            return
        if text:
            self.drafts[self.chat_key] = text
        elif self.drafts.has_key(self.chat_key):
            del self.drafts[self.chat_key]
        self.back_to_chat()

    def send_now(self):
        text = self.editor.get().replace(u"\u2029", u"\n").strip()
        if self.chat_key is not None:
            self.client.set_typing(self.chat_key, 1)
        if not text:
            appuifw.note(u"Type a message first.", "info")
            return
        key = self.chat_key
        reply_to = self.reply_to
        editing = getattr(self, "editing", None)
        if editing is not None:
            self.editing = None
            self.back_to_chat()
            if text == to_u(editing["text"]).strip():
                return
            self.status(u"Saving...")
            self.client.edit_text(key, editing["id"], text,
                                  lambda r, self=self: self.done_wait(), self.send_failed)
            return
        if self.drafts.has_key(key):
            del self.drafts[key]
        self.back_to_chat()
        self.jump_latest()
        self.status(u"Sending...")
        self.client.send_text(key, text, lambda m, self=self, key=key, text=text:
                              self.sent(key, m, text), self.send_failed, reply_to)

    def sent(self, key, msg, text):
        self.done_wait()
        if msg is not None:
            self.add_message(key, msg)
        d = self.dialog_for(key)
        if d is not None:
            d["preview"] = to_b(text)
            d["sender"] = "You"
            d["out"] = 1
            d["date"] = self.now()
            if msg is not None:
                d["top"] = msg["id"]
            self.move_to_top(d)
            self.dialogs_changed()
        self.redraw()


    # ---------------------------------------------------------- attach file

    def attach_file(self, mode=None):
        """Pick a file and send it. mode "voice" / "video" sends it as a voice
        note or a round video note instead of a normal file."""
        key = self.chat_key
        if key is None or not self.client.can_write(key):
            return
        if self.upload is not None:
            appuifw.note(u"An upload is already running.", "info")
            return
        self.note_mode = mode
        start = self.cfg.get("last_dir") or ""
        try:
            start = unicode(start, "utf-8")
        except:
            start = u""
        self.screen = "filepick"
        self.set_screen("normal")
        self.picker = filepick.FilePickView(self, start, self.file_picked,
                                            self.pick_cancelled, self.remember_dir)
        self.view = self.picker
        self.picker.show()

    def remember_dir(self, path):
        try:
            p = path.encode("utf-8")
        except:
            return
        if self.cfg.get("last_dir") != p:
            self.cfg.set("last_dir", p)
            self.cfg.save()

    def pick_cancelled(self):
        self.picker = None
        self.note_mode = None
        self.back_to_chat()

    def file_picked(self, paths):
        self.picker = None
        self.back_to_chat()
        mode = self.note_mode
        self.note_mode = None
        if type(paths) is not type([]):
            paths = [paths]
        items = []
        total = 0
        for path in paths:
            try:
                size = int(os.path.getsize(path))
            except:
                appuifw.note(u"Cannot read the file.", "error")
                continue
            name = fileinfo.base_name(path)
            if size <= 0:
                appuifw.note(u"The file is empty.", "error")
                continue
            if size > 2000 * 1024 * 1024:
                appuifw.note(u"Telegram accepts files up to 2000 MB.", "error")
                continue
            items.append((path, name, size))
            total = total + size
        if not items:
            return
        if mode is not None and len(items) == 1:
            name0 = items[0][1]
            if mode == "voice" and not fileinfo.is_audio(name0):
                appuifw.note(u"Pick a recording (mp3, wav, amr or ogg) to send as a "
                             u"voice note.", "info")
                return
            if mode == "video" and not fileinfo.is_video(name0):
                appuifw.note(u"Pick a video (mp4 or 3gp) to send as a video note.", "info")
                return
        elif mode is not None:
            mode = None          # several files: send them as ordinary files
        title = one_line(items[0][1], 30)
        if len(items) > 1:
            title = u"%d files" % len(items)
        c = appuifw.popup_menu([u"Send", u"Add caption and send", u"Cancel"], title)
        if c is None or c == 2:
            return
        caption = u""
        if c == 1:
            caption = appuifw.query(u"Caption", "text", u"")
            if caption is None:
                caption = u""
            caption = caption.strip()[:1000]
        if len(items) == 1:
            q = u"Send " + one_line(items[0][1], 40) + u" (" + fileinfo.human_size(total) + u")?"
        else:
            q = u"Send %d files (%s)?" % (len(items), fileinfo.human_size(total))
        if not appuifw.query(q, "query"):
            return
        if total > 20 * 1024 * 1024:
            minutes = int((total / 102400 + 59) / 60)
            if minutes < 1:
                minutes = 1
            if not appuifw.query(u"This phone uploads slowly: about %d minutes?" % minutes,
                                 "query"):
                return
        self.queue = {"items": items, "i": 0, "caption": caption, "key": self.chat_key,
                      "sent": 0, "note": mode}
        self.next_upload()

    def next_upload(self):
        q = self.queue
        path, name, size = q["items"][q["i"]]
        caption = u""
        if q["i"] == 0:
            caption = q["caption"]
        self.start_upload(q["key"], path, name, size, caption, q.get("note"))

    def start_upload(self, key, path, name, size, caption, note=None):
        self.upload = {"name": name, "size": size, "pct": -1, "key": key, "h": None}
        self.upload_progress(0, size)
        reply_to = 0
        h = self.client.send_file(
            key, path, caption, reply_to,
            self.upload_progress,
            lambda r, self=self, name=name: self.upload_done(name),
            self.upload_failed, note)
        if self.upload is not None:
            self.upload["h"] = h
        self.update_menu_for_upload()

    def update_menu_for_upload(self):
        if self.screen == "chat":
            self.update_chat_menu()
        elif self.screen == "chats":
            self.update_list_menu()

    def upload_progress(self, done, total):
        u = self.upload
        if u is None:
            return
        pct = int(done * 100 / total)
        if pct == u["pct"]:
            return
        u["pct"] = pct
        q = self.queue
        pre = u"Uploading "
        if q is not None and len(q["items"]) > 1:
            pre = u"Uploading %d/%d " % (q["i"] + 1, len(q["items"]))
        self.busy = pre + one_line(u["name"], 24) + u" %d%% (%s)" % (
            pct, fileinfo.progress_sizes(done, total))
        self.redraw()

    def upload_done(self, name):
        self.upload = None
        q = self.queue
        if q is not None:
            q["sent"] = q["sent"] + 1
            q["i"] = q["i"] + 1
            if q["i"] < len(q["items"]):
                self.next_upload()
                return
        self.queue = None
        self.done_wait()
        if q is not None and q["sent"] > 1:
            self.show_toast(u"Sent %d files" % q["sent"], u"")
        else:
            self.show_toast(u"Sent", one_line(name, 40))
        self.update_menu_for_upload()

    def upload_failed(self, e):
        self.upload = None
        q = self.queue
        self.done_wait()
        if q is not None and q["i"] + 1 < len(q["items"]):
            q["i"] = q["i"] + 1
            if appuifw.query(u"Not sent: " + err_msg(e) + u" Continue with the rest?", "query"):
                self.next_upload()
                return
            self.queue = None
        else:
            self.queue = None
            appuifw.note(u"Not sent: " + err_msg(e), "error")
        self.update_menu_for_upload()

    def cancel_upload(self):
        u = self.upload
        if u is None:
            return
        if u["h"] is not None:
            u["h"].cancel()
        self.upload = None
        self.queue = None
        self.done_wait()
        self.show_toast(u"Upload cancelled", one_line(u["name"], 40))
        self.update_menu_for_upload()


    def send_failed(self, e):
        self.done_wait()
        appuifw.note(u"Not sent: " + err_msg(e), "error")

    def add_message(self, key, msg):
        msgs = self.msgs.get(key)
        if msgs is None:
            return
        for m in msgs:
            if m["id"] == msg["id"]:
                return
        view = self.view
        at_end = isinstance(view, tgui.ChatView) and view.key_ == key and view.at_bottom()
        msgs.append(msg)
        if at_end:
            view.sel = len(msgs)

    def move_to_top(self, d):
        try:
            self.dialogs.remove(d)
        except:
            pass
        if d.get("pinned"):
            self.dialogs.insert(0, d)
            return
        i = 0
        while i < len(self.dialogs) and self.dialogs[i].get("pinned"):
            i = i + 1
        self.dialogs.insert(i, d)

    def forward_message(self, m):
        keys = []
        names = []
        me = "u%d" % (self.client.me or 0)
        keys.append(me)
        names.append(u"Saved Messages")
        for r in self.dialogs:
            if r["key"] != me and self.client.can_write(r["key"]):
                keys.append(r["key"])
                names.append(one_line(self.client.peer_name(r["key"]), 40))
        i = appuifw.selection_list(names, 1)
        if i is None:
            return
        to = keys[i]
        self.status(u"Forwarding...")

        def ok(res, self=self, to=to):
            self.done_wait()
            self.show_toast(u"Forwarded", u"to " + to_u(self.client.peer_name(to)))
        self.client.forward(self.chat_key, [m["id"]], to, ok, self.send_failed)

    def delete_message(self, m):
        key = self.chat_key
        choices = [u"Delete for me"]
        revokes = [0]
        name = self.client.short_name(key)
        if key[0] == "h":
            choices = [u"Delete for everyone"]
            revokes = [1]
        elif m["out"] or key[0] == "c":
            if key[0] == "u" and key != "u%d" % (self.client.me or 0):
                choices.append(u"Delete for me and " + to_u(name))
                revokes.append(1)
            elif key[0] == "c":
                choices.append(u"Delete for everyone")
                revokes.append(1)
        elif key[0] == "u" and key != "u%d" % (self.client.me or 0):
            choices.append(u"Delete for me and " + to_u(name))
            revokes.append(1)
        i = appuifw.popup_menu(choices, u"Delete message?")
        if i is None:
            return
        self.status(u"Deleting...")
        mid = m["id"]

        def ok(res, self=self, key=key, mid=mid):
            self.done_wait()
            self.messages_deleted(key, [mid])
        self.client.delete_messages(key, [mid], revokes[i], ok, self.send_failed)

    def messages_deleted(self, key, ids):
        gone = {}
        for i in ids:
            gone[i] = 1
        changed = 0
        for k in self.msgs.keys():
            if key is not None and k != key:
                continue
            if key is None and k[0] == "h":
                continue   # channel ids are separate; those come with the key
            old = self.msgs[k]
            new = []
            for m in old:
                if not gone.has_key(m["id"]):
                    new.append(m)
            if len(new) != len(old):
                self.msgs[k] = new
                changed = 1
                v = self.view
                if isinstance(v, tgui.ChatView) and v.key_ == k and v.sel > len(new):
                    v.sel = len(new)
        if changed:
            self.redraw_soon()

    # ---------------------------------------------------------- Telegram calls

    def telegram_call(self, key):
        """Start an outgoing Telegram call (signalling only for now)."""
        if self.client.call_busy():
            appuifw.note(u"You are already in a call.", "info")
            return
        self.client.start_call(key)

    def call_yield(self):
        try:
            self.redraw()
            e32.ao_yield()
        except:
            pass

    def call_ready(self, cs):
        """Call reached 'connected': start the relay audio helper."""
        self.stop_call_audio()
        if self.client.call_version == "mimic":
            # probe mode: signalling only, the media protocol isn't built yet
            self.audio_state = "failed"
            self.log("call 2.7.7 probe: connected at the servers, no audio helper")
            self.call_changed()
            return
        try:
            if tgui.AUDIO_FACTORY is not None:
                ca = tgui.AUDIO_FACTORY()
            else:
                import callaudio
                ca = callaudio.CallAudio()
        except:
            self.audio_state = "failed"
            return
        self.call_audio = ca
        self.audio_state = "connecting"
        early = self.pending_sig
        self.pending_sig = []
        iap = 0
        try:
            iap = int(self.cfg.get("apid") or 0)
        except:
            iap = 0
        if self.client.call_version == "2.7.7":
            ok = ca.start_relay277(cs["kb"], cs["out"], cs["conns"], self.audio_changed, iap,
                                   self.audio_signal)
        else:
            ok = ca.start_relay(cs["kb"], cs["out"], cs["conns"], self.audio_changed, iap)
        ca.on_info = self.audio_info
        try:
            ca.set_agc(self.mic_boost())
            ca.set_btexp(self.bt_experimental())
            ca.set_btmode(self.bt_mode())
        except:
            self.log("mic boost / bt mode: " + err_text())
        if self.client.call_version == "2.7.7" and self.cfg.get("video_rx") != "0":
            try:
                # receive the peer's video (on by default since 0.15.0: software H.264 decoder in
                # tgvideo.exe; config video_rx = 0 turns it off). The decoder helper only starts
                # when the peer's video is actually on.
                ca.set_rx(1)
            except:
                self.log("set_rx: " + err_text())
        if self.client.call_version == "2.7.7":
            for sid, d in early:
                if sid == cs["id"]:
                    ca.send_signaling(d)
        self.log("call audio helper %s %s" % (ok and "started" or "NOT started",
                                              to_b(getattr(ca, "last_error", u""))))
        self.call_changed()

    def audio_signal(self, data):
        """The 2.7.7 helper has a signalling blob for the peer."""
        cs = self.client.cs
        if cs is not None and cs["state"] != "ended":
            self.client.send_signaling(cs, data)

    def call_signaling(self, data):
        """updatePhoneCallSignalingData for the current call."""
        ca = self.call_audio
        if ca is not None and hasattr(ca, "send_signaling"):
            ca.send_signaling(data)
        else:
            # the helper isn't up yet (call not connected): keep it for call_ready
            cs = self.client.cs
            if cs is not None and len(self.pending_sig) < 64:
                self.pending_sig.append((cs["id"], data))

    def audio_changed(self, name):
        if self.call_audio is None:
            return
        self.audio_state = name
        if name == "failed" or name == "ended":
            self.stop_call_video()
        cs = self.client.cs
        if cs is not None and cs["state"] != "ended":
            self.redraw()

    def call_peer_video_check(self):
        """The peer turned its video on: start the helper that decodes and shows it."""
        ca = self.call_audio
        if ca is None or not getattr(ca, "want_rx", 0) or not self.call_peer_video():
            return
        cv = self.call_video
        if cv is not None and getattr(cv, "rx_on", 0) and cv.helper_up():
            return                      # already showing (or waiting for) the peer's picture
        if cv is not None and getattr(cv, "rx_tried", 0) >= 3:
            return                      # the helper failed for the peer's picture 3 times this call
        try:
            import callvideo
            if cv is None:
                cv = callvideo.CallVideo(ca, self.call_video_changed, self.log)
                cv.show_self = self.call_show_self
                self.call_video = cv
            # also when our camera video already runs in the helper (0.15.0 bug: the peer's video
            # was never switched on in that order)
            cv.rx_tried = getattr(cv, "rx_tried", 0) + 1
            cv.start_rx()
        except:
            self.log("peer video helper: " + err_text())

    def audio_info(self):
        if self.call_audio is None:
            return
        try:
            self.call_peer_video_check()
        except:
            self.log("peer video check: " + err_text())
        ca = self.call_audio
        bt = getattr(ca, "bt_links", -1)
        if bt != getattr(self, "call_bt_seen", -1):
            self.call_bt_seen = bt
            self.log("bluetooth links %d, sound output %d (chosen by user: %d)" % (
                bt, getattr(ca, "want_route", -1), getattr(ca, "route_user", 0)))
            # 0.16.1: headsets are ignored (the helper keeps the phone's speaker/earpiece and
            # mic through tgbtroute); only the experimental mode reacts to them
            if (bt > 0 and self.bt_experimental() and self.cfg.get("bt_mode") is not None and
                    not getattr(ca, "route_user", 0) and getattr(ca, "want_route", 2) != 2):
                # experimental only, and only with a combination the user verified in the test
                self.call_set_route(2)
                try:
                    self.show_toast(u"Sound output", u"Bluetooth headset")
                except:
                    pass
            try:
                if self.screen == "call":
                    self.call_menu()
            except:
                pass
        rf = getattr(ca, "route_failed", -1)
        if rf >= 0:
            ca.route_failed = -1
            name = [u"Earpiece", u"Speaker", u"Bluetooth / auto"][rf % 3]
            self.log("sound output %d failed in the helper, previous route kept" % rf)
            try:
                self.show_toast(u"Sound output", name + u" not available, kept the previous output")
            except:
                pass
        cs = self.client.cs
        if cs is not None and cs["state"] != "ended" and self.screen == "call":
            self.redraw()

    def call_muted(self):
        ca = self.call_audio
        if ca is None:
            return 0
        return ca.want_mute

    def call_route(self):
        ca = self.call_audio
        if ca is None:
            return 1
        return ca.want_route

    def call_toggle_mute(self):
        ca = self.call_audio
        if ca is None:
            return
        ca.set_mute(not ca.want_mute)
        self.call_menu()
        self.redraw()

    def bt_experimental(self):
        """Experimental Bluetooth headset routing in calls (config bt_experimental = 1, off by
        default and not in Settings; see docs/CALL-277-SPEC.md). Off: headsets are not used,
        the sound stays on the phone speaker/earpiece and the phone microphone."""
        return self.cfg.get("bt_experimental") == "1"

    def call_bt(self):
        """A Bluetooth device is connected (the helper reads the phone's Bluetooth link count)."""
        ca = self.call_audio
        return ca is not None and getattr(ca, "bt_links", -1) > 0

    def call_route_name(self):
        """What the [2] Sound button and the menu show: the current output."""
        r = self.call_route()
        if r == 0:
            return u"Earpiece"
        if r == 1:
            return u"Speaker"
        if self.call_bt() and self.bt_experimental():
            ca = self.call_audio
            to = getattr(ca, "tel_out", -1)
            if to == 5 or to == -1:
                return u"Bluetooth"
            return u"Bluetooth?"            # asked for, not (yet) confirmed by the phone
        return u"Auto"

    def call_pick_route(self, n):
        """Sound output chosen by the user (no automatic Bluetooth switch after that)."""
        ca = self.call_audio
        if ca is not None:
            ca.route_user = 1
        self.call_set_route(n)
        try:
            self.call_menu()
        except:
            pass

    def call_set_route(self, n):
        """Sound output. Whatever goes wrong here never ends the call (0.15.1)."""
        ca = self.call_audio
        if ca is None:
            return
        try:
            ca.set_route(n)
        except:
            self.log("route %d: %s" % (n, err_text()))
            try:
                self.show_toast(u"Sound output", u"Could not switch the sound output")
            except:
                pass
        try:
            self.redraw()
        except:
            pass

    def call_cycle_route(self):
        ca = self.call_audio
        if ca is None:
            return
        ca.route_user = 1
        if self.bt_experimental():
            self.call_set_route((ca.want_route + 1) % 3)
        elif ca.want_route == 1:
            self.call_set_route(0)            # key 2: speaker <-> phone earpiece
        else:
            self.call_set_route(1)

    # ---------------------------------------------------------- send-only video (2.7.7 calls)

    def call_video_ok(self):
        """Video can be turned on: a connected 2.7.7 call with a running audio helper."""
        cs = self.client.cs
        ca = self.call_audio
        return (cs is not None and cs["state"] == "connected" and ca is not None and
                self.client.call_version == "2.7.7" and getattr(ca, "v277", 0) and
                hasattr(ca, "set_video"))

    def call_video_on(self):
        cv = self.call_video
        return cv is not None and cv.active()

    def call_video_text(self):
        """Our video state for the call screen: u"Video on - front camera", the failure text,
        or u"" when video is not in use."""
        cv = self.call_video
        if cv is not None:
            return cv.status_text()
        return u""

    def call_video_failed(self):
        cv = self.call_video
        return cv is not None and not cv.active() and cv.status_text() != u""

    def call_video_cam(self):
        """0 rear, 1 front (the camera video would use / uses)."""
        cv = self.call_video
        if cv is not None:
            return cv.cam
        return 1

    def call_peer_asked(self):
        ca = self.call_audio
        return ca is not None and getattr(ca, "peer_asked", 0) and not self.call_video_on()

    def call_peer_video(self):
        """1 when the peer's own video is on (we cannot show it on this phone)."""
        ca = self.call_audio
        return ca is not None and getattr(ca, "peer_video", -1) == 2

    def call_peer_frame(self):
        cv = self.call_video
        f = getattr(cv, "peer_frame", None)
        if f is None:
            return None
        return f()

    def call_peer_status(self):
        cv = self.call_video
        f = getattr(cv, "peer_status", None)
        if f is None:
            return u""
        return f()

    def call_peer_failed(self):
        cv = self.call_video
        f = getattr(cv, "peer_failed", None)
        return f is not None and f()

    def call_toggle_video(self):
        if self.call_video_on():
            cv = self.call_video
            f = getattr(cv, "stop_send", None)
            if f is not None:
                try:
                    f()
                except:
                    self.log("video off: " + err_text())
            else:
                self.stop_call_video()
        elif self.call_video_ok():
            try:
                import callvideo
                cv = self.call_video
                if cv is None:
                    cv = callvideo.CallVideo(self.call_audio, self.call_video_changed, self.log)
                    cv.show_self = self.call_show_self
                self.call_video = cv
                if getattr(self.call_audio, "peer_asked", 0):
                    self.call_audio.peer_asked = 0
                cv.start(callvideo.CAM_FRONT)
            except:
                self.call_video = None
                self.log("video start failed: " + err_text())
                appuifw.note(u"Video is not available: " + err_text(), "error")
        self.call_menu()
        self.redraw()

    def call_toggle_self(self):
        cv = self.call_video
        f = getattr(cv, "toggle_self", None)
        if f is not None and cv.active():
            f()
            self.call_show_self = getattr(cv, "show_self", 0) and 1 or 0
        self.call_menu()
        self.redraw()

    def call_self_shown(self):
        cv = self.call_video
        if cv is None:
            return self.call_show_self
        return getattr(cv, "show_self", 0)

    def call_switch_camera(self):
        cv = self.call_video
        if cv is not None and cv.active():
            cv.switch_camera()
        self.redraw()

    def call_video_changed(self):
        if self.screen == "call":
            cv = self.call_video
            sig = None
            if cv is not None:
                sig = (cv.state, cv.cam, cv.status_text(), self.call_peer_status(),
                       self.call_peer_frame() is not None)
            if sig != self.call_video_sig:
                self.call_video_sig = sig
                try:
                    self.call_menu()
                except:
                    pass
            self.redraw()

    def stop_call_video(self):
        cv = self.call_video
        if cv is None:
            return
        try:
            cv.stop()
        except:
            self.log("video stop: " + err_text())
        if self.screen == "call" and self.client.cs is not None:
            try:
                self.call_menu()
            except:
                pass

    def stop_call_audio(self):
        self.stop_call_video()
        self.call_video = None
        ca = self.call_audio
        self.call_audio = None
        self.audio_state = ""
        if ca is not None:
            try:
                ca.stop()
            except:
                pass

    def call_changed(self):
        cs = self.client.cs
        if cs is None:
            return
        if cs["state"] == "ended":
            self.stop_call_audio()
        if self.screen != "call":
            if isinstance(self.view, tgui.PlayerView):
                self.view.close()
            self.call_return = self.screen
            self.screen = "call"
            self.set_screen("large")
            self.view = tgui.CallView(self)
            self.view.show()
        self.call_menu()
        self.redraw()
        st = cs["state"]
        if st == "connected" and not self.call_timer:
            self.call_timer = 1
            self.net.later(1, self.call_tick)
        elif st == "ended":
            self.call_gen = self.call_gen + 1
            gen = self.call_gen

            def close(self=self, gen=gen):
                if self.call_gen == gen:
                    self.close_call()
            self.net.later(2, close)

    def call_tick(self):
        cs = self.client.cs
        if cs is not None and cs["state"] == "connected" and self.screen == "call":
            self.redraw()
            self.net.later(1, self.call_tick)
        else:
            self.call_timer = 0

    def call_menu(self):
        cs = self.client.cs
        st = cs["state"]
        if st == "incoming":
            appuifw.app.menu = [(u"Accept", self.call_primary), (u"Decline", self.call_hangup)]
            appuifw.app.exit_key_handler = self.call_hangup
        elif st == "ended":
            appuifw.app.menu = [(u"Close", self.close_call)]
            appuifw.app.exit_key_handler = self.close_call
        else:
            m = []
            if st == "connected" and self.call_audio is not None:
                if self.call_muted():
                    m.append((u"Unmute microphone", self.call_toggle_mute))
                else:
                    m.append((u"Mute microphone", self.call_toggle_mute))
                if self.call_bt() and self.bt_experimental():
                    # experimental: a Bluetooth headset is connected
                    m.append((u"Sound: " + self.call_route_name(), (
                        (u"Bluetooth headset", lambda self=self: self.call_pick_route(2)),
                        (u"Speaker", lambda self=self: self.call_pick_route(1)),
                        (u"Phone earpiece", lambda self=self: self.call_pick_route(0)))))
                else:
                    m.append((u"Sound: " + self.call_route_name(), (
                        (u"Speaker", lambda self=self: self.call_pick_route(1)),
                        (u"Phone earpiece", lambda self=self: self.call_pick_route(0)))))
                if self.call_bt() and self.bt_experimental():
                    m.append((u"Bluetooth test", self.call_bt_test))
                if self.call_video_ok():
                    if self.call_video_on():
                        m.append((u"Turn video off", self.call_toggle_video))
                        m.append((u"Switch camera", self.call_switch_camera))
                        if self.call_self_shown():
                            m.append((u"Hide my picture", self.call_toggle_self))
                        else:
                            m.append((u"Show my picture", self.call_toggle_self))
                    else:
                        m.append((u"Turn video on", self.call_toggle_video))
            m.append((u"Hang up", self.call_hangup))
            appuifw.app.menu = m
            appuifw.app.exit_key_handler = self.call_exit_key

    def call_exit_key(self):
        """Right softkey during a connected call. On some S60 builds it also fires when Cancel/Back
        closes the Options menu or a submenu, which must not end the call: ask first."""
        cs = self.client.cs
        if cs is None:
            return
        if cs["state"] == "connected":
            try:
                ok = appuifw.query(u"End the call?", "query")
            except:
                ok = None
            if not ok:
                self.redraw()
                return
            if self.client.cs is None or self.client.cs["state"] == "ended":
                return
        self.call_hangup()

    def call_primary(self):
        cs = self.client.cs
        if cs is None:
            return
        st = cs["state"]
        if st == "incoming":
            self.client.accept_call()
        elif st == "ended":
            self.close_call()
        else:
            self.call_hangup()

    def call_hangup(self):
        cs = self.client.cs
        if cs is None:
            return
        if cs["state"] == "ended":
            self.close_call()
        else:
            self.client.hang_up()

    def close_call(self):
        self.call_gen = self.call_gen + 1
        if self.client.cs is not None and self.client.cs["state"] == "ended":
            self.stop_call_audio()
        if self.screen != "call":
            return
        self.call_timer = 0
        ret = self.call_return
        if ret == "chat" and self.chat_key is not None:
            self.back_to_chat()
        elif ret == "profile" and self.chat_key is not None:
            self.view_profile()
        else:
            self.back_to_chats()

    # ---------------------------------------------------------- live updates

    def new_message(self, key, msg):
        self.add_message(key, msg)
        # only a chat on screen in front counts as read: in the background the message
        # stays unread and its notification is shown
        viewing = (self.focused and key == self.chat_key and
                   self.screen in ("chat", "text", "compose", "filepick", "poll"))
        if viewing and not msg["out"]:
            self.client.mark_read(key, msg["id"])
        d = self.dialog_for(key)
        if d is None:
            d = {"key": key, "unread": 0, "mark": 0, "preview": "", "sender": "",
                 "date": 0, "top": 0, "out": 0, "pinned": 0, "muted": 0, "read_out": 0,
                 "read_in": 0, "folder": 0}
        d["preview"] = self.client.preview(msg)
        if msg["service"]:
            d["preview"] = msg["text"]
        d["sender"] = ""
        if msg["out"]:
            d["sender"] = "You"
        elif self.client.is_group(key) and msg.get("from_key"):
            d["sender"] = self.client.short_name(msg["from_key"])
        d["date"] = msg["date"]
        d["top"] = msg["id"]
        d["out"] = msg["out"]
        if not msg["out"] and not viewing:
            d["unread"] = d.get("unread", 0) + 1
        self.move_to_top(d)
        self.dialogs_changed()
        if not msg["out"] and not viewing and not d.get("muted") and self.notify_mode():
            who = to_u(self.client.peer_name(key))
            text = to_u(self.client.preview(msg))
            if self.client.is_group(key) and msg.get("from_key"):
                text = to_u(self.client.short_name(msg["from_key"])) + u": " + text
            self.log("notify: %s focused=%d mode=%d" % (key, self.focused,
                                                       self.notify_mode()))
            if self.notify_mode() == 2 or not self.focused:
                # a global note (third argument) is shown by S60 even when RetroTele is
                # in the background, over whatever application is in front
                try:
                    appuifw.note(who + u"\n" + text, "info", 1)
                except TypeError:
                    try:
                        appuifw.note(who + u"\n" + text, "info")
                    except:
                        self.show_toast(who, text)
                except:
                    self.show_toast(who, text)
            else:
                self.show_toast(who, text)
        else:
            self.redraw_soon()

    def message_edited(self, key, msg):
        for m in self.msgs.get(key, []):
            if m["id"] == msg["id"]:
                m.update(msg)
                self.redraw_soon()
                return

    def read_changed(self, key, which, max_id, still):
        if key is None:
            return
        d = self.dialog_for(key)
        if which == "out":
            self.read_outs[key] = max(self.read_outs.get(key, 0), max_id)
            if d is not None:
                d["read_out"] = max(d.get("read_out", 0), max_id)
        elif d is not None and still >= 0:
            d["unread"] = still
            if not still:
                d["mark"] = 0
        self.dialogs_changed()
        self.redraw_soon()

    def peer_changed(self, key):
        if self.screen == "chats" or key == self.chat_key:
            self.rows_cache = {}
            self.redraw_soon()

    def refresh_needed(self):
        if self.loading_dialogs or time.time() - getattr(self, "dialogs_time", 0) < 60:
            return      # just loaded (a new session is announced right after start)
        if self.screen in ("chat", "text", "compose") and self.chat_key:
            self.reload_chat()
        self.client.get_dialogs(self.got_dialogs, self.load_failed, 20)

    # ---------------------------------------------------------- menus

    def bt_mode(self):
        """Bluetooth headset combination found by the in-call Bluetooth test (default 1)."""
        try:
            m = int(self.cfg.get("bt_mode", "1"))
        except:
            m = 1
        if m < 0 or m > 7:
            m = 1
        return m

    BT_COMBOS = [u"Bluetooth output only (0.15.2 way)",
                 u"Bluetooth output, then audio restarted",
                 u"Bluetooth (no device preference), audio restarted",
                 u"Bluetooth (loudspeaker device), audio restarted",
                 u"Bluetooth output, audio paused and resumed",
                 u"earpiece, then Bluetooth, audio restarted",
                 u"audio closed, Bluetooth output, audio opened",
                 u"audio closed, Bluetooth (no preference), audio opened"]

    def call_bt_test(self):
        """Guided test during a call with a Bluetooth headset: tries the 8 ways of moving the call
        audio to the headset, asks after each one, keeps the best for the next calls (bt_mode).
        Answers go to E:\\retrotele_btsweep.txt and into the call log with the audio levels."""
        ca = self.call_audio
        if ca is None or not self.call_bt():
            appuifw.note(u"No Bluetooth headset connected", "info")
            return
        if not appuifw.query(u"Bluetooth test: 8 short steps of about 8 s. In each, talk and "
                             u"listen, then answer. The call goes on. Start?", "query"):
            return
        answers = []
        best = -1
        ca.route_user = 1
        self.call_set_route(2)
        i = 0
        while i < len(self.BT_COMBOS):
            try:
                ca.set_btmode(i)
            except:
                self.log("bt test: " + err_text())
            self.show_toast(u"Bluetooth test %d/8" % (i + 1), self.BT_COMBOS[i])
            try:
                e32.ao_sleep(8)
            except:
                pass
            if self.call_audio is not ca:
                return                          # the call ended
            j = appuifw.popup_menu([u"Yes: I hear them and they hear me",
                                    u"I hear them, they don't hear me",
                                    u"They hear me, I don't hear them",
                                    u"No sound at all",
                                    u"Stop the test"],
                                   u"Test %d/8: works?" % (i + 1))
            if j is None or j == 4:
                break
            word = ["yes", "spk-only", "mic-only", "none"][j]
            answers.append((i, word))
            try:
                ca.bt_answer("%d %s" % (i, word))
            except:
                pass
            self.bt_sweep_log("combination %d (%s): %s" % (i, to_b(self.BT_COMBOS[i]), word))
            if j == 0 and best < 0:
                best = i
            i = i + 1
        if best >= 0:
            self.cfg.set("bt_mode", str(best))
            self.cfg.save()
            try:
                ca.set_btmode(best)
            except:
                pass
            self.bt_sweep_log("chosen: combination %d" % best)
            appuifw.note(u"Bluetooth: using way %d for calls from now on" % (best + 1), "info")
        else:
            try:
                ca.set_btmode(self.bt_mode())
            except:
                pass
            self.bt_sweep_log("no combination worked (answers %s)" % str(answers))
            appuifw.note(u"No way worked. Please send E:\\retrotele_callaudio.txt and "
                         u"E:\\retrotele_btsweep.txt", "info")

    def bt_sweep_log(self, line):
        self.log("bt test: " + line)
        for p in ("E:\\retrotele_btsweep.txt", "C:\\Data\\retrotele_btsweep.txt"):
            try:
                f = open(p, "a")
                f.write(time.strftime("%H:%M:%S ") + line + "\n")
                f.close()
                return
            except:
                pass

    def mic_boost(self):
        """0 off, 1 normal (default), 2 high: the digital mic gain in calls (tgcallaudio's AGC)."""
        try:
            m = int(self.cfg.get("mic_boost", "1"))
        except:
            m = 1
        if m < 0 or m > 2:
            m = 1
        return m

    def settings(self):
        ap = u"Auto-download pictures: on"
        if not self.auto_photos():
            ap = u"Auto-download pictures: off"
        default = "0"
        if tgcrypto.NATIVE:
            default = "1"
        fm = u"Fast mode: on"
        if self.cfg.get("verify", default) == "1":
            fm = u"Fast mode: off (full check)"
        mb = [u"Mic boost in calls: off", u"Mic boost in calls: normal", u"Mic boost in calls: high"][self.mic_boost()]
        nm = [u"Notifications: off", u"Notifications: banner",
              u"Notifications: system popup"][self.notify_mode()]
        items = [u"Access point", u"Telegram API key", u"Log out", u"Show data folder", ap, fm, mb,
                 nm]
        i = appuifw.popup_menu(items, u"Settings")
        if i == 0:
            if self.setup_ap(1):
                appuifw.note(u"Saved. Restart RetroTele to use the new access point.", "info")
        elif i == 1:
            if self.ask_api():
                appuifw.note(u"Saved. Restart RetroTele to use the new key.", "info")
        elif i == 2:
            if self.client is not None and appuifw.query(u"Log out of Telegram?", "query"):
                self.status(u"Logging out...")
                self.client.logout(lambda self=self: (self.done_wait(), self.logged_out()))
        elif i == 3:
            appuifw.note(u"Log: E:\\retrotele_log.txt, data: " + to_u(self.dir), "info")
        elif i == 5:
            if self.cfg.get("verify", default) == "1":
                self.cfg.set("verify", "0")
                appuifw.note(u"Fast mode on: received data is decrypted but its SHA-256 "
                             u"integrity hash is not checked (2-3x faster).", "info")
            else:
                self.cfg.set("verify", "1")
                appuifw.note(u"Full check on: every received message is verified (slower).",
                             "info")
            self.cfg.save()
            v = self.cfg.get("verify") == "1"
            self.client.verify = v
            for sess in self.client.sessions.values():
                sess.verify = v
        elif i == 6:
            j = appuifw.popup_menu([u"Off", u"Normal (automatic level)", u"High (quiet microphone)"],
                                   u"Mic boost in calls")
            if j is not None and j >= 0:
                self.cfg.set("mic_boost", str(j))
                self.cfg.save()
                ca = self.call_audio
                if ca is not None:
                    try:
                        ca.set_agc(j)
                    except:
                        pass
        elif i == 7:
            j = appuifw.popup_menu([u"Off", u"In-app banner",
                                    u"Popup for every message"], u"Notifications")
            if j is not None and j >= 0:
                self.cfg.set("notify", str(j))
                self.cfg.save()
                appuifw.note([u"Notifications off.",
                              u"Small banner inside RetroTele, and a small note when it is "
                              u"in the background.",
                              u"A small note for every new message, in front or in the "
                              u"background."][j], "info")
        elif i == 4:
            if self.auto_photos():
                self.cfg.set("auto_photos", "0")
            else:
                self.cfg.set("auto_photos", "1")
            self.cfg.save()
            self.redraw()

    def call_test(self):
        self.screen = "calltest"
        self.set_screen("large")
        v = tgui.CallTestView(self)
        self.view = v
        v.show()
        appuifw.app.menu = [(u"Start / stop echo test", v.toggle),
                            (u"Opus speed test", v.opus_test),
                            (u"Echo test via helper (unlocked phones)", v.helper_test),
                            (u"Echo test via VoIP (unlocked phones)", v.voip_test),
                            (u"Echo via call audio", v.echo_call_audio),
                            (u"Back", self.close_call_test)]
        appuifw.app.exit_key_handler = self.close_call_test

    def close_call_test(self):
        v = self.view
        if isinstance(v, tgui.CallTestView):
            v.stop()
        self.show_chats()

    def about(self):
        engine = u"Python crypto"
        if tgcrypto.NATIVE:
            engine = u"native crypto"
        appuifw.note(u"RetroTele " + VERSION + u" (" + engine + u")\nTelegram for S60 3rd Edition, written in "
                     u"Python. Left/right: switch tabs. Any number key in a chat: "
                     u"write a message.", "info")

    def exit(self):
        boot_log("exit requested")
        if self.upload is not None:
            if not appuifw.query(u"Cancel the upload and exit?", "query"):
                return
            self.cancel_upload()
        self.hash_job = None
        if isinstance(self.view, tgui.PlayerView):
            self.view.close()
        if isinstance(self.view, tgui.CallTestView):
            self.view.stop()
        if self.client is not None and self.client.call_busy():
            self.client.hang_up()
        self.stop_call_audio()
        if self.client is not None and self.client.me is not None:
            self.save_cache()
        self.net.cancel_all()
        # close the Telegram connections now: a socket with a pending read
        # keeps the app from closing (it stayed on a white screen)
        if self.client is not None:
            for sess in self.client.sessions.values():
                sess.state = "closed"
                sess.gen = sess.gen + 1
                c = getattr(sess, "conn", None)
                sess.conn = None
                if c is not None:
                    try:
                        c.hard_close()
                    except:
                        pass
        try:
            self.net.close_all()
        except:
            pass
        self.lock.signal()

    def run(self):
        appuifw.app.title = APP
        appuifw.app.exit_key_handler = self.exit
        try:
            appuifw.app.focus = self.app_focus
        except:
            pass
        self.set_screen("large")
        self.view = tgui.WelcomeView(self, [u"Starting..."])
        self.view.show()
        appuifw.app.menu = [(u"Exit", self.exit)]
        self.net.later(0.3, self.start)
        self.lock.wait()
        self.net.cancel_all()
        appuifw.app.menu = []
        appuifw.app.body = None
        boot_log("closing")
        try:
            appuifw.app.set_exit()   # end the app process when the script returns
        except:
            pass


def main():
    try:
        app = App()
        app.run()
        boot_log("app ended normally")
    except:
        show_crash("main")


if not getattr(appuifw, "FAKE", 0):
    main()
