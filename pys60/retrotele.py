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

VERSION = u"0.8.0"  # single source of truth: build_sis.sh reads this
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
    Works whether time.time() on the phone is UTC or local."""
    try:
        wall = calendar.timegm(time.localtime(time.time()))
        off = wall - server_now
        return int(round(off / 900.0)) * 900
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
        self.is_online = 0
        self.busy = u""
        self.apo = None
        self.tz = 0
        self.hash_job = None
        self.toast_text = None
        self.toast_gen = 0
        self.call_gen = 0
        self.call_timer = 0
        self.call_return = "chats"
        self.redraw_armed = 0
        self.cache_armed = 0
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
        tabs = list(BUILTIN_TABS)
        have = {}
        for t in tabs:
            have[t[0].lower()] = 1
        for f in self.filters:
            title = to_u(f["title"]).strip()
            if not title:
                title = u"Folder"
            if have.has_key(title.lower()):
                continue
            tabs.append((title, ("folder", f)))
        tabs.append((u"Archived", "archived"))
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
        return d

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
        if spec == "archived":
            src = self.archived or []
        for r in src:
            ok = 1
            kind = cl.peer(r["key"])["kind"]
            if spec == "unread":
                ok = r.get("unread") or r.get("mark")
            elif spec == "personal":
                ok = kind in ("user", "bot", "self")
            elif spec == "groups":
                ok = kind in ("group", "supergroup")
            elif spec == "channels":
                ok = kind == "channel"
            elif type(spec) is types.TupleType:
                ok = cl.in_filter(spec[1], r)
            if ok:
                rows.append(self.decorate(r))
        self.rows_cache[ck] = rows
        return rows

    def dialogs_changed(self):
        self.rows_cache = {}
        self.save_cache_soon()

    def empty_text(self, tab):
        spec = self.tabs()[tab][1]
        if spec == "contacts" and self.contacts is None:
            return u"Loading contacts..."
        if spec == "archived" and self.archived is None:
            return u"Loading..."
        if not self.dialogs and self.busy:
            return u"Loading chats..."
        if spec == "unread":
            return u"All caught up!"
        return u"No chats here"

    def tab_changed(self, tab):
        spec = self.tabs()[tab][1]
        if spec == "contacts" and self.contacts is None:
            self.client.get_contacts(self.got_contacts, self.load_failed)
        elif spec == "archived" and self.archived is None:
            self.client.get_dialogs(self.got_archived, self.load_failed, 25, None, 1)
        elif spec != "all" and spec != "contacts" and spec != "archived" and \
                len(self.dialogs) < 60:
            self.load_more_dialogs()
        self.update_list_menu()

    def got_contacts(self, keys):
        self.contacts = keys
        self.rows_cache = {}
        self.redraw()

    def got_archived(self, rows, more):
        self.archived = rows
        self.rows_cache = {}
        self.redraw()

    def near_end(self, tab):
        spec = self.tabs()[tab][1]
        if spec != "contacts" and spec != "archived" and self.more_dialogs:
            self.load_more_dialogs()

    def load_dialogs(self):
        self.status(u"Updating...")
        self.loading_dialogs = 1
        self.client.get_dialogs(self.got_dialogs, self.load_failed, 20)
        self.client.get_filters(self.got_filters, lambda e: None)

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
        if r is not None and r["key"][0] == "u" and self.client.peer(r["key"]).get("phone"):
            m.append((u"Call " + one_line(self.client.short_name(r["key"]), 20),
                      lambda self=self, k=r["key"]: self.call_peer(k)))
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
        rows = self.tab_rows(self.list_view.tab)
        n = 0
        for r in rows:
            if r.get("unread") and not r.get("contact_row"):
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
        if key[0] == "u" and self.client.peer(key)["kind"] == "user":
            m.append((u"Telegram call", lambda self=self, k=key: self.telegram_call(k)))
        if key[0] == "u" and self.client.peer(key).get("phone"):
            m.append((u"Call " + one_line(self.client.short_name(key), 20),
                      lambda self=self, k=key: self.call_peer(k)))
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
            if msgs and not older:
                d = self.dialog_for(key)
                if d is None or d.get("unread") or d.get("mark"):
                    self.client.mark_read(key, msgs[-1]["id"])
                if d is not None and (d.get("unread") or d.get("mark")):
                    d["unread"] = 0
                    d["mark"] = 0
                    self.dialogs_changed()

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
        if m.get("audio"):
            items.insert(0, u"Play")
            acts.insert(0, lambda self=self, m=m: self.play_audio(m))
        if not m["service"]:
            items.append(u"Forward")
            acts.append(lambda self=self, m=m: self.forward_message(m))
        if m.get("photo"):
            items.append(u"View picture")
            acts.append(lambda self=self, m=m: self.view_photo(m))
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
        i = appuifw.popup_menu(items)
        if i is not None:
            acts[i]()

    def play_audio(self, m):
        info = m["audio"]
        if info["voice"] or info["ext"] in ("ogg", "opus", "oga", "flac"):
            appuifw.note(u"This is an Opus/OGG recording, which the N79 can't play yet. "
                         u"Support is planned together with the native crypto module.",
                         "info")
            return
        path = self.media.folder + info["id"] + "." + info["ext"]
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
        appuifw.app.menu = [(u"Send", self.send_now), (u"Cancel", self.cancel_compose)]
        appuifw.app.exit_key_handler = self.cancel_compose

    def cancel_compose(self):
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

    def call_changed(self):
        cs = self.client.cs
        if cs is None:
            return
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
            appuifw.app.menu = [(u"Hang up", self.call_hangup)]
            appuifw.app.exit_key_handler = self.call_hangup

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
        viewing = key == self.chat_key and self.screen in ("chat", "text", "compose")
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
        if not msg["out"] and not viewing and not d.get("muted"):
            who = self.client.peer_name(key)
            text = to_u(self.client.preview(msg))
            if self.client.is_group(key) and msg.get("from_key"):
                text = to_u(self.client.short_name(msg["from_key"])) + u": " + text
            self.show_toast(to_u(who), text)
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
        items = [u"Access point", u"Telegram API key", u"Log out", u"Show data folder", ap, fm,
                 u"Call test (experimental)"]
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
        elif i == 6:
            self.call_test()
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
        self.hash_job = None
        if isinstance(self.view, tgui.PlayerView):
            self.view.close()
        if isinstance(self.view, tgui.CallTestView):
            self.view.stop()
        if self.client is not None and self.client.call_busy():
            self.client.hang_up()
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
