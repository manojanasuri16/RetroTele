# Telegram client logic for RetroTele: sessions per data centre, login,
# chats and folders, history, sending, read state and live updates.
# No UI code here. Python 2.2 compatible.

import os
import time
import sys
import binascii

import tgcrypto
import tl
import mtproto
import fileinfo
from mtproto import RpcError

# ui object (the app) gets:
#   log(text), status(text)
#   new_message(key, msg)        msg as returned by norm_message()
#   message_edited(key, msg)
#   read_changed(key)            read ticks / unread counts changed
#   peer_changed(key)            name / online status changed
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
    """key=value text file (session data and settings)."""
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
    "messageMediaPhoto": "Photo", "messageMediaGeo": "Location",
    "messageMediaContact": "Contact", "messageMediaUnsupported": "Unsupported message",
    "messageMediaDocument": "File", "messageMediaWebPage": "",
    "messageMediaVenue": "Venue", "messageMediaGame": "Game",
    "messageMediaInvoice": "Invoice", "messageMediaGeoLive": "Live location",
    "messageMediaPoll": "Poll", "messageMediaDice": "Dice",
    "messageMediaStory": "Story", "messageMediaGiveaway": "Giveaway",
    "messageMediaPaidMedia": "Paid media", "messageMediaToDo": "To-do list",
}


def doc_label(doc):
    """Sticker, Voice message, Video, Music or the file name."""
    if type(doc) is not type({}):
        return "File"
    name = ""
    for a in doc.get("attributes", []):
        n = a["_"]
        if n == "documentAttributeSticker":
            return ("Sticker " + a.get("alt", "")).strip()
        if n == "documentAttributeAnimated":
            return "GIF"
        if n == "documentAttributeAudio":
            if a.get("voice"):
                return "Voice message %d:%02d" % (a.get("duration", 0) / 60,
                                                  a.get("duration", 0) % 60)
            t = a.get("title") or ""
            if a.get("performer"):
                t = a["performer"] + " - " + t
            return ("Music " + t).strip()
        if n == "documentAttributeVideo":
            d = int(a.get("duration", 0))
            if a.get("round_message"):
                return "Video message %d:%02d" % (d / 60, d % 60)
            return "Video %d:%02d" % (d / 60, d % 60)
        if n == "documentAttributeFilename":
            name = a.get("file_name", "")
    if name:
        return name
    return "File"


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


def input_peer_key(p, me):
    """InputPeer (as found in folders) -> key."""
    n = p.get("_")
    if n == "inputPeerSelf":
        return "u%d" % (me or 0)
    if n == "inputPeerUser":
        return "u%d" % p["user_id"]
    if n == "inputPeerChat":
        return "c%d" % p["chat_id"]
    if n == "inputPeerChannel":
        return "h%d" % p["channel_id"]
    return None


def text_of(t):
    """TextWithEntities or plain string -> string."""
    if type(t) is type({}):
        return t.get("text", "")
    return t or ""


SIZE_ORDER = ["m", "x", "s", "y", "c", "b", "a"]


def pick_size(sizes):
    """(type, w, h, stripped bytes) of the best preview size (about 320 px)."""
    best = None
    stripped = None
    for sz in sizes or []:
        n = sz.get("_")
        if n == "photoStrippedSize":
            stripped = sz.get("bytes")
        elif n in ("photoSize", "photoSizeProgressive", "photoCachedSize"):
            t = sz.get("type", "")
            if t in SIZE_ORDER and (best is None or
                                    SIZE_ORDER.index(t) < SIZE_ORDER.index(best[0])):
                best = (t, sz.get("w", 0), sz.get("h", 0))
    return best, stripped


def photo_preview(ph):
    if type(ph) is not type({}) or ph.get("_") != "photo":
        return None
    best, stripped = pick_size(ph.get("sizes"))
    if best is None:
        return None
    return {"id": "p%d%s" % (ph["id"], best[0]), "dc": ph.get("dc_id", 0), "w": best[1],
            "h": best[2], "stripped": stripped, "badge": "",
            "loc": {"_": "inputPhotoFileLocation", "id": ph["id"],
                    "access_hash": ph["access_hash"], "file_reference": ph["file_reference"],
                    "thumb_size": best[0]}}


def doc_preview(doc, label):
    """Preview picture of a video, GIF or file (its JPEG thumbnail), if any."""
    if type(doc) is not type({}) or doc.get("_") != "document":
        return None
    mime = doc.get("mime_type", "")
    if mime.find("webp") >= 0 or mime.find("tgsticker") >= 0:
        return None
    best, stripped = pick_size(doc.get("thumbs"))
    if best is None:
        return None
    badge = label
    if mime[:6] == "image/" and label[:3] != "GIF":
        badge = ""
    return {"id": "d%d%s" % (doc["id"], best[0]), "dc": doc.get("dc_id", 0), "w": best[1],
            "h": best[2], "stripped": stripped, "badge": badge,
            "loc": {"_": "inputDocumentFileLocation", "id": doc["id"],
                    "access_hash": doc["access_hash"], "file_reference": doc["file_reference"],
                    "thumb_size": best[0]}}


AUDIO_EXT = {"audio/mpeg": "mp3", "audio/mp3": "mp3", "audio/mp4": "m4a",
             "audio/x-m4a": "m4a", "audio/m4a": "m4a", "audio/aac": "aac",
             "audio/ogg": "ogg", "audio/opus": "ogg", "audio/wav": "wav",
             "audio/x-wav": "wav", "audio/amr": "amr", "audio/3gpp": "3gp",
             "audio/flac": "flac", "audio/x-flac": "flac"}


