# Telegram client logic for RetroTele: sessions per data centre, login,
# chats, history, sending and live updates. No UI code here.
# Python 2.2 compatible.

import time
import sys
import binascii

import tgcrypto
import tl
import mtproto
from mtproto import RpcError

# ui object (the app) gets:
#   log(text), status(text)
#   new_message(key, msg)        msg as returned by norm_message()
#   refresh_needed()             updates were missed: reload what is shown
#   logged_out()                 the authorization is gone
#   online(flag)                 connection state of the main data centre


def hexs(s):
    return binascii.hexlify(s)


def unhex(s):
    return binascii.unhexlify(s)


def err_text():
    return str(sys.exc_info()[1])


class Store:
    """key=value text file (session data); written atomically enough for us."""
    def __init__(self, path):
        self.path = path
        self.d = {}
        try:
            f = open(path, "rb")
            for line in f.read().split("\n"):
                p = line.find("=")
                if p > 0:
                    self.d[line[:p].strip()] = line[p + 1:].strip()
            f.close()
        except:
            pass

    def get(self, k, default=None):
        return self.d.get(k, default)

    def set(self, k, v):
        if v is None:
            if self.d.has_key(k):
                del self.d[k]
        else:
            self.d[k] = str(v)

    def save(self):
        keys = self.d.keys()
        keys.sort()
        lines = []
        for k in keys:
            lines.append(k + "=" + self.d[k])
        try:
            f = open(self.path, "wb")
            f.write("\n".join(lines) + "\n")
            f.close()
        except:
            pass


MEDIA_LABELS = {
    "messageMediaPhoto": "[Photo]", "messageMediaGeo": "[Location]",
    "messageMediaContact": "[Contact]", "messageMediaUnsupported": "[Unsupported]",
    "messageMediaDocument": "[File]", "messageMediaWebPage": "",
    "messageMediaVenue": "[Venue]", "messageMediaGame": "[Game]",
    "messageMediaInvoice": "[Invoice]", "messageMediaGeoLive": "[Live location]",
    "messageMediaPoll": "[Poll]", "messageMediaDice": "[Dice]",
    "messageMediaStory": "[Story]", "messageMediaGiveaway": "[Giveaway]",
    "messageMediaPaidMedia": "[Paid media]", "messageMediaToDo": "[To-do list]",
}


def doc_label(doc):
    """[Sticker], [Voice message], [Video], [Music] or [File name.ext]."""
    if type(doc) is not type({}):
        return "[File]"
    name = ""
    for a in doc.get("attributes", []):
        n = a["_"]
        if n == "documentAttributeSticker":
            return "[Sticker " + a.get("alt", "") + "]"
        if n == "documentAttributeAnimated":
            return "[GIF]"
        if n == "documentAttributeAudio":
            if a.get("voice"):
                return "[Voice message %ds]" % a.get("duration", 0)
            t = a.get("title") or ""
            if a.get("performer"):
                t = a["performer"] + " - " + t
            return "[Music " + t + "]"
        if n == "documentAttributeVideo":
            if a.get("round_message"):
                return "[Video message]"
            return "[Video %ds]" % int(a.get("duration", 0))
        if n == "documentAttributeFilename":
            name = a.get("file_name", "")
    if name:
        return "[File " + name + "]"
    return "[File]"


def peer_key(p):
    if p is None:
        return None
    n = p["_"]
    if n == "peerUser":
        return "u%d" % p["user_id"]
    if n == "peerChat":
        return "c%d" % p["chat_id"]
    if n == "peerChannel":
        return "h%d" % p["channel_id"]
    return None


