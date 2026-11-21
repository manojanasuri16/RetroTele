# RetroTele: a small Telegram client for Python for S60 1.4.5 (Nokia N79 and
# other S60 3rd Edition phones). Talks MTProto 2.0 directly to Telegram's
# servers, no PC or proxy needed. Text chats: log in, chat list, read, write.
#
# Written for Python 2.2: no enumerate/sorted/sets/generators, no
# conditional expressions, no "with", no "except X as e", and substring
# tests use find(). The file also parses as Python 3 so it can be checked on
# a PC (tools/check_py22.py).

import sys
import appuifw
import e32

VERSION = u"0.1.2"  # single source of truth: build_sis.sh reads this
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
        self.screen = None          # "chats", "chat", "text", "compose", "login"
        self.dialogs = []
        self.chat_key = None
        self.messages = []
        self.has_older = 0
        self.is_online = 0
        self.busy = u""
        self.apo = None
        self.tz = 0
        self.hash_job = None

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
        self.set_title()
        try:
            e32.ao_yield()
        except:
            pass

    def set_title(self):
        t = APP
        if self.screen in ("chat", "compose", "text") and self.chat_key:
            t = to_u(self.client.peer_name(self.chat_key))
        if self.busy:
            t = self.busy
        elif not self.is_online:
            t = t + u" (offline)"
        try:
            appuifw.app.title = t
        except:
            pass

    def online(self, flag):
        self.is_online = flag
        if flag:
            self.busy = u""
            s = self.client.session()
            self.tz = local_offset(time.time() + s.time_offset)
        self.set_title()

    def hhmm(self, ts):
        if not ts:
            return u""
        t = time.gmtime(ts + self.tz)
        now = time.gmtime(time.time() + self.client.session().time_offset + self.tz)
        if t[:3] == now[:3]:
            return to_u(time.strftime("%H:%M", t))
        return to_u(time.strftime("%d.%m %H:%M", t))

    def wait_note(self, text):
        self.status(text)

    def done_wait(self):
        self.busy = u""
        self.set_title()

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
        self.status(u"Loading...")
        try:
            self.schema = tl.Schema(find_schema())
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
            appuifw.note(u"No access point chosen. Options > Settings > Access point.", "error")
        self.client = tgclient.Client(self.net, self.schema, self, self.store,
                                      self.cfg.get("api_id"), self.cfg.get("api_hash"),
                                      to_b(VERSION))
        self.status(u"Connecting to Telegram...")
        self.client.start()
        if self.client.logged_in():
            self.show_chats()
            self.load_dialogs()
        else:
            self.screen = "login"
            self.show_login_screen()
            self.net.later(0.5, self.login_phone)

    # ---------------------------------------------------------- login

    def show_login_screen(self):
        self.screen = "login"
        t = appuifw.Text()
        t.set(u"RetroTele " + VERSION + u"\n\nLog in with your Telegram phone number. "
              u"The code arrives in your Telegram app on another device, or by SMS.\n\n"
              u"Options > Log in to start.")
        appuifw.app.body = t
        appuifw.app.menu = [(u"Log in", self.login_phone),
                            (u"Settings", self.settings),
                            (u"Exit", self.exit)]
        appuifw.app.exit_key_handler = self.exit
        self.set_title()

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
        choice = appuifw.popup_menu([u"Enter password (phone, about 1 hour)",
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
        appuifw.note(u"Computing the password key. This takes a long time on the phone: "
                     u"keep RetroTele open and the phone charging.", "info")
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
        self.show_login_screen()

    def logged_in(self):
        self.done_wait()
        try:
            os.remove(self.dir + "2fa_salts.txt")
        except:
            pass
        appuifw.note(u"Logged in to Telegram.", "conf")
        self.show_chats()
        self.load_dialogs()

    def logged_out(self):
        appuifw.note(u"You were logged out of Telegram.", "error")
        self.show_login_screen()

    # ---------------------------------------------------------- chats list

    def chat_rows(self):
        rows = []
        for d in self.dialogs:
            name = one_line(d["name"], 40)
            if d["unread"]:
                name = u"(%d) %s" % (d["unread"], name)
            sub = self.hhmm(d["date"]) + u" " + one_line(d["preview"], 60)
            rows.append((name, sub))
        if not rows:
            rows.append((u"No chats yet", u"Options > Refresh"))
        return rows

    def show_chats(self):
        self.screen = "chats"
        self.chat_key = None
        self.chat_list = appuifw.Listbox(self.chat_rows(), self.open_selected)
        appuifw.app.body = self.chat_list
        appuifw.app.menu = [(u"Open", self.open_selected),
                            (u"Refresh", self.load_dialogs),
                            (u"New chat (@username)", self.new_chat),
                            (u"Contacts", self.contacts),
                            (u"Settings", self.settings),
                            (u"About", self.about),
                            (u"Exit", self.exit)]
        appuifw.app.exit_key_handler = self.exit
        self.set_title()

    def refresh_chats(self):
        if self.screen != "chats":
            return
        try:
            cur = self.chat_list.current()
        except:
            cur = 0
        rows = self.chat_rows()
        if cur >= len(rows):
            cur = len(rows) - 1
        self.chat_list.set_list(rows, max(cur, 0))
        self.set_title()

    def load_dialogs(self):
        self.status(u"Loading chats...")
        self.client.get_dialogs(self.got_dialogs, self.load_failed)

    def got_dialogs(self, rows):
        self.done_wait()
        self.dialogs = rows
        self.refresh_chats()

    def load_failed(self, e):
        self.done_wait()
        self.log("load failed: " + to_b(err_msg(e)))
        if self.screen == "chats" or self.screen == "chat":
            appuifw.note(err_msg(e), "error")

    def open_selected(self):
        if not self.dialogs:
            self.load_dialogs()
            return
        i = self.chat_list.current()
        if 0 <= i < len(self.dialogs):
            self.open_chat(self.dialogs[i]["key"])

    def new_chat(self):
        name = appuifw.query(u"Username (without @)", "text")
        if not name:
            return
        self.status(u"Looking up...")
        self.client.resolve_username(to_b(name).strip(),
                                     lambda key, self=self: (self.done_wait(),
                                                             self.open_chat(key)),
                                     self.load_failed)

    def contacts(self):
        self.status(u"Loading contacts...")
        self.client.get_contacts(self.got_contacts, self.load_failed)

    def got_contacts(self, rows):
        self.done_wait()
        if not rows:
            appuifw.note(u"No contacts.", "info")
            return
        names = []
        for k, n in rows:
            names.append(one_line(n, 40))
        i = appuifw.selection_list(names, 1)
        if i is not None:
            self.open_chat(rows[i][0])

    def dialog_for(self, key):
        for d in self.dialogs:
            if d["key"] == key:
                return d
        return None

    # ---------------------------------------------------------- one chat

    def open_chat(self, key):
        if key is None:
            return
        self.chat_key = key
        self.messages = []
        self.has_older = 0
        self.screen = "chat"
        self.msg_list = appuifw.Listbox([(u"Loading...", u"")], self.msg_selected)
        appuifw.app.body = self.msg_list
        appuifw.app.menu = [(u"Write message", self.compose),
                            (u"Read message", self.msg_selected),
                            (u"Older messages", self.load_older),
                            (u"Refresh", self.reload_chat),
                            (u"Back to chats", self.back_to_chats)]
        appuifw.app.exit_key_handler = self.back_to_chats
        self.set_title()
        self.reload_chat()

    def reload_chat(self):
        key = self.chat_key
        self.status(u"Loading messages...")
        self.client.get_history(key, lambda msgs, self=self, key=key:
                                self.got_history(key, msgs, 0), self.load_failed)

    def load_older(self):
        if not self.messages:
            return
        key = self.chat_key
        first = self.messages[0]["id"]
        self.status(u"Loading older...")
        self.client.get_history(key, lambda msgs, self=self, key=key:
                                self.got_history(key, msgs, 1), self.load_failed,
                                offset_id=first)

    def got_history(self, key, msgs, older):
        self.done_wait()
        if key != self.chat_key:
            return
        self.has_older = len(msgs) >= 20
        if older:
            self.messages = msgs + self.messages
            focus = len(msgs)
        else:
            self.messages = msgs
            focus = None
        self.refresh_chat(focus)
        if msgs and not older:
            last = msgs[-1]["id"]
            d = self.dialog_for(key)
            if d is not None and d["unread"]:
                d["unread"] = 0
                self.client.mark_read(key, last)
            elif d is None:
                self.client.mark_read(key, last)

    def msg_rows(self):
        rows = []
        if self.has_older:
            rows.append((u"\u2191 Older messages", u""))
        for m in self.messages:
            head = one_line(m["from"], 30) + u"  " + self.hhmm(m["date"])
            rows.append((head, one_line(m["text"] or u"(empty)", 100)))
        if self.client.is_channel(self.chat_key):
            rows.append((u"(channel)", u"Only admins can post here"))
        else:
            rows.append((u"\u270e Write message", u"Select to type"))
        return rows

    def refresh_chat(self, focus=None):
        if self.screen != "chat":
            return
        rows = self.msg_rows()
        if focus is None:
            focus = len(rows) - 1
        elif self.has_older:
            focus = focus + 1
        if focus >= len(rows):
            focus = len(rows) - 1
        self.msg_list.set_list(rows, max(focus, 0))
        self.set_title()

    def msg_selected(self):
        i = self.msg_list.current()
        off = 0
        if self.has_older:
            if i == 0:
                self.load_older()
                return
            off = 1
        j = i - off
        if j >= len(self.messages):
            if not self.client.is_channel(self.chat_key):
                self.compose()
            return
        if j >= 0:
            self.show_text(self.messages[j])

    def show_text(self, m):
        self.screen = "text"
        self.text_return = self.msg_list.current()
        t = appuifw.Text()
        t.set(to_u(m["from"]) + u", " + self.hhmm(m["date"]) + u"\n\n" + to_u(m["text"]))
        appuifw.app.body = t
        appuifw.app.menu = [(u"Reply", self.compose), (u"Back", self.back_to_chat)]
        appuifw.app.exit_key_handler = self.back_to_chat
        self.set_title()

    def back_to_chat(self):
        self.screen = "chat"
        appuifw.app.body = self.msg_list
        appuifw.app.menu = [(u"Write message", self.compose),
                            (u"Read message", self.msg_selected),
                            (u"Older messages", self.load_older),
                            (u"Refresh", self.reload_chat),
                            (u"Back to chats", self.back_to_chats)]
        appuifw.app.exit_key_handler = self.back_to_chats
        self.refresh_chat()
        self.set_title()

    def back_to_chats(self):
        self.show_chats()
        self.refresh_chats()

    def compose(self):
        self.screen = "compose"
        self.editor = appuifw.Text()
        draft = getattr(self, "draft", {}).get(self.chat_key, u"")
        self.editor.set(draft)
        appuifw.app.body = self.editor
        appuifw.app.menu = [(u"Send", self.send_now), (u"Cancel", self.cancel_compose)]
        appuifw.app.exit_key_handler = self.cancel_compose
        self.set_title()

    def cancel_compose(self):
        if not hasattr(self, "draft"):
            self.draft = {}
        self.draft[self.chat_key] = self.editor.get()
        self.back_to_chat()

    def send_now(self):
        text = self.editor.get().replace(u"\u2029", u"\n").strip()
        if not text:
            appuifw.note(u"Type a message first.", "info")
            return
        key = self.chat_key
        if hasattr(self, "draft") and self.draft.has_key(key):
            del self.draft[key]
        self.back_to_chat()
        self.status(u"Sending...")
        self.client.send_text(key, text, lambda m, self=self, key=key, text=text:
                              self.sent(key, m, text), self.send_failed)

    def sent(self, key, msg, text):
        self.done_wait()
        if msg is not None and key == self.chat_key:
            if not self.have_msg(msg["id"]):
                self.messages.append(msg)
                self.refresh_chat()
        d = self.dialog_for(key)
        if d is not None:
            d["preview"] = u"You: " + text
            d["date"] = int(time.time() + self.client.session().time_offset)
            self.dialogs.remove(d)
            self.dialogs.insert(0, d)

    def send_failed(self, e):
        self.done_wait()
        appuifw.note(u"Not sent: " + err_msg(e), "error")

    def have_msg(self, mid):
        for m in self.messages:
            if m["id"] == mid:
                return 1
        return 0

    # ---------------------------------------------------------- live updates

    def new_message(self, key, msg):
        if key == self.chat_key and self.screen in ("chat", "text", "compose"):
            if not self.have_msg(msg["id"]):
                self.messages.append(msg)
                if self.screen == "chat":
                    self.refresh_chat()
                if not msg["out"]:
                    self.client.mark_read(key, msg["id"])
        d = self.dialog_for(key)
        if d is None:
            d = {"key": key, "name": self.client.peer_name(key), "unread": 0,
                 "preview": "", "date": 0, "top": 0, "pinned": 0}
        else:
            self.dialogs.remove(d)
        preview = msg["text"]
        if key[0] != "u" and msg["from"]:
            preview = to_u(msg["from"]).split(u" ")[0] + u": " + to_u(preview)
        d["preview"] = preview
        d["date"] = msg["date"]
        if not msg["out"] and key != self.chat_key:
            d["unread"] = d["unread"] + 1
        self.dialogs.insert(0, d)
        if self.screen == "chats":
            self.refresh_chats()
        if not msg["out"] and key != self.chat_key:
            self.alert(key, msg)

    def alert(self, key, msg):
        """A short pop-up for a message in another chat."""
        if self.screen == "compose":
            return  # do not disturb typing
        try:
            appuifw.note(one_line(to_u(self.client.peer_name(key)) + u": " +
                                  to_u(msg["text"]), 60), "info")
        except:
            pass

    def refresh_needed(self):
        if self.screen == "chat":
            self.reload_chat()
        self.client.get_dialogs(self.got_dialogs, self.load_failed)

    # ---------------------------------------------------------- menus

    def settings(self):
        items = [u"Access point", u"Telegram API key", u"Log out", u"Show log file path"]
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
                self.client.logout(lambda self=self: (self.done_wait(),
                                                      self.show_login_screen()))
        elif i == 3:
            appuifw.note(u"Log: E:\\retrotele_log.txt, data: " + to_u(self.dir), "info")

    def about(self):
        appuifw.note(u"RetroTele " + VERSION + u"\nTelegram for S60 3rd Edition, "
                     u"written in Python. Text chats only.", "info")

    def exit(self):
        self.hash_job = None
        self.lock.signal()

    def run(self):
        appuifw.app.screen = "normal"
        appuifw.app.title = APP
        appuifw.app.exit_key_handler = self.exit
        t = appuifw.Text()
        t.set(u"RetroTele " + VERSION + u"\n\nStarting...")
        appuifw.app.body = t
        appuifw.app.menu = [(u"Exit", self.exit)]
        self.net.later(0.3, self.start)
        self.lock.wait()
        self.net.cancel_all()
        if self.client is not None:
            for s in self.client.sessions.values():
                s.state = "closed"
                s.gen = s.gen + 1
        appuifw.app.menu = []
        appuifw.app.body = None


def main():
    try:
        app = App()
        app.run()
        boot_log("app ended normally")
    except:
        show_crash("main")


if not getattr(appuifw, "FAKE", 0):
    main()