def audio_info(doc):
    """Download and playback details of a music file or voice message."""
    if type(doc) is not type({}) or doc.get("_") != "document":
        return None
    mime = doc.get("mime_type", "")
    a = None
    name = ""
    for at in doc.get("attributes", []):
        if at["_"] == "documentAttributeAudio":
            a = at
        elif at["_"] == "documentAttributeFilename":
            name = at.get("file_name", "")
    if a is None and mime[:6] != "audio/":
        return None
    ext = AUDIO_EXT.get(mime, "")
    if not ext and name.find(".") > 0:
        ext = name.split(".")[-1].lower()
    if not ext:
        ext = "mp3"
    a = a or {}
    title = a.get("title") or name or "Audio"
    if a.get("voice"):
        title = "Voice message"
    return {"id": "f%d" % doc["id"], "dc": doc.get("dc_id", 0), "size": doc.get("size", 0),
            "mime": mime, "ext": ext, "voice": a.get("voice", 0),
            "duration": int(a.get("duration", 0)), "title": title,
            "performer": a.get("performer") or "",
            "loc": {"_": "inputDocumentFileLocation", "id": doc["id"],
                    "access_hash": doc["access_hash"], "file_reference": doc["file_reference"],
                    "thumb_size": ""}}


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
        self.peers = {}        # key -> info dict (see peer_info)
        self.cs = None         # current Telegram call
        self.dh = None         # cached (g, p) from messages.getDhConfig
        self.verify = 0        # full msg_key check on received data (slow)
        self.call_protocol = self.CALL_PROTOCOL
        self.call_version = "2.4.4"
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
            s.verify = self.verify
            self.sessions[dc] = s
        return s

    def logged_in(self):
        return self.me is not None and self.store.get("dc%d_key" % self.main_dc)

    def server_time(self):
        return int(time.time() + self.session().time_offset)

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
                self.set_online(1)

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
            if e.code == 303 and tries < 3 and (m[:13] == "FILE_MIGRATE_" or dc is not None):
                self.file_call(int(m.split("_")[-1]), func, on_ok, on_err, tries + 1)
                return
            if dc is not None and dc != self.main_dc:
                if e.code == 401 and tries < 2:
                    self.store.set("dc%d_auth" % dc, None)
                    self.file_call(dc, func, on_ok, on_err, tries + 1)
                    return
                on_err(e)
                return
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

    def file_call(self, dc, func, on_ok, on_err, tries=0):
        """Calls func on data centre dc (where a file lives), copying the login
        there first (auth.exportAuthorization / importAuthorization)."""
        if not dc or dc == self.main_dc:
            self.call(func, on_ok, on_err, None, tries)
            return
        if self.store.get("dc%d_auth" % dc) == str(self.me):
            self.call(func, on_ok, on_err, dc, tries)
            return

        def exported(res, self=self, dc=dc, func=func, on_ok=on_ok, on_err=on_err,
                     tries=tries):
            def imported(r, self=self, dc=dc, func=func, on_ok=on_ok, on_err=on_err,
                         tries=tries):
                self.store.set("dc%d_auth" % dc, str(self.me))
                self.store.save()
                self.call(func, on_ok, on_err, dc, tries)
            self.session(dc).invoke({"_": "auth.importAuthorization", "id": res["id"],
                                     "bytes": res["bytes"]}, imported, on_err)
        self.log("copying login to DC %d" % dc)
        self.call({"_": "auth.exportAuthorization", "dc_id": dc}, exported, on_err)

    def download(self, info, path, on_ok, on_err, progress=None):
        """Downloads a file (info from photo_preview / audio_info) to path.
        Pieces go to path + ".part" as they arrive, so an interrupted download
        continues where it stopped; the file is renamed when complete.
        progress(done_bytes) is called after every 32 KB piece."""
        import os
        CH = 32768          # small pieces: less memory per decrypted packet
        part = path + ".part"
        start = 0
        try:
            if os.path.exists(part):
                start = (os.path.getsize(part) / CH) * CH
                f = open(part, "r+b")
                f.truncate(start)
                f.close()
            else:
                open(part, "wb").close()
        except:
            on_err(RpcError(-4, "cannot write " + part))
            return
        state = {"offset": start}

        def got(res, self=self, info=info, path=path, part=part, on_ok=on_ok,
                on_err=on_err, progress=progress, state=state):
            data = res.get("bytes") or ""
            try:
                f = open(part, "ab")
                f.write(data)
                f.close()
            except:
                on_err(RpcError(-4, "cannot write " + part))
                return
            state["offset"] = state["offset"] + len(data)
            if progress is not None:
                progress(state["offset"])
            if len(data) == CH and state["offset"] < 1600 * CH:
                fetch(state["offset"])
                return
            try:
                if os.path.exists(path):
                    os.remove(path)
                os.rename(part, path)
            except:
                on_err(RpcError(-4, "cannot save " + path))
                return
            on_ok(path)

        def fetch(offset, self=self, info=info, got=got, on_err=on_err):
            self.file_call(info["dc"], {"_": "upload.getFile", "location": info["loc"],
                                        "offset": offset, "limit": CH}, got, on_err)
        if progress is not None and start:
            progress(start)
        fetch(start)

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

    def set_online(self, flag):
        """Shows you as online (or last seen now) to your contacts."""
        self.call({"_": "account.updateStatus", "offline": not flag},
                  lambda r: None, lambda e: None)

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
        """Remembers users and chats (names, access hashes, photos) from any result."""
        if type(res) is not type({}):
            return
        for u in res.get("users", []):
            self.add_user(u)
        for c in res.get("chats", []):
            self.add_chat(c)
        if res.get("user"):
            self.add_user(res["user"])

    def add_user(self, u):
        if type(u) is not type({}) or u.get("id") is None:
            return
        key = "u%d" % u["id"]
        old = self.peers.get(key)
        if u.get("min") and old is not None:
            return    # min objects lack the access hash and phone
        if u["_"] == "userEmpty":
            name = "Deleted account"
        else:
            name = ((u.get("first_name") or "") + " " + (u.get("last_name") or "")).strip()
        if u.get("deleted"):
            name = "Deleted account"
        if not name:
            name = u.get("username") or u.get("phone") or ("User %d" % u["id"])
        kind = "user"
        if u.get("bot"):
            kind = "bot"
        if u.get("self") or u["id"] == self.me:
            kind = "self"
        photo = None
        photo_id = 0
        photo_dc = 0
        p = u.get("photo")
        if type(p) is type({}):
            photo = p.get("stripped_thumb")
            photo_id = p.get("photo_id", 0)
            photo_dc = p.get("dc_id", 0)
        status = u.get("status")
        if status is None and old is not None:
            status = old.get("status")
        info = {"name": name, "kind": kind, "hash": u.get("access_hash", 0),
                "phone": u.get("phone") or "", "contact": u.get("contact", 0),
                "username": u.get("username") or "", "photo": photo,
                "photo_id": photo_id, "photo_dc": photo_dc,
                "status": status, "members": 0}
        if old is not None:
            if not info["hash"]:
                info["hash"] = old.get("hash", 0)
            if not info["phone"]:
                info["phone"] = old.get("phone", "")
        self.peers[key] = info

    def add_chat(self, c):
        if type(c) is not type({}) or c.get("id") is None:
            return
        n = c["_"]
        if n in ("chat", "chatForbidden", "chatEmpty"):
            key = "c%d" % c["id"]
            kind = "group"
        else:
            key = "h%d" % c["id"]
            kind = "channel"
            if c.get("megagroup") or c.get("gigagroup"):
                kind = "supergroup"
        old = self.peers.get(key)
        if c.get("min") and old is not None:
            return
        photo = None
        photo_id = 0
        photo_dc = 0
        p = c.get("photo")
        if type(p) is type({}):
            photo = p.get("stripped_thumb")
            photo_id = p.get("photo_id", 0)
            photo_dc = p.get("dc_id", 0)
        info = {"name": c.get("title") or "Chat", "kind": kind,
                "photo_id": photo_id, "photo_dc": photo_dc,
                "hash": c.get("access_hash", 0), "phone": "", "contact": 0,
                "username": c.get("username") or "", "photo": photo, "status": None,
                "members": c.get("participants_count") or 0,
                "can_write": not (kind == "channel" and not (c.get("creator") or
                                                              c.get("admin_rights"))),
                "left": c.get("left", 0)}
        if old is not None:
            if not info["hash"]:
                info["hash"] = old.get("hash", 0)
            if not info["members"]:
                info["members"] = old.get("members", 0)
        self.peers[key] = info

    def peer(self, key):
        p = self.peers.get(key)
        if p is None:
            kind = "user"
            if key[:1] == "c":
                kind = "group"
            elif key[:1] == "h":
                kind = "channel"
            p = {"name": "Unknown", "kind": kind, "hash": 0, "phone": "", "contact": 0,
                 "username": "", "photo": None, "status": None, "members": 0}
        return p

    def input_peer(self, key):
        kind = key[0]
        pid = long(key[1:])
        if kind == "u":
            if pid == self.me:
                return {"_": "inputPeerSelf"}
            return {"_": "inputPeerUser", "user_id": pid,
                    "access_hash": self.peer(key).get("hash", 0)}
        if kind == "c":
            return {"_": "inputPeerChat", "chat_id": pid}
        return {"_": "inputPeerChannel", "channel_id": pid,
                "access_hash": self.peer(key).get("hash", 0)}

    def peer_name(self, key):
        if key is None:
            return "?"
        if key == "u%d" % (self.me or 0):
            return "Saved Messages"
        return self.peer(key)["name"]

    def short_name(self, key):
        if key == "u%d" % (self.me or 0):
            return "You"
        n = self.peer(key)["name"]
        if key[0] == "u":
            return n.split(" ")[0]
        return n

    def can_write(self, key):
        return self.peer(key).get("can_write", 1)

    def is_group(self, key):
        return self.peer(key)["kind"] in ("group", "supergroup")

    def status_text(self, key):
        """Header subtitle: online / last seen / members / bot."""
        p = self.peer(key)
        kind = p["kind"]
        if kind == "self":
            return "your cloud storage"
        if kind == "bot":
            return "bot"
        if kind in ("group", "supergroup"):
            if p.get("members"):
                return "%d members" % p["members"]
            return "group"
        if kind == "channel":
            if p.get("members"):
                return "%d subscribers" % p["members"]
            return "channel"
        s = p.get("status") or {}
        n = s.get("_", "")
        now = self.server_time()
        if n == "userStatusOnline" and s.get("expires", 0) > now:
            return "online"
        if n == "userStatusOnline" or n == "userStatusOffline":
            t = s.get("was_online") or s.get("expires") or 0
            ago = now - t
            if ago < 60:
                return "last seen just now"
            if ago < 3600:
                return "last seen %d min ago" % (ago / 60)
            if ago < 86400:
                return "last seen %d h ago" % (ago / 3600)
            return "last seen %d days ago" % (ago / 86400)
        if n == "userStatusRecently":
            return "last seen recently"
        if n == "userStatusLastWeek":
            return "last seen within a week"
        if n == "userStatusLastMonth":
            return "last seen within a month"
        return "last seen a long time ago"

    def is_online(self, key):
        s = self.peer(key).get("status") or {}
        return s.get("_") == "userStatusOnline" and s.get("expires", 0) > self.server_time()

    # ---------------------------------------------------------- messages

    def norm_message(self, m):
        """Telegram message -> {"id", "key", "out", "from", "from_key", "text",
        "date", "media", "reply_to", "edited", "fwd", "service"}."""
        n = m["_"]
        key = peer_key(m.get("peer_id"))
        d = {"id": m.get("id", 0), "key": key, "out": m.get("out", 0),
             "date": m.get("date", 0), "text": "", "media": "", "reply_to": 0,
             "edited": 0, "fwd": "", "service": 0, "from": "", "from_key": None,
             "photo": None, "sticker": None, "audio": None}
        if n == "messageEmpty":
            d["text"] = "Deleted message"
            d["service"] = 1
            return d
        sender = peer_key(m.get("from_id"))
        if sender is None:
            if d["out"]:
                sender = "u%d" % (self.me or 0)
            else:
                sender = key
        d["from_key"] = sender
        if d["out"]:
            d["from"] = "You"
        else:
            d["from"] = self.peer_name(sender)
        rt = m.get("reply_to")
        if type(rt) is type({}) and rt.get("reply_to_msg_id"):
            d["reply_to"] = rt["reply_to_msg_id"]
        if m.get("edit_date") and not m.get("edit_hide"):
            d["edited"] = 1
        if n == "messageService":
            d["service"] = 1
            d["text"] = self.action_text(m.get("action") or {}, d["from"])
            return d
        f = m.get("fwd_from")
        if type(f) is type({}):
            fk = peer_key(f.get("from_id"))
            if fk is not None:
                d["fwd"] = self.peer_name(fk)
            else:
                d["fwd"] = f.get("from_name") or "unknown"
        d["text"] = m.get("message") or ""
        media = m.get("media")
        if media is not None:
            mn = media["_"]
            label = MEDIA_LABELS.get(mn, mn[12:])
            if mn == "messageMediaDocument":
                doc = media.get("document")
                label = doc_label(doc)
                if label[:7] == "Sticker":
                    d["sticker"] = label[8:]
                else:
                    try:
                        d["photo"] = doc_preview(doc, label)
                        d["audio"] = audio_info(doc)
                    except:
                        pass     # unusual document: just show the label
            elif mn == "messageMediaPhoto":
                try:
                    d["photo"] = photo_preview(media.get("photo"))
                except:
                    pass
            elif mn == "messageMediaPoll":
                try:
                    label = "Poll: " + text_of(media["poll"]["question"])
                except:
                    pass
            elif mn == "messageMediaGeo" or mn == "messageMediaVenue":
                try:
                    g = media["geo"]
                    label = label + " %.5f, %.5f" % (g["lat"], g["long"])
                except:
                    pass
            elif mn == "messageMediaContact":
                label = "Contact: " + ((media.get("first_name") or "") + " " +
                                       (media.get("phone_number") or "")).strip()
            d["media"] = label
        return d

    def action_text(self, a, who):
        n = a.get("_", "")
        names = {"messageActionChatCreate": "created the group",
                 "messageActionChatEditTitle": "changed the group name",
                 "messageActionChatEditPhoto": "changed the group photo",
                 "messageActionChatDeletePhoto": "removed the group photo",
                 "messageActionChatAddUser": "added a member",
                 "messageActionChatDeleteUser": "left the group",
                 "messageActionChatJoinedByLink": "joined via invite link",
                 "messageActionChatJoinedByRequest": "joined the group",
                 "messageActionPinMessage": "pinned a message",
                 "messageActionPhoneCall": "called",
                 "messageActionChannelCreate": "created the channel",
                 "messageActionContactSignUp": "joined Telegram",
                 "messageActionHistoryClear": "cleared the history",
                 "messageActionScreenshotTaken": "took a screenshot",
                 "messageActionGroupCall": "started a video chat"}
        t = names.get(n)
        if t is None:
            t = n[13:]
        if n == "messageActionChatEditTitle":
            t = t + " to \"" + a.get("title", "") + "\""
        return who + " " + t

    def preview(self, m):
        """One-line preview of a normalized message for the chat list."""
        t = m["text"]
        if m["media"]:
            if t:
                t = m["media"] + ", " + t
            else:
                t = m["media"]
        return t

    def dialog_row(self, dg, top):
        key = peer_key(dg["peer"])
        preview = ""
        sender = ""
        date = 0
        out = 0
        if top is not None:
            nm = self.norm_message(top)
            preview = self.preview(nm)
            date = nm["date"]
            out = nm["out"]
            if nm["service"]:
                preview = nm["text"]
            elif out:
                sender = "You"
            elif self.is_group(key) and nm["from_key"]:
                sender = self.short_name(nm["from_key"])
        ns = dg.get("notify_settings") or {}
        muted = ns.get("mute_until", 0) > self.server_time()
        return {"key": key, "unread": dg.get("unread_count", 0),
                "mark": dg.get("unread_mark", 0), "preview": preview, "sender": sender,
                "date": date, "top": dg.get("top_message", 0), "out": out,
                "pinned": dg.get("pinned", 0), "muted": muted,
                "read_out": dg.get("read_outbox_max_id", 0),
                "read_in": dg.get("read_inbox_max_id", 0),
                "folder": dg.get("folder_id", 0)}

    def get_dialogs(self, on_ok, on_err, limit=50, after=None, folder=0):
        """One page of chats. after: the last row of the previous page."""
        def ok(res, self=self, on_ok=on_ok):
            msgs = {}
            for m in res.get("messages", []):
                msgs[(peer_key(m.get("peer_id")), m.get("id"))] = m
            rows = []
            for dg in res.get("dialogs", []):
                if dg["_"] != "dialog" or peer_key(dg["peer"]) is None:
                    continue
                rows.append(self.dialog_row(dg, msgs.get((peer_key(dg["peer"]),
                                                          dg.get("top_message")))))
            more = res["_"] == "messages.dialogsSlice" and len(rows) > 0
            on_ok(rows, more)
        f = {"_": "messages.getDialogs", "offset_date": 0, "offset_id": 0,
             "offset_peer": {"_": "inputPeerEmpty"}, "limit": limit, "hash": 0}
        if folder:
            f["folder_id"] = folder
        if after is not None:
            f["offset_date"] = after["date"]
            f["offset_id"] = after["top"]
            f["offset_peer"] = self.input_peer(after["key"])
        self.call(f, ok, on_err)

    def get_filters(self, on_ok, on_err):
        """Your chat folders as simple dicts."""
        def ok(res, self=self, on_ok=on_ok):
            out = []
            for f in res.get("filters", []):
                if f["_"] not in ("dialogFilter", "dialogFilterChatlist"):
                    continue
                d = {"id": f["id"], "title": text_of(f.get("title")),
                     "contacts": f.get("contacts", 0), "non_contacts": f.get("non_contacts", 0),
                     "groups": f.get("groups", 0), "broadcasts": f.get("broadcasts", 0),
                     "bots": f.get("bots", 0), "exclude_muted": f.get("exclude_muted", 0),
                     "exclude_read": f.get("exclude_read", 0)}
                for name in ("include_peers", "exclude_peers", "pinned_peers"):
                    keys = []
                    for p in f.get(name, []):
                        k = input_peer_key(p, self.me)
                        if k is not None:
                            keys.append(k)
                    d[name] = keys
                out.append(d)
            on_ok(out)
        self.call({"_": "messages.getDialogFilters"}, ok, on_err)

    def in_filter(self, f, row):
        key = row["key"]
        if key in f.get("pinned_peers", []) or key in f.get("include_peers", []):
            return 1
        if key in f.get("exclude_peers", []):
            return 0
        if f.get("exclude_muted") and row.get("muted"):
            return 0
        if f.get("exclude_read") and not row.get("unread") and not row.get("mark"):
            return 0
        kind = self.peer(key)["kind"]
        if kind == "bot":
            return f.get("bots", 0)
        if kind in ("user", "self"):
            if self.peer(key).get("contact") or kind == "self":
                return f.get("contacts", 0)
            return f.get("non_contacts", 0)
        if kind in ("group", "supergroup"):
            return f.get("groups", 0)
        if kind == "channel":
            return f.get("broadcasts", 0)
        return 0

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

    def send_text(self, key, text, on_ok, on_err, reply_to=0):
        if type(text) is type(u""):
            text = text.encode("utf-8")
        rid = tgcrypto.random_long()

        def ok(res, self=self, key=key, text=text, on_ok=on_ok, reply_to=reply_to):
            msg = None
            if res["_"] == "updateShortSentMessage":
                msg = {"id": res.get("id", 0), "key": key, "out": 1, "from": "You",
                       "from_key": "u%d" % (self.me or 0), "text": text, "media": "",
                       "date": res.get("date", self.server_time()), "reply_to": reply_to,
                       "edited": 0, "fwd": "", "service": 0}
            else:
                self.handle_updates(res)
            on_ok(msg)
        f = {"_": "messages.sendMessage", "peer": self.input_peer(key),
             "message": text, "random_id": rid}
        if reply_to:
            f["reply_to"] = {"_": "inputReplyToMessage", "reply_to_msg_id": reply_to}
        self.call(f, ok, on_err)

    def send_file(self, key, path, caption, reply_to, progress, on_ok, on_err):
        """Uploads the file at path and sends it to chat key. Returns an Upload
        (call cancel() to stop). progress(done_bytes, total_bytes) follows every
        acknowledged part, on_ok(None) when sent, on_err(RpcError) on failure."""
        u = Upload(self, key, path, caption, reply_to, progress, on_ok, on_err)
        u.start()
        return u

    def edit_text(self, key, mid, text, on_ok, on_err):
        if type(text) is type(u""):
            text = text.encode("utf-8")

        def ok(res, self=self, on_ok=on_ok):
            self.handle_updates(res)
            on_ok(res)
        self.call({"_": "messages.editMessage", "peer": self.input_peer(key), "id": mid,
                   "message": text}, ok, on_err)

    def delete_messages(self, key, ids, revoke, on_ok, on_err):
        """revoke: also delete for the other person / everyone."""
        if key[0] == "h":
            f = {"_": "channels.deleteMessages", "id": ids,
                 "channel": {"_": "inputChannel", "channel_id": long(key[1:]),
                             "access_hash": self.peer(key).get("hash", 0)}}
        else:
            f = {"_": "messages.deleteMessages", "id": ids}
            if revoke:
                f["revoke"] = 1
        self.call(f, on_ok, on_err)

    def profile_photo(self, key):
        """Download info for the chat's 160 px profile picture, or None."""
        p = self.peer(key)
        if not p.get("photo_id"):
            return None
        return {"id": "a%d" % p["photo_id"], "dc": p.get("photo_dc", 0), "w": 160, "h": 160,
                "stripped": p.get("photo"), "badge": "",
                "loc": {"_": "inputPeerPhotoFileLocation", "peer": self.input_peer(key),
                        "photo_id": p["photo_id"]}}

    def get_profile(self, key, on_ok, on_err):
        """Bio / description and member count: {"about", "members", "calls"}."""
        def ok(res, self=self, key=key, on_ok=on_ok):
            full = res.get("full_user") or res.get("full_chat") or {}
            d = {"about": full.get("about") or "", "members": 0,
                 "calls": full.get("phone_calls_available", 0)}
            if full.get("participants_count"):
                d["members"] = full["participants_count"]
            parts = full.get("participants")
            if type(parts) is type({}) and parts.get("participants"):
                d["members"] = len(parts["participants"])
            if d["members"] and self.peers.has_key(key):
                self.peers[key]["members"] = d["members"]
            on_ok(d)
        kind = key[0]
        if kind == "u":
            ip = self.input_peer(key)
            if ip["_"] == "inputPeerSelf":
                iu = {"_": "inputUserSelf"}
            else:
                iu = {"_": "inputUser", "user_id": ip["user_id"],
                      "access_hash": ip["access_hash"]}
            f = {"_": "users.getFullUser", "id": iu}
        elif kind == "c":
            f = {"_": "messages.getFullChat", "chat_id": long(key[1:])}
        else:
            f = {"_": "channels.getFullChannel",
                 "channel": {"_": "inputChannel", "channel_id": long(key[1:]),
                             "access_hash": self.peer(key).get("hash", 0)}}
        self.call(f, ok, on_err)

    def set_mute(self, key, mute, on_ok, on_err):
        until = 0
        if mute:
            until = 2147483647
        self.call({"_": "account.updateNotifySettings",
                   "peer": {"_": "inputNotifyPeer", "peer": self.input_peer(key)},
                   "settings": {"_": "inputPeerNotifySettings", "mute_until": until}},
                  on_ok, on_err)

    def forward(self, from_key, ids, to_key, on_ok, on_err):
        rids = []
        for i in ids:
            rids.append(tgcrypto.random_long())

        def ok(res, self=self, on_ok=on_ok):
            self.handle_updates(res)
            on_ok(res)
        self.call({"_": "messages.forwardMessages", "from_peer": self.input_peer(from_key),
                   "id": ids, "random_id": rids, "to_peer": self.input_peer(to_key)},
                  ok, on_err)

    # ---------------------------------------------------------- Telegram calls
    # Signalling only (DH key exchange); the call state lives in self.cs:
    # {"key", "id", "hash", "out", "state", "text", "a", "g_a", "g_a_hash",
    #  "start", "conns", "fp", "kb", "emoji"}; "kb" (256-byte key) and "conns"
    # (phoneConnection dicts) are what the media layer needs once connected.
    # states: calling ringing incoming keys connected ended

    CALL_PROTOCOL = {"_": "phoneCallProtocol", "udp_p2p": 1, "udp_reflector": 1,
                     "min_layer": 65, "max_layer": 92, "library_versions": ["2.4.4"]}
    CALL_PROTOCOL_277 = {"_": "phoneCallProtocol", "udp_p2p": 1, "udp_reflector": 1,
                         "min_layer": 65, "max_layer": 92, "library_versions": ["2.7.7"]}

    def protocol_for(self, cs):
        """The phoneCallProtocol we announce for this call. In 'mimic' mode
        (experiment) we repeat what the peer announced, or the official apps'
        list when we are the caller."""
        if self.call_version == "mimic":
            pr = cs.get("peer_protocol")
            if pr:
                p = {"_": "phoneCallProtocol", "udp_p2p": pr.get("udp_p2p", 1),
                     "udp_reflector": pr.get("udp_reflector", 1),
                     "min_layer": pr.get("min_layer", 65), "max_layer": pr.get("max_layer", 92),
                     "library_versions": list(pr.get("library_versions") or [])}
            else:
                p = {"_": "phoneCallProtocol", "udp_p2p": 1, "udp_reflector": 1,
                     "min_layer": 65, "max_layer": 92,
                     "library_versions": ["2.7.7", "5.0.0", "7.0.0", "8.0.0", "9.0.0",
                                          "10.0.0", "11.0.0", "12.0.0", "13.0.0"]}
        else:
            p = self.call_protocol
        self.log("call announces protocol: udp_p2p=%s udp_reflector=%s layers %s-%s versions=%s" % (
            p.get("udp_p2p"), p.get("udp_reflector"), p.get("min_layer"), p.get("max_layer"),
            str(p.get("library_versions"))))
        return p

    def set_call_version(self, version):
        """'2.4.4' (legacy, works with modded/old clients) or '2.7.7' (what
        official apps accept; probe only: signalling, no audio yet)."""
        if version == "mimic":
            self.call_protocol = self.CALL_PROTOCOL_277
        elif version == "2.7.7":
            self.call_protocol = self.CALL_PROTOCOL_277
        else:
            self.call_protocol = self.CALL_PROTOCOL
        self.call_version = version

    def call_busy(self):
        return self.cs is not None and self.cs["state"] != "ended"

    VCAP_FLAG = "E:\\retrotele_videocap.flag"
    VCAP_LOG = "E:\\retrotele_callvideo.txt"

    def vcap_on(self):
        """Stage 0 video capture: only when E:\\retrotele_videocap.flag exists."""
        try:
            return os.path.exists(self.VCAP_FLAG)
        except:
            return 0

    def vcap_log(self, msg):
        if not self.vcap_on():
            return
        try:
            f = open(self.VCAP_LOG, "a")
            try:
                f.write(msg + "\n")
            finally:
                f.close()
        except:
            pass

    def call_log(self, cs, msg):
        self.log("call %s: %s" % (cs["state"], msg))

    def call_state(self, cs, state, text):
        cs["state"] = state
        cs["text"] = text
        self.call_log(cs, text)
        self.ui.call_changed()

    def call_input(self, cs):
        return {"_": "inputPhoneCall", "id": cs["id"], "access_hash": cs["hash"]}

    def call_fail(self, cs, e):
        if cs["state"] != "ended":
            self.call_state(cs, "ended", "Call failed: " + e.message)
            self.ui.call_changed()

    def get_dh_config(self, on_ok, on_err):
        if self.dh is not None:
            on_ok(self.dh)
            return

        def ok(res, self=self, on_ok=on_ok, on_err=on_err):
            g = res.get("g", 0)
            p = res.get("p", "")
            if res.get("_") != "messages.dhConfig" or len(p) != 256 or ord(p[0]) < 128 \
                    or g < 2 or g > 7:
                on_err(RpcError(0, "BAD_DH_CONFIG"))
                return
            self.dh = (g, tgcrypto.bytes_to_long(p))
            on_ok(self.dh)
        self.call({"_": "messages.getDhConfig", "version": 0, "random_length": 256},
                  ok, on_err)

    def dh_ok(self, x, p):
        """Range check from the docs: 2^1984 < x < p - 2^1984."""
        lim = long(2) ** 1984
        return x > lim and x < p - lim

    def fingerprint(self, kb):
        s = tgcrypto.sha1(kb)[-8:]
        l = list(s)
        l.reverse()
        v = tgcrypto.bytes_to_long("".join(l))
        if v >= long(2) ** 63:
            v = v - long(2) ** 64
        return v

    def new_call(self, key, out):
        self.cs = {"key": key, "id": None, "hash": 0, "out": out, "state": "calling",
                   "text": "", "a": None, "g_a": "", "g_a_hash": "", "start": 0,
                   "conns": [], "fp": 0, "kb": "", "emoji": ""}
        return self.cs

    def start_call(self, key):
        """Outgoing Telegram call to user key 'u<id>'. False if busy."""
        if self.call_busy():
            return 0
        cs = self.new_call(key, 1)
        self.call_state(cs, "calling", "Calling...")

        def fail(e, self=self, cs=cs):
            self.call_fail(cs, e)

        def have(dh, self=self, cs=cs, key=key, fail=fail):
            if cs["state"] == "ended":
                return
            g, p = dh
            self.call_state(cs, "calling", "Creating key...")
            self.ui.call_yield()
            a = tgcrypto.bytes_to_long(tgcrypto.random_bytes(256))
            ga = tgcrypto.powmod(g, a, p)
            if not self.dh_ok(ga, p):
                fail(RpcError(0, "BAD_G_A"))
                return
            gab = tgcrypto.long_to_bytes(ga, 256)
            cs["a"] = a
            cs["g_a"] = gab
            self.call_state(cs, "calling", "Calling...")
            pk = self.input_peer(key)

            def sent(res, self=self, cs=cs):
                c = res.get("phone_call") or {}
                cs["id"] = c.get("id")
                cs["hash"] = c.get("access_hash", 0)
                if cs["state"] == "ended":
                    # hung up before the server answered
                    self.send_discard(cs, "phoneCallDiscardReasonHangup", 0)
                    return
                self.call_log(cs, "requested, id %s" % str(cs["id"]))
                if c.get("receive_date"):
                    self.call_state(cs, "ringing", "Ringing...")
            req = {"_": "phone.requestCall",
                   "user_id": {"_": "inputUser", "user_id": pk["user_id"],
                               "access_hash": pk["access_hash"]},
                   "random_id": int(tgcrypto.bytes_to_long(tgcrypto.random_bytes(4))
                                    % 2147483647),
                   "g_a_hash": tgcrypto.sha256(gab),
                   "protocol": self.protocol_for(cs)}
            if self.vcap_on():
                req["video"] = 1
                self.vcap_log("requestCall with video flag set")
            self.call(req, sent, fail)
        self.get_dh_config(have, fail)
        return 1

    def accept_call(self):
        cs = self.cs
        if cs is None or cs["state"] != "incoming":
            return

        def fail(e, self=self, cs=cs):
            self.call_fail(cs, e)

        def have(dh, self=self, cs=cs, fail=fail):
            if cs["state"] == "ended":
                return
            g, p = dh
            self.call_state(cs, "keys", "Exchanging keys...")
            self.ui.call_yield()
            b = tgcrypto.bytes_to_long(tgcrypto.random_bytes(256))
            gb = tgcrypto.powmod(g, b, p)
            if not self.dh_ok(gb, p):
                fail(RpcError(0, "BAD_G_B"))
                return
            cs["a"] = b
            cs["p"] = p

            def sent(res, self=self, cs=cs):
                self.call_log(cs, "accepted, waiting for the caller's key")
            self.call({"_": "phone.acceptCall", "peer": self.call_input(cs),
                       "g_b": tgcrypto.long_to_bytes(gb, 256),
                       "protocol": self.protocol_for(cs)}, sent, fail)
        self.get_dh_config(have, fail)

    def send_discard(self, cs, reason, duration):
        self.call({"_": "phone.discardCall", "duration": duration, "connection_id": 0,
                   "peer": self.call_input(cs), "reason": {"_": reason}},
                  lambda r: None, lambda e: None)

    def send_signaling(self, cs, data):
        """phone.sendSignalingData: an opaque blob for the peer's call library."""
        if cs is None or cs["id"] is None or cs["state"] == "ended":
            return
        def bad(e, self=self):
            self.log("call sendSignalingData failed: %s" % str(e))
        self.call({"_": "phone.sendSignalingData", "peer": self.call_input(cs), "data": data},
                  lambda r: None, bad)

    def hang_up(self):
        """Decline (incoming, ringing), cancel or hang up."""
        cs = self.cs
        if cs is None or cs["state"] == "ended":
            return
        dur = 0
        reason = "phoneCallDiscardReasonHangup"
        if cs["state"] == "incoming":
            reason = "phoneCallDiscardReasonBusy"
        if cs["start"]:
            dur = int(time.time() - cs["start"])
        if cs["id"] is not None:
            self.send_discard(cs, reason, dur)
        self.call_state(cs, "ended", "Call ended")

    def decline_busy(self, c):
        self.call({"_": "phone.discardCall", "duration": 0, "connection_id": 0,
                   "peer": {"_": "inputPhoneCall", "id": c["id"],
                            "access_hash": c["access_hash"]},
                   "reason": {"_": "phoneCallDiscardReasonBusy"}},
                  lambda r: None, lambda e: None)

    def call_connected(self, cs, c):
        cs["conns"] = c.get("connections", [])
        cs["start"] = time.time()
        for x in cs["conns"]:
            self.log("call connection: %s ip=%s port=%s tag=%s id=%s" % (
                x.get("_"), x.get("ip", ""), x.get("port", ""),
                binascii.hexlify(x.get("peer_tag", "")), x.get("id", "")))
        self.log("call server protocol: %s" % str(c.get("protocol")))
        if self.call_version == "mimic":
            # experiment calls only: the key lets the PC decode the peer's setup messages
            self.log("PROBE call key %s" % binascii.hexlify(cs["kb"]))
            self.log("PROBE call is_outgoing %d" % cs["out"])
        self.log("call key fingerprint %s, key sha1 %s" % (
            str(cs["fp"]), binascii.hexlify(tgcrypto.sha1(cs["kb"]))))
        h = binascii.hexlify(tgcrypto.sha256(cs["kb"] + cs["g_a"]))
        cs["emoji"] = "%s %s %s %s" % (h[0:4], h[4:8], h[8:12], h[12:16])
        self.call_state(cs, "connected", "Connected")
        self.ui.call_ready(cs)

    def call_update(self, c):
        n = c.get("_")
        cs = self.cs
        if n in ("phoneCallRequested", "phoneCall", "phoneCallAccepted", "phoneCallWaiting"):
            self.vcap_log("%s flags=%s (0x%x)" % (n, str(c.get("flags")), c.get("flags") or 0))
        if n == "phoneCallRequested" and c.get("participant_id") == self.me:
            if self.call_busy():
                self.log("call: busy, declining %s" % str(c["id"]))
                self.decline_busy(c)
                return
            cs = self.new_call("u%d" % c["admin_id"], 0)
            cs["id"] = c["id"]
            cs["hash"] = c["access_hash"]
            cs["g_a_hash"] = c.get("g_a_hash", "")
            pr = c.get("protocol") or {}
            cs["peer_protocol"] = pr
            self.log("call incoming protocol: udp_p2p=%s udp_reflector=%s min_layer=%s "
                     "max_layer=%s versions=%s" % (pr.get("udp_p2p"), pr.get("udp_reflector"),
                     pr.get("min_layer"), pr.get("max_layer"), str(pr.get("library_versions"))))
            self.call({"_": "phone.receivedCall", "peer": self.call_input(cs)},
                      lambda r: None, lambda e: None)
            self.call_state(cs, "incoming", "Incoming Telegram call")
            return
        if cs is None or cs["state"] == "ended":
            return
        if cs["id"] is None or c.get("id") != cs["id"]:
            return
        if n == "phoneCallDiscarded":
            self.log("call discarded: %s" % str(c))
            r = (c.get("reason") or {}).get("_", "")
            text = "Call ended"
            if r == "phoneCallDiscardReasonBusy":
                text = "Call ended (busy)"
            elif r == "phoneCallDiscardReasonMissed":
                text = "Call ended (missed)"
            elif r == "phoneCallDiscardReasonDisconnect":
                text = "Call ended (disconnected)"
            self.call_state(cs, "ended", text)
        elif n == "phoneCallWaiting":
            if cs["out"] and cs["state"] == "calling" and c.get("receive_date"):
                self.call_state(cs, "ringing", "Ringing...")
        elif n == "phoneCallAccepted" and cs["out"] and cs["state"] != "keys":
            self.call_state(cs, "keys", "Exchanging keys...")
            self.ui.call_yield()
            g, p = self.dh
            gb = tgcrypto.bytes_to_long(c.get("g_b", ""))
            if not self.dh_ok(gb, p):
                self.fail_call_now(cs, "BAD_G_B")
                return
            kb = tgcrypto.long_to_bytes(tgcrypto.powmod(gb, cs["a"], p), 256)
            cs["kb"] = kb
            cs["fp"] = self.fingerprint(kb)

            def done(res, self=self, cs=cs):
                if cs["state"] == "ended":
                    return
                self.call_connected(cs, res.get("phone_call") or {})

            def fail(e, self=self, cs=cs):
                self.call_fail(cs, e)
            self.call({"_": "phone.confirmCall", "peer": self.call_input(cs),
                       "g_a": cs["g_a"], "key_fingerprint": cs["fp"],
                       "protocol": self.protocol_for(cs)}, done, fail)
        elif n == "phoneCall" and not cs["out"] and cs["state"] == "keys":
            ga = c.get("g_a_or_b", "")
            if tgcrypto.sha256(ga) != cs["g_a_hash"]:
                self.fail_call_now(cs, "G_A_HASH_MISMATCH")
                return
            p = cs["p"]
            gan = tgcrypto.bytes_to_long(ga)
            if not self.dh_ok(gan, p):
                self.fail_call_now(cs, "BAD_G_A")
                return
            self.ui.call_yield()
            kb = tgcrypto.long_to_bytes(tgcrypto.powmod(gan, cs["a"], p), 256)
            fp = self.fingerprint(kb)
            if fp != c.get("key_fingerprint"):
                self.fail_call_now(cs, "KEY_FINGERPRINT_MISMATCH")
                return
            cs["g_a"] = ga
            cs["kb"] = kb
            cs["fp"] = fp
            self.call_connected(cs, c)

    def fail_call_now(self, cs, why):
        self.send_discard(cs, "phoneCallDiscardReasonDisconnect", 0)
        self.call_state(cs, "ended", "Call failed: " + why)

    def mark_read(self, key, max_id):
        if key[0] == "h":
            f = {"_": "channels.readHistory", "max_id": max_id,
                 "channel": {"_": "inputChannel", "channel_id": long(key[1:]),
                             "access_hash": self.peer(key).get("hash", 0)}}
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
            keys = []
            for c in res.get("contacts", []):
                keys.append("u%d" % c["user_id"])
            on_ok(keys)
        self.call({"_": "contacts.getContacts", "hash": 0}, ok, on_err)

    # ---------------------------------------------------------- updates

    def short_msg(self, u, key, from_key):
        return {"id": u["id"], "key": key, "out": u.get("out", 0),
                "from": self.peer_name(from_key), "from_key": from_key,
                "text": u.get("message", ""), "media": "", "date": u.get("date", 0),
                "reply_to": 0, "edited": 0, "fwd": "", "service": 0}

    def handle_updates(self, u):
        n = u["_"]
        if n == "newSession" or n == "updatesTooLong":
            self.ui.refresh_needed()
            return
        if n == "updateShortMessage":
            key = "u%d" % u["user_id"]
            frm = key
            if u.get("out"):
                frm = "u%d" % (self.me or 0)
            m = self.short_msg(u, key, frm)
            if u.get("out"):
                m["from"] = "You"
            self.ui.new_message(key, m)
            if not self.peers.has_key(key):
                self.ui.refresh_needed()
            return
        if n == "updateShortChatMessage":
            key = "c%d" % u["chat_id"]
            m = self.short_msg(u, key, "u%d" % u["from_id"])
            if u.get("out"):
                m["from"] = "You"
            self.ui.new_message(key, m)
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
        elif n == "updateEditMessage" or n == "updateEditChannelMessage":
            m = self.norm_message(x["message"])
            if m["key"] is not None:
                self.ui.message_edited(m["key"], m)
        elif n == "updateReadHistoryOutbox":
            self.ui.read_changed(peer_key(x["peer"]), "out", x["max_id"], -1)
        elif n == "updateReadHistoryInbox":
            self.ui.read_changed(peer_key(x["peer"]), "in", x["max_id"],
                                 x.get("still_unread_count", 0))
        elif n == "updateReadChannelInbox":
            self.ui.read_changed("h%d" % x["channel_id"], "in", x["max_id"],
                                 x.get("still_unread_count", 0))
        elif n == "updateReadChannelOutbox":
            self.ui.read_changed("h%d" % x["channel_id"], "out", x["max_id"], -1)
        elif n == "updateUserStatus":
            key = "u%d" % x["user_id"]
            p = self.peers.get(key)
            if p is not None:
                p["status"] = x["status"]
                self.ui.peer_changed(key)
        elif n == "updateDeleteMessages":
            self.ui.messages_deleted(None, x.get("messages", []))
        elif n == "updateDeleteChannelMessages":
            self.ui.messages_deleted("h%d" % x["channel_id"], x.get("messages", []))
        elif n == "updatePhoneCallSignalingData":
            data = x.get("data", "")
            self.log("call signaling data: %d bytes" % len(data))
            if self.call_version == "mimic":
                self.log("PROBE signaling %s" % binascii.hexlify(data))
            cs = self.cs
            if (cs is not None and cs["id"] is not None and cs["id"] == x.get("phone_call_id")
                    and cs["state"] != "ended"):
                self.ui.call_signaling(data)
        elif n == "updatePhoneCall":
            self.call_update(x.get("phone_call") or {})
        elif n == "updateUserTyping" or n == "updateChatUserTyping":
            pass
        elif n == "updateChannelTooLong":
            self.ui.refresh_needed()