class Client:
    def __init__(self, net, schema, ui, store, api_id, api_hash, version="1.0.0"):
        self.net = net
        self.schema = schema
        self.w = tl.Writer(schema)
        self.ui = ui
        self.store = store
        self.api_id = int(api_id)
        self.api_hash = api_hash
        self.version = version
        self.sessions = {}
        self.main_dc = int(store.get("main_dc", "2"))
        self.users = {}
        self.chats = {}
        self.me = None
        uid = store.get("user_id")
        if uid:
            self.me = long(uid)

    def log(self, m):
        self.ui.log(m)

    # ---------------------------------------------------------- sessions

    def init_query(self, inner):
        w = self.w
        conn = w.obj({"_": "initConnection", "api_id": self.api_id,
                      "device_model": "Nokia N79", "system_version": "S60 3rd Edition FP2",
                      "app_version": "RetroTele " + self.version, "system_lang_code": "en",
                      "lang_pack": "", "lang_code": "en", "query": tl.Raw(inner)})
        return w.obj({"_": "invokeWithLayer", "layer": self.schema.layer,
                      "query": tl.Raw(conn)})

    def session(self, dc=None):
        if dc is None:
            dc = self.main_dc
        s = self.sessions.get(dc)
        if s is None:
            key = self.store.get("dc%d_key" % dc)
            salt = self.store.get("dc%d_salt" % dc)
            if key:
                key = unhex(key)
            if salt:
                salt = unhex(salt)
            off = float(self.store.get("time_offset", "0"))
            s = mtproto.Session(self.net, self.schema, self, dc, key, salt, off,
                                self.init_query)
            self.sessions[dc] = s
        return s

    def logged_in(self):
        return self.me is not None and self.store.get("dc%d_key" % self.main_dc)

    # events from mtproto.Session
    def status(self, text):
        self.ui.status(text)

    def saved(self, s):
        if s.auth_key:
            self.store.set("dc%d_key" % s.dc_id, hexs(s.auth_key))
            self.store.set("dc%d_salt" % s.dc_id, hexs(s.salt))
        else:
            self.store.set("dc%d_key" % s.dc_id, None)
            self.store.set("dc%d_salt" % s.dc_id, None)
        self.store.set("time_offset", "%d" % int(s.time_offset))
        self.store.save()

    def connected(self, s):
        if s.dc_id == self.main_dc:
            self.ui.online(1)
            if self.me is not None:
                # tell the server we want updates on this connection
                self.call({"_": "updates.getState"}, lambda r: None, lambda e: None)

    def disconnected(self, s, why):
        if s.dc_id == self.main_dc:
            self.ui.online(0)

    def update(self, obj):
        try:
            self.handle_updates(obj)
        except:
            self.log("update error: " + err_text())

    # ---------------------------------------------------------- calls

    def call(self, func, on_ok, on_err, dc=None, tries=0):
        def err(e, self=self, func=func, on_ok=on_ok, on_err=on_err, dc=dc, tries=tries):
            m = e.message
            if e.code == 303 and tries < 3:
                new_dc = int(m.split("_")[-1])
                self.log("%s: moving to DC %d" % (func["_"], new_dc))
                self.set_main_dc(new_dc)
                self.call(func, on_ok, on_err, None, tries + 1)
                return
            if e.code == 401 and m in ("AUTH_KEY_UNREGISTERED", "SESSION_REVOKED",
                                       "SESSION_EXPIRED", "USER_DEACTIVATED"):
                if self.me is not None:
                    self.forget_login()
                    self.ui.logged_out()
            on_err(e)

        def ok(res, self=self, on_ok=on_ok):
            self.collect(res)
            on_ok(res)
        self.session(dc).invoke(func, ok, err)

    def set_main_dc(self, dc):
        if dc == self.main_dc:
            return
        old = self.sessions.get(self.main_dc)
        self.main_dc = dc
        self.store.set("main_dc", dc)
        self.store.save()
        if old is not None and self.me is None:
            old.close()
            del self.sessions[old.dc_id]
        self.session(dc).start()

    def start(self):
        self.session().start()

    def forget_login(self):
        self.me = None
        self.store.set("user_id", None)
        self.store.save()

    def logout(self, done):
        def fin(*a):
            self.forget_login()
            for dc in self.sessions.keys():
                self.store.set("dc%d_key" % dc, None)
                self.store.set("dc%d_salt" % dc, None)
                self.sessions[dc].close()
            self.sessions = {}
            self.store.save()
            done()
        self.call({"_": "auth.logOut"}, fin, fin)

    # ---------------------------------------------------------- login

    def send_code(self, phone, on_ok, on_err):
        self.phone = phone
        self.call({"_": "auth.sendCode", "phone_number": phone, "api_id": self.api_id,
                   "api_hash": self.api_hash, "settings": {"_": "codeSettings"}},
                  on_ok, on_err)

    def resend_code(self, phone, code_hash, on_ok, on_err):
        self.call({"_": "auth.resendCode", "phone_number": phone,
                   "phone_code_hash": code_hash}, on_ok, on_err)

    def sign_in(self, phone, code_hash, code, on_ok, on_err):
        def ok(res, self=self, on_ok=on_ok, on_err=on_err):
            if res["_"] == "auth.authorizationSignUpRequired":
                on_err(RpcError(400, "SIGN_UP_REQUIRED"))
                return
            self.authorized(res)
            on_ok(res)
        self.call({"_": "auth.signIn", "phone_number": phone, "phone_code_hash": code_hash,
                   "phone_code": code}, ok, on_err)

    def get_password(self, on_ok, on_err):
        self.call({"_": "account.getPassword"}, on_ok, on_err)

    def check_password(self, srp_answer, on_ok, on_err):
        def ok(res, self=self, on_ok=on_ok):
            self.authorized(res)
            on_ok(res)
        self.call({"_": "auth.checkPassword", "password": srp_answer}, ok, on_err)

    def authorized(self, res):
        u = res.get("user") or {}
        self.me = u.get("id")
        self.store.set("user_id", self.me)
        self.store.save()
        self.call({"_": "updates.getState"}, lambda r: None, lambda e: None)

    # ---------------------------------------------------------- peers

    def collect(self, res):
        """Remembers users and chats (names, access hashes) from any result."""
        if type(res) is not type({}):
            return
        for u in res.get("users", []):
            if type(u) is type({}) and u.get("id") is not None:
                old = self.users.get(u["id"])
                if u.get("min") and old is not None and old.get("access_hash"):
                    continue
                self.users[u["id"]] = u
        for c in res.get("chats", []):
            if type(c) is type({}) and c.get("id") is not None:
                old = self.chats.get(c["id"])
                if c.get("min") and old is not None and old.get("access_hash"):
                    continue
                self.chats[c["id"]] = c
        if res.get("user"):
            u = res["user"]
            if type(u) is type({}) and u.get("id") is not None:
                self.users[u["id"]] = u

    def input_peer(self, key):
        kind = key[0]
        pid = long(key[1:])
        if kind == "u":
            if pid == self.me:
                return {"_": "inputPeerSelf"}
            u = self.users.get(pid) or {}
            return {"_": "inputPeerUser", "user_id": pid,
                    "access_hash": u.get("access_hash", 0)}
        if kind == "c":
            return {"_": "inputPeerChat", "chat_id": pid}
        c = self.chats.get(pid) or {}
        return {"_": "inputPeerChannel", "channel_id": pid,
                "access_hash": c.get("access_hash", 0)}

    def user_name(self, uid):
        if uid == self.me:
            return "You"
        u = self.users.get(uid)
        if u is None:
            return "User %d" % uid
        if u["_"] == "userEmpty":
            return "Deleted account"
        name = (u.get("first_name") or "") + " " + (u.get("last_name") or "")
        name = name.strip()
        if not name:
            name = u.get("username") or u.get("phone") or ("User %d" % uid)
        if u.get("deleted"):
            name = "Deleted account"
        return name

    def peer_name(self, key):
        if key is None:
            return "?"
        pid = long(key[1:])
        if key[0] == "u":
            if pid == self.me:
                return "Saved Messages"
            return self.user_name(pid)
        c = self.chats.get(pid)
        if c is None:
            return "Chat %d" % pid
        return c.get("title") or "Chat"

    def is_channel(self, key):
        """Broadcast channel (you usually cannot write)."""
        if key[0] != "h":
            return 0
        c = self.chats.get(long(key[1:])) or {}
        return c.get("broadcast") and not (c.get("creator") or c.get("admin_rights"))

    # ---------------------------------------------------------- messages

    def norm_message(self, m):
        """Telegram message -> {"id", "key", "out", "from", "text", "date"}."""
        n = m["_"]
        key = peer_key(m.get("peer_id"))
        d = {"id": m.get("id", 0), "key": key, "out": m.get("out", 0),
             "date": m.get("date", 0), "text": ""}
        if n == "messageEmpty":
            d["text"] = "[Deleted]"
            d["from"] = ""
            return d
        sender = peer_key(m.get("from_id"))
        if sender is None:
            if d["out"]:
                sender = "u%d" % (self.me or 0)
            elif key is not None and key[0] == "u":
                sender = key
            else:
                sender = key
        if d["out"]:
            d["from"] = "You"
        else:
            d["from"] = self.peer_name(sender)
        if n == "messageService":
            d["text"] = "[" + self.action_text(m.get("action") or {}) + "]"
            return d
        text = m.get("message") or ""
        media = m.get("media")
        if media is not None:
            mn = media["_"]
            label = MEDIA_LABELS.get(mn, "[" + mn[12:] + "]")
            if mn == "messageMediaDocument":
                label = doc_label(media.get("document"))
            elif mn == "messageMediaPoll":
                try:
                    q = media["poll"]["question"]["text"]
                    label = "[Poll: " + q + "]"
                except:
                    pass
            elif mn == "messageMediaGeo" or mn == "messageMediaVenue":
                try:
                    g = media["geo"]
                    label = label[:-1] + " %.5f,%.5f]" % (g["lat"], g["long"])
                except:
                    pass
            elif mn == "messageMediaContact":
                label = "[Contact " + (media.get("first_name") or "") + " " + \
                        (media.get("phone_number") or "") + "]"
            if label:
                if text:
                    text = label + " " + text
                else:
                    text = label
        if m.get("fwd_from"):
            text = "[Forwarded] " + text
        d["text"] = text
        return d

    def action_text(self, a):
        n = a.get("_", "")
        names = {"messageActionChatCreate": "created the group",
                 "messageActionChatEditTitle": "changed the title",
                 "messageActionChatEditPhoto": "changed the photo",
                 "messageActionChatAddUser": "added a member",
                 "messageActionChatDeleteUser": "removed a member",
                 "messageActionChatJoinedByLink": "joined by link",
                 "messageActionPinMessage": "pinned a message",
                 "messageActionPhoneCall": "call",
                 "messageActionChannelCreate": "created the channel",
                 "messageActionContactSignUp": "joined Telegram",
                 "messageActionHistoryClear": "history cleared",
                 "messageActionScreenshotTaken": "took a screenshot"}
        return names.get(n, n[13:])

    def get_dialogs(self, on_ok, on_err, limit=40):
        def ok(res, self=self, on_ok=on_ok):
            msgs = {}
            for m in res.get("messages", []):
                k = peer_key(m.get("peer_id"))
                msgs[(k, m.get("id"))] = m
            rows = []
            for dg in res.get("dialogs", []):
                if dg["_"] != "dialog":
                    continue
                key = peer_key(dg["peer"])
                if key is None:
                    continue
                top = msgs.get((key, dg.get("top_message")))
                preview = ""
                date = 0
                if top is not None:
                    nm = self.norm_message(top)
                    preview = nm["text"]
                    date = nm["date"]
                    if key[0] != "u" and nm["from"] and not self.is_channel(key):
                        preview = nm["from"].split(" ")[0] + ": " + preview
                rows.append({"key": key, "name": self.peer_name(key),
                             "unread": dg.get("unread_count", 0), "preview": preview,
                             "date": date, "top": dg.get("top_message", 0),
                             "pinned": dg.get("pinned", 0)})
            on_ok(rows)
        self.call({"_": "messages.getDialogs", "offset_date": 0, "offset_id": 0,
                   "offset_peer": {"_": "inputPeerEmpty"}, "limit": limit, "hash": 0},
                  ok, on_err)

    def get_history(self, key, on_ok, on_err, offset_id=0, limit=20):
        def ok(res, self=self, on_ok=on_ok):
            out = []
            for m in res.get("messages", []):
                out.append(self.norm_message(m))
            out.reverse()   # oldest first
            on_ok(out)
        self.call({"_": "messages.getHistory", "peer": self.input_peer(key),
                   "offset_id": offset_id, "offset_date": 0, "add_offset": 0,
                   "limit": limit, "max_id": 0, "min_id": 0, "hash": 0}, ok, on_err)

    def send_text(self, key, text, on_ok, on_err):
        if type(text) is type(u""):
            text = text.encode("utf-8")
        rid = tgcrypto.random_long()

        def ok(res, self=self, key=key, text=text, on_ok=on_ok):
            msg = {"id": res.get("id", 0), "key": key, "out": 1, "from": "You",
                   "text": text, "date": res.get("date", int(time.time()))}
            if res["_"] != "updateShortSentMessage":
                self.handle_updates(res, key)
                msg = None
            on_ok(msg)
        self.call({"_": "messages.sendMessage", "peer": self.input_peer(key),
                   "message": text, "random_id": rid}, ok, on_err)

    def mark_read(self, key, max_id):
        if key[0] == "h":
            c = self.chats.get(long(key[1:])) or {}
            f = {"_": "channels.readHistory", "max_id": max_id,
                 "channel": {"_": "inputChannel", "channel_id": long(key[1:]),
                             "access_hash": c.get("access_hash", 0)}}
        else:
            f = {"_": "messages.readHistory", "peer": self.input_peer(key), "max_id": max_id}
        self.call(f, lambda r: None, lambda e: None)

    def resolve_username(self, name, on_ok, on_err):
        def ok(res, self=self, on_ok=on_ok):
            on_ok(peer_key(res.get("peer")))
        if name[:1] == "@":
            name = name[1:]
        self.call({"_": "contacts.resolveUsername", "username": name}, ok, on_err)

    def get_contacts(self, on_ok, on_err):
        def ok(res, self=self, on_ok=on_ok):
            rows = []
            for c in res.get("contacts", []):
                rows.append(("u%d" % c["user_id"], self.user_name(c["user_id"])))
            rows.sort(lambda a, b: cmp(a[1].lower(), b[1].lower()))
            on_ok(rows)
        self.call({"_": "contacts.getContacts", "hash": 0}, ok, on_err)

    # ---------------------------------------------------------- updates

    def handle_updates(self, u, sent_key=None):
        n = u["_"]
        if n == "newSession" or n == "updatesTooLong":
            self.ui.refresh_needed()
            return
        if n == "updateShortMessage":
            uid = u["user_id"]
            key = "u%d" % uid
            if u.get("out"):
                frm = "You"
            else:
                frm = self.user_name(uid)
            self.ui.new_message(key, {"id": u["id"], "key": key, "out": u.get("out", 0),
                                      "from": frm, "text": u.get("message", ""),
                                      "date": u.get("date", 0)})
            if not self.users.has_key(uid):
                self.ui.refresh_needed()
            return
        if n == "updateShortChatMessage":
            key = "c%d" % u["chat_id"]
            if u.get("out"):
                frm = "You"
            else:
                frm = self.user_name(u["from_id"])
            self.ui.new_message(key, {"id": u["id"], "key": key, "out": u.get("out", 0),
                                      "from": frm, "text": u.get("message", ""),
                                      "date": u.get("date", 0)})
            return
        if n == "updateShort":
            self.one_update(u["update"])
            return
        if n == "updates" or n == "updatesCombined":
            self.collect(u)
            for x in u.get("updates", []):
                self.one_update(x)
            return
        if n[:6] == "update":
            self.one_update(u)

    def one_update(self, x):
        n = x["_"]
        if n == "updateNewMessage" or n == "updateNewChannelMessage":
            m = self.norm_message(x["message"])
            if m["key"] is not None:
                self.ui.new_message(m["key"], m)
        elif n == "updateChannelTooLong":
            self.ui.refresh_needed()