# ---------------------------------------------------------------- avatars

STRIPPED_HEADER = (
    "ffd8ffe000104a46494600010100000100010000ffdb004300281c1e231e19282321232d2b28303c"
    "64413c37373c7b585d4964918099968f808c8aa0b4e6c3a0aadaad8a8cc8ffcbdaeef5ffffff9bc1"
    "fffffffaffe6fdfff8ffdb0043012b2d2d3c353c76414176f8a58ca5f8f8f8f8f8f8f8f8f8f8f8f8"
    "f8f8f8f8f8f8f8f8f8f8f8f8f8f8f8f8f8f8f8f8f8f8f8f8f8f8f8f8f8f8f8f8f8f8f8f8f8f8ffc0"
    "0011080000000003012200021101031101ffc4001f00000105010101010101000000000000000001"
    "02030405060708090a0bffc400b5100002010303020403050504040000017d010203000411051221"
    "31410613516107227114328191a1082342b1c11552d1f02433627282090a161718191a2526272829"
    "2a3435363738393a434445464748494a535455565758595a636465666768696a737475767778797a"
    "838485868788898a92939495969798999aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7b8b9bac2c3c4c5c6"
    "c7c8c9cad2d3d4d5d6d7d8d9dae1e2e3e4e5e6e7e8e9eaf1f2f3f4f5f6f7f8f9faffc4001f010003"
    "0101010101010101010000000000000102030405060708090a0bffc400b511000201020404030407"
    "05040400010277000102031104052131061241510761711322328108144291a1b1c109233352f015"
    "6272d10a162434e125f11718191a262728292a35363738393a434445464748494a53545556575859"
    "5a636465666768696a737475767778797a82838485868788898a92939495969798999aa2a3a4a5a6"
    "a7a8a9aab2b3b4b5b6b7b8b9bac2c3c4c5c6c7c8c9cad2d3d4d5d6d7d8d9dae2e3e4e5e6e7e8e9ea"
    "f2f3f4f5f6f7f8f9faffda000c03010002110311003f00")


PART_SIZE = 65536          # multiple of 1024, divides 512 KB
SMALL_LIMIT = 10 * 1024 * 1024
PHOTO_LIMIT = 10 * 1024 * 1024
MAX_FILE = 2000 * 1024 * 1024
MAX_PARTS = 4000
PHOTO_FALLBACK = ("PHOTO_INVALID_DIMENSIONS", "PHOTO_SAVE_FILE_INVALID",
                  "IMAGE_PROCESS_FAILED", "PHOTO_EXT_INVALID", "MEDIA_INVALID")


class Upload:
    """One file upload: parts go one at a time (each acknowledged before the
    next is read, so only one part is ever in memory), then messages.sendMedia."""

    def __init__(self, client, key, path, caption, reply_to, progress, on_ok, on_err):
        self.c = client
        self.key = key
        self.path = path
        self.caption = caption or ""
        if type(self.caption) is type(u""):
            self.caption = self.caption.encode("utf-8")
        self.reply_to = reply_to
        self.progress = progress
        self.on_ok = on_ok
        self.on_err = on_err
        self.cancelled = 0
        self.finished = 0
        self.f = None
        self.md5 = None
        self.index = 0
        self.done = 0
        self.total = 0
        self.fid = 0
        self.tries = 0
        self.data = None
        self.name = fileinfo.base_name(path)
        if type(self.name) is type(u""):
            self.name = self.name.encode("utf-8")

    def cancel(self):
        self.cancelled = 1
        self.finish_file()

    def finish_file(self):
        self.data = None
        if self.f is not None:
            try:
                self.f.close()
            except:
                pass
            self.f = None

    def fail(self, e):
        self.finish_file()
        if self.cancelled or self.finished:
            return
        self.finished = 1
        self.on_err(e)

    def start(self):
        import os
        try:
            self.total = int(os.path.getsize(self.path))
            self.f = open(self.path, "rb")
        except:
            self.fail(RpcError(-4, "cannot read file"))
            return
        if self.total <= 0:
            self.fail(RpcError(-4, "FILE_EMPTY"))
            return
        if self.total > MAX_FILE:
            self.fail(RpcError(-4, "FILE_TOO_BIG"))
            return
        self.part_size = PART_SIZE
        while (self.total + self.part_size - 1) / self.part_size > MAX_PARTS:
            self.part_size = self.part_size * 2
        self.parts = int((self.total + self.part_size - 1) / self.part_size)
        self.big = self.total > SMALL_LIMIT
        if not self.big:
            import md5
            self.md5 = md5.new()
        self.fid = tgcrypto.random_long()
        self.next_part()

    def next_part(self):
        if self.cancelled:
            return
        try:
            self.data = self.f.read(self.part_size)
        except:
            self.fail(RpcError(-4, "cannot read file"))
            return
        if not self.data:
            self.fail(RpcError(-4, "FILE_PARTS_INVALID"))
            return
        if self.md5 is not None:
            self.md5.update(self.data)
        self.tries = 0
        self.send_part()

    def send_part(self):
        if self.big:
            func = {"_": "upload.saveBigFilePart", "file_id": self.fid,
                    "file_part": self.index, "file_total_parts": self.parts,
                    "bytes": self.data}
        else:
            func = {"_": "upload.saveFilePart", "file_id": self.fid,
                    "file_part": self.index, "bytes": self.data}
        self.c.call(func, self.part_ok, self.part_err)

    def part_ok(self, res):
        if self.cancelled:
            return
        self.done = self.done + len(self.data)
        self.data = None
        self.index = self.index + 1
        if self.progress is not None:
            try:
                self.progress(self.done, self.total)
            except:
                pass
        if self.index < self.parts:
            self.next_part()
            return
        self.finish_file()
        self.send_media(0)

    def part_err(self, e):
        if self.cancelled:
            return
        if self.tries < 3 and e.code not in (401, 403):
            self.tries = self.tries + 1
            self.c.log("upload part %d failed (%s), retry %d" % (self.index, e.message, self.tries))
            self.c.net.later(0.5, self.retry)
            return
        self.fail(e)

    def retry(self):
        if not self.cancelled:
            self.send_part()

    def input_file(self):
        if self.big:
            return {"_": "inputFileBig", "id": self.fid, "parts": self.parts,
                    "name": self.name}
        return {"_": "inputFile", "id": self.fid, "parts": self.parts,
                "name": self.name, "md5_checksum": self.md5.hexdigest()}

    def media(self, as_document):
        f = self.input_file()
        if not as_document and fileinfo.is_image(self.name) and self.total <= PHOTO_LIMIT:
            return {"_": "inputMediaUploadedPhoto", "file": f}
        attrs = []
        m = {"_": "inputMediaUploadedDocument", "file": f,
             "mime_type": fileinfo.mime_for(self.name)}
        if fileinfo.is_image(self.name):
            m["force_file"] = 1
        elif fileinfo.is_audio(self.name) or fileinfo.is_video(self.name):
            info = fileinfo.media_info(self.name, self.path)
            if fileinfo.is_audio(self.name):
                a = {"_": "documentAttributeAudio", "duration": info["duration"]}
                if info["title"]:
                    a["title"] = info["title"].encode("utf-8")
                if info["performer"]:
                    a["performer"] = info["performer"].encode("utf-8")
                attrs.append(a)
            elif info["duration"] and info["w"] and info["h"]:
                attrs.append({"_": "documentAttributeVideo",
                              "duration": float(info["duration"]),
                              "w": info["w"], "h": info["h"]})
        attrs.append({"_": "documentAttributeFilename", "file_name": self.name})
        m["attributes"] = attrs
        return m

    def send_media(self, as_document):
        f = {"_": "messages.sendMedia", "peer": self.c.input_peer(self.key),
             "media": self.media(as_document), "message": self.caption,
             "random_id": tgcrypto.random_long()}
        if self.reply_to:
            f["reply_to"] = {"_": "inputReplyToMessage", "reply_to_msg_id": self.reply_to}
        self.c.call(f, self.sent_ok, lambda e, self=self, d=as_document: self.sent_err(e, d))

    def sent_ok(self, res):
        if self.cancelled or self.finished:
            return
        self.finished = 1
        try:
            self.c.handle_updates(res)
        except:
            self.c.log("update error: " + err_text())
        self.on_ok(None)

    def sent_err(self, e, as_document):
        if self.cancelled:
            return
        if not as_document and e.message in PHOTO_FALLBACK and \
                fileinfo.is_image(self.name):
            self.send_media(1)       # not a usable photo: send it as a file
            return
        self.fail(e)