# ---------------------------------------------------------------- 2FA (SRP)

def srp_answer(pw, x_hash):
    """Builds inputCheckPasswordSRP from account.password and the slow
    password hash x (see pbkdf2 note in retrotele.py / tools/tg2fa.py)."""
    algo = pw["current_algo"]
    g = algo["g"]
    p_bytes = algo["p"]
    p = tgcrypto.bytes_to_long(p_bytes)
    sha256 = tgcrypto.sha256
    pad = lambda n: tgcrypto.long_to_bytes(n, 256)
    g_b = pw["srp_B"]
    gb = tgcrypto.bytes_to_long(g_b)
    x = tgcrypto.bytes_to_long(x_hash)
    k = tgcrypto.bytes_to_long(sha256(p_bytes + pad(g)))
    while 1:
        a = tgcrypto.bytes_to_long(tgcrypto.random_bytes(256))
        ga = pow(g, a, p)
        if ga > 0 and ga < p:
            break
    g_a = pad(ga)
    u = tgcrypto.bytes_to_long(sha256(g_a + pad(gb)))
    gx = pow(g, x, p)
    kgx = (k * gx) % p
    t = (gb - kgx) % p
    sa = pow(t, a + u * x, p)
    k_a = sha256(pad(sa))
    hp = sha256(p_bytes)
    hg = sha256(pad(g))
    m1 = sha256(tgcrypto.xor_bytes(hp, hg) + sha256(algo["salt1"]) + sha256(algo["salt2"]) +
                g_a + pad(gb) + k_a)
    return {"_": "inputCheckPasswordSRP", "srp_id": pw["srp_id"], "A": g_a, "M1": m1}