def stripped_to_jpeg(s):
    """Telegram's stripped photo thumbnail (a tiny JPEG without its standard
    header) -> a complete JPEG file."""
    if not s or len(s) < 3 or s[0] != "\x01":
        return None
    h = unhex(STRIPPED_HEADER)
    h = h[:164] + s[1] + h[165] + s[2] + h[167:]
    return h + s[3:] + "\xff\xd9"


# ---------------------------------------------------------------- 2FA (SRP)

def srp_answer(pw, x_hash):
    """Builds inputCheckPasswordSRP from account.password and the slow
    password hash x (tgsrp.PasswordHash or tools/tg2fa.py)."""
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
        ga = tgcrypto.powmod(g, a, p)
        if ga > 0 and ga < p:
            break
    g_a = pad(ga)
    u = tgcrypto.bytes_to_long(sha256(g_a + pad(gb)))
    gx = tgcrypto.powmod(g, x, p)
    kgx = (k * gx) % p
    t = (gb - kgx) % p
    sa = tgcrypto.powmod(t, a + u * x, p)
    k_a = sha256(pad(sa))
    hp = sha256(p_bytes)
    hg = sha256(pad(g))
    m1 = sha256(tgcrypto.xor_bytes(hp, hg) + sha256(algo["salt1"]) + sha256(algo["salt2"]) +
                g_a + pad(gb) + k_a)
    return {"_": "inputCheckPasswordSRP", "srp_id": pw["srp_id"], "A": g_a, "M1": m1}
