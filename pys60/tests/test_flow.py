# Drives the RetroTele UI (fake appuifw) against a fake Telegram session:
# login with code + two-step password (SRP checked like the server does),
# chat list, open chat, send, live update. Python 2.7.
import sys, os, hashlib
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "fake_s60"))
sys.path.insert(0, os.path.join(HERE, ".."))
import tempfile, shutil
TMP = tempfile.mkdtemp()
os.chdir(TMP)
shutil.copy(os.path.join(HERE, "..", "schema.txt"), TMP)

import appuifw
notes = []
answers = []
popups = []
appuifw.note = lambda text, kind="info": notes.append(text)
qlog = []
def query(label, kind, initial=None):
    qlog.append(label)
    assert answers, "unexpected query: %r" % label
    a = answers.pop(0)
    print "  query %r -> %r" % (label, a)
    return a
appuifw.query = query
def popup_menu(items, title=None):
    if popups:
        return popups.pop(0)
    return 0       # "Send" (no caption)
appuifw.popup_menu = popup_menu

class Listbox:
    def __init__(self, rows, cb):
        self.rows = rows; self.cb = cb; self.cur = 0
    def set_list(self, rows, cur=0):
        self.rows = rows; self.cur = cur
    def current(self):
        return self.cur
appuifw.Listbox = Listbox
class Text:
    def __init__(self): self.t = u""
    def set(self, t): self.t = t
    def get(self): return self.t
appuifw.Text = Text
class Canvas:
    def __init__(self, redraw_callback=None, event_callback=None):
        self.size = (240, 292); self.keys = {}
    def bind(self, code, cb): self.keys[code] = cb
    def blit(self, img, **k): pass
appuifw.Canvas = Canvas
appuifw.selection_list = lambda items, search_field=0: 0
import graphics

import retrotele, tgclient, tgsrp, tgcrypto, mtproto
from mtproto import RpcError

class FakeNet:
    def __init__(self): self.q = []; self.delayed = []
    def later(self, sec, f):
        if sec >= 1:
            self.delayed.append(f)   # timers (player ticks, toasts) don't run here
        else:
            self.q.append(f)
    def run(self):
        n = 0
        while self.q:
            f = self.q.pop(0); f(); n += 1
            assert n < 10000
    def cancel_all(self): self.q = []

# --- server side SRP
P = int(mtproto.DH_PRIME, 16); G = 3
SALT1 = "s1" * 20; SALT2 = "s2" * 8; PASSWORD = "secret"
def sh(d, s): return hashlib.sha256(s + d + s).digest()
def x_for(pw):
    return sh(hashlib.pbkdf2_hmac("sha512", sh(sh(pw, SALT1), SALT2), SALT1, 50), SALT2)
def i2b(n): return tgcrypto.long_to_bytes(n, 256)
def b2i(s): return tgcrypto.bytes_to_long(s)
X = b2i(x_for(PASSWORD)); V = pow(G, X, P)
K = b2i(hashlib.sha256(i2b(P) + i2b(G)).digest())
B_SECRET = 123456789123456789
GB = (K * V + pow(G, B_SECRET, P)) % P
def server_check(ans):
    A = b2i(ans["A"])
    u = b2i(hashlib.sha256(i2b(A) + i2b(GB)).digest())
    S = pow(A * pow(V, u, P), B_SECRET, P)
    ka = hashlib.sha256(i2b(S)).digest()
    hp = hashlib.sha256(i2b(P)).digest(); hg = hashlib.sha256(i2b(G)).digest()
    m1 = hashlib.sha256(tgcrypto.xor_bytes(hp, hg) + hashlib.sha256(SALT1).digest() +
                        hashlib.sha256(SALT2).digest() + i2b(A) + i2b(GB) + ka).digest()
    return m1 == ans["M1"]

USER = {"_": "user", "id": 42, "access_hash": 999, "first_name": "Alice", "last_name": "B",
        "contact": 1, "phone": "15550001111",
        "status": {"_": "userStatusOnline", "expires": 4000000000}}
CYAN = {"_": "user", "id": 43, "access_hash": 5, "first_name": "Cyan"}
GROUP = {"_": "chat", "id": 900, "title": "Book club", "participants_count": 5,
         "date": 0, "version": 1, "photo": {"_": "chatPhotoEmpty"}}
ME = {"_": "user", "id": 7, "self": 1, "first_name": "Me"}
calls = []
class FakeSession:
    def __init__(self, net, schema, events, dc_id, *a):
        self.net = net; self.events = events; self.dc_id = dc_id
        self.time_offset = 0; self.state = "ready"; self.gen = 0; self.auth_key = "k" * 256
        self.salt = "s" * 8
    def start(self):
        self.net.later(0, lambda: self.events.connected(self))
    def close(self): pass
    def invoke(self, f, ok, err):
        calls.append(f["_"])
        res = handle(f)
        if isinstance(res, RpcError):
            self.net.later(0, lambda: err(res))
        else:
            self.net.later(0, lambda: ok(res))
state = {"signed": 0}
up = {"parts": [], "md5": None, "bytes": 0, "fail": {}, "hook": None,
      "media": [], "media_err": []}
def handle(f):
    n = f["_"]
    if n == "auth.sendCode":
        if state.get("migrated") is None:
            state["migrated"] = 1
            return RpcError(303, "PHONE_MIGRATE_4")
        return {"_": "auth.sentCode", "phone_code_hash": "HASH", "type": {"_": "auth.sentCodeTypeApp"}}
    if n == "auth.signIn":
        assert f["phone_code"] == "12345" and f["phone_code_hash"] == "HASH"
        return RpcError(401, "SESSION_PASSWORD_NEEDED")
    if n == "account.getPassword":
        return {"_": "account.password", "has_password": 1, "srp_id": 555, "srp_B": i2b(GB),
                "hint": "pet", "current_algo": {"_": "passwordKdfAlgoSHA256SHA256PBKDF2HMACSHA512iter100000SHA256ModPow",
                "salt1": SALT1, "salt2": SALT2, "g": G, "p": i2b(P)}}
    if n == "auth.checkPassword":
        if not server_check(f["password"]):
            return RpcError(400, "PASSWORD_HASH_INVALID")
        return {"_": "auth.authorization", "user": ME}
    if n == "updates.getState":
        return {"_": "updates.state", "pts": 1, "qts": 0, "date": 0, "seq": 0, "unread_count": 0}
    if n == "messages.getDialogs":
        return {"_": "messages.dialogs",
                "dialogs": [{"_": "dialog", "peer": {"_": "peerUser", "user_id": 42}, "top_message": 10, "unread_count": 2,
                             "read_outbox_max_id": 0, "notify_settings": {"_": "peerNotifySettings"}},
                            {"_": "dialog", "peer": {"_": "peerChat", "chat_id": 900}, "top_message": 2, "unread_count": 0,
                             "notify_settings": {"_": "peerNotifySettings"}}],
                "messages": [{"_": "message", "id": 10, "peer_id": {"_": "peerUser", "user_id": 42},
                              "from_id": {"_": "peerUser", "user_id": 42}, "date": 1700000000, "message": "hey there"},
                             {"_": "message", "id": 2, "peer_id": {"_": "peerChat", "chat_id": 900},
                              "from_id": {"_": "peerUser", "user_id": 43}, "date": 1699990000, "message": "lol"}],
                "users": [USER, CYAN], "chats": [GROUP]}
    if n == "messages.getDialogFilters":
        return {"_": "messages.dialogFilters", "filters": [{"_": "dialogFilterDefault"},
                {"_": "dialogFilter", "id": 2, "title": {"_": "textWithEntities", "text": "Work", "entities": []},
                 "pinned_peers": [], "include_peers": [{"_": "inputPeerChat", "chat_id": 900}], "exclude_peers": []}]}
    if n == "contacts.getContacts":
        return {"_": "contacts.contacts", "contacts": [{"_": "contact", "user_id": 42, "mutual": 1}],
                "saved_count": 0, "users": [USER]}
    if n == "account.updateStatus":
        return 1
    if n == "messages.getHistory":
        assert f["peer"] == {"_": "inputPeerUser", "user_id": 42, "access_hash": 999}, f["peer"]
        return {"_": "messages.messages", "users": [USER], "chats": [], "messages": [
            {"_": "message", "id": 10, "peer_id": {"_": "peerUser", "user_id": 42}, "date": 1700000000, "message": "hey there"},
            {"_": "message", "id": 9, "out": 1, "peer_id": {"_": "peerUser", "user_id": 42}, "date": 1699999000, "message": "hi",
             "media": {"_": "messageMediaDocument", "document": {"_": "document", "attributes": [
                 {"_": "documentAttributeAudio", "voice": 1, "duration": 4}]}}},
            {"_": "message", "id": 8, "peer_id": {"_": "peerUser", "user_id": 42}, "date": 1699990000, "message": "",
             "media": {"_": "messageMediaDocument", "document": {"_": "document", "id": 77, "access_hash": 1,
                 "file_reference": "r", "date": 0, "mime_type": "audio/mpeg", "size": 300000, "dc_id": 4,
                 "thumbs": [], "attributes": [{"_": "documentAttributeAudio", "duration": 185,
                 "title": "Nokia Tune", "performer": "Nokia"}]}}}]}
    if n == "messages.readHistory":
        return {"_": "messages.affectedMessages", "pts": 2, "pts_count": 1}
    if n == "messages.sendMessage":
        state["sent"] = state.get("sent", 10) + 1
        if state["sent"] == 11:
            assert f["message"] == "Hello\nworld", repr(f["message"])
        else:
            assert f["reply_to"]["reply_to_msg_id"] > 0, f
        return {"_": "updateShortSentMessage", "id": state["sent"], "pts": 3, "pts_count": 1, "date": 1700000100, "out": 1}
    if n == "messages.editMessage":
        return {"_": "updates", "users": [], "chats": [], "date": 0, "seq": 0, "updates": [
            {"_": "updateEditMessage", "pts": 1, "pts_count": 1, "message": {
                "_": "message", "id": f["id"], "out": 1, "peer_id": {"_": "peerUser", "user_id": 42},
                "date": 1700000100, "message": f["message"], "edit_date": 1700000500}}]}
    if n == "messages.deleteMessages":
        state["deleted"] = (f["id"], f.get("revoke"))
        return {"_": "messages.affectedMessages", "pts": 1, "pts_count": 1}
    if n == "upload.getFile":
        assert f["location"]["_"] == "inputDocumentFileLocation" and f["limit"] == 32768
        size = 300000 - f["offset"]
        return {"_": "upload.file", "type": {"_": "storage.fileMp3"}, "mtime": 0,
                "bytes": "x" * min(size, 32768)}
    if n == "users.getFullUser":
        assert f["id"]["user_id"] == 42
        return {"_": "users.userFull", "full_user": {"_": "userFull", "id": 42, "about": "Retro phone fan",
                "settings": {}, "notify_settings": {}, "common_chats_count": 0}, "chats": [], "users": [USER]}
    if n == "account.updateNotifySettings":
        state["muted"] = f["settings"].get("mute_until")
        return 1
    if n == "messages.forwardMessages":
        state["forwarded"] = (f["id"], f["to_peer"]["_"], len(f["random_id"]))
        return {"_": "updates", "users": [], "chats": [], "date": 0, "seq": 0, "updates": []}
    if n == "messages.getDhConfig":
        return {"_": "messages.dhConfig", "g": G, "p": i2b(P), "version": 1, "random": "r" * 256}
    if n == "phone.requestCall":
        state["req"] = f
        return {"_": "phone.phoneCall", "users": [], "phone_call": {"_": "phoneCallWaiting",
                "id": 777, "access_hash": 9, "date": 0, "admin_id": 7, "participant_id": 42,
                "protocol": f["protocol"]}}
    if n == "phone.acceptCall":
        state["acc"] = f
        return {"_": "phone.phoneCall", "users": [], "phone_call": {"_": "phoneCallWaiting",
                "id": 555, "access_hash": 1, "date": 0, "admin_id": 42, "participant_id": 7,
                "protocol": f["protocol"]}}
    if n == "phone.confirmCall":
        state["conf"] = f
        return {"_": "phone.phoneCall", "users": [], "phone_call": {"_": "phoneCall",
                "id": 777, "access_hash": 9, "date": 0, "admin_id": 7, "participant_id": 42,
                "g_a_or_b": f["g_a"], "key_fingerprint": f["key_fingerprint"],
                "protocol": f["protocol"], "start_date": 0,
                "connections": [{"_": "phoneConnection", "id": 1, "ip": "1.2.3.4",
                                 "ipv6": "", "port": 598, "peer_tag": "\x01\x02" * 8}]}}
    if n == "phone.sendSignalingData":
        state.setdefault("sigs", []).append((f["peer"]["id"], f["data"]))
        return True
    if n == "phone.receivedCall":
        state["received"] = f["peer"]["id"]
        return True
    if n == "phone.discardCall":
        state["declined"] = f["peer"]["id"]
        state["discard"] = (f["peer"]["id"], f["reason"]["_"], f["duration"])
        return {"_": "updates", "users": [], "chats": [], "date": 0, "seq": 0, "updates": []}
    if n in ("upload.saveFilePart", "upload.saveBigFilePart"):
        import md5
        b = f["bytes"]
        up["parts"].append((n, f["file_id"], f["file_part"], len(b), f.get("file_total_parts")))
        up["md5"].update(b)
        up["bytes"] = up["bytes"] + len(b)
        k = f["file_part"]
        if up["fail"].get(k, 0) > 0:
            up["fail"][k] = up["fail"][k] - 1
            return RpcError(500, "INTERNAL")
        if up["hook"] is not None and k == up["hook"][0]:
            up["hook"][1]()
        return True
    if n == "messages.sendMedia":
        up["media"].append(f)
        if up["media_err"]:
            return RpcError(400, up["media_err"].pop(0))
        state["sent"] = state.get("sent", 10) + 1
        return {"_": "updates", "users": [], "chats": [], "date": 0, "seq": 0, "updates": [
            {"_": "updateNewMessage", "pts": 5, "pts_count": 1, "message": {
                "_": "message", "id": state["sent"], "out": 1,
                "peer_id": {"_": "peerUser", "user_id": 42}, "date": 1700000200,
                "message": f["message"], "media": {"_": "messageMediaUnsupported"}}}]}
    raise AssertionError("unexpected call " + n)

tgclient.mtproto.Session = FakeSession
# fewer PBKDF2 rounds for the test (the server side above uses 50 too)
_orig = tgsrp.PasswordHash
tgsrp.PasswordHash = lambda pw, s1, s2: _orig(pw, s1, s2, 50)

def press(name):
    import key_codes
    codes = {"up": key_codes.EKeyUpArrow, "down": key_codes.EKeyDownArrow,
             "left": key_codes.EKeyLeftArrow, "right": key_codes.EKeyRightArrow,
             "select": key_codes.EKeySelect}
    app.view.canvas.keys[codes.get(name, name)]()
    app.net.run()

def screen_text():
    del graphics.drawn[:]
    app.view.draw()
    return u" | ".join([t[2] for t in graphics.drawn])

errors = []
app = retrotele.App()
app.log = lambda m: (errors.append(m) if (str(m).startswith("paint") or str(m).startswith("error")) else (sys.stderr.write(str(m) + "\n") if "File" in str(m) else None))
app.net = FakeNet()
app.dir = TMP + os.sep
app.avatars = retrotele.tgui.Avatars(app, TMP + "/av.jpg")
app.cfg = tgclient.Store(TMP + "/settings.txt")
app.store = tgclient.Store(TMP + "/session.txt")
app.cfg.set("api_id", 12345); app.cfg.set("api_hash", "a" * 32); app.cfg.set("apid", 1)
app.setup_ap = lambda force=0: 1
answers[:] = ["+15551234567", "12345", PASSWORD]
popups[:] = [0]
app.start()
app.net.run()
assert app.screen == "welcome", app.screen
print "welcome:", screen_text()
app.login_phone()
app.net.run()
assert app.client.main_dc == 4, app.client.main_dc
assert app.client.me == 7
assert app.screen == "chats", app.screen
txt = screen_text()
print "chats:", txt
assert txt.find(u"Alice B") >= 0 and txt.find(u"hey there") >= 0 and txt.find(u"Book club") >= 0, txt
assert not errors, errors

# tabs: Unread (1), Personal, Groups (shows the group), the Work folder, Contacts
press("right")
assert app.list_view.tab == 1 and len(app.tab_rows(1)) == 1
press("right"); press("right")
groups = app.tab_rows(3)
assert len(groups) == 1 and groups[0]["key"] == "c900", groups
gt = screen_text(); assert gt.find(u"Cyan: ") >= 0 and gt.find(u"lol") >= 0, gt
tabs = app.tabs()
work = [i for i in range(len(tabs)) if tabs[i][0] == u"Work"][0]
assert [r["key"] for r in app.tab_rows(work)] == ["c900"], app.tab_rows(work)
contacts_tab = len(tabs) - 1
app.list_view.tab = contacts_tab; app.tab_changed(contacts_tab); app.net.run()
ct = screen_text()
print "contacts:", ct
assert ct.find(u"Alice B") >= 0 and ct.find(u"online") >= 0, ct
app.list_view.tab = 0; app.list_view.cur = 0
press("select")
assert app.screen == "chat"
txt = screen_text()
print "chat:", txt
msgs = app.msgs["u42"]
assert msgs[0]["audio"]["title"] == "Nokia Tune" and msgs[0]["audio"]["ext"] == "mp3"
assert msgs[0]["media"] == "Music Nokia - Nokia Tune", msgs[0]["media"]
answers[:] = [1]                 # "Download 0.3 MB?" isn't asked below 1 MB
del answers[:]
app.play_audio(msgs[0]); app.net.run()
import audio
assert app.screen == "player" and audio.played and audio.played[-1].endswith(u"f77.mp3"), audio.played
assert os.path.getsize(app.media.folder + "f77.mp3") == 300000
pl = screen_text()
print "player:", pl
assert pl.find(u"Nokia Tune") >= 0 and pl.find(u"3:05") >= 0, pl
app.close_player()
assert app.screen == "chat"
msgs = msgs[1:]
assert msgs[0]["media"] == "Voice message 0:04" and msgs[0]["text"] == "hi"
assert txt.find(u"hey there") >= 0 and txt.find(u"Voice message 0:04") >= 0 and txt.find(u"Message") >= 0
assert "messages.readHistory" in calls
assert app.dialogs[0]["unread"] == 0
press("up"); press("up")
assert app.view.selected()["id"] == 9

app.compose()
app.editor.set(u"Hello\u2029world")
app.send_now()
app.net.run()
assert app.msgs["u42"][-1]["text"] == "Hello\nworld", app.msgs["u42"][-1]
assert app.view.at_bottom()
screen_text()

# reply to the selected message
press("up")
app.reply_selected()
assert app.screen == "compose" and app.reply_to == app.view.selected()["id"]
app.editor.set(u"re")
app.send_now(); app.net.run()
assert screen_text().find(u"re") >= 0

# live update in the open chat, read receipt, and a message in another chat
app.client.update({"_": "updateShortMessage", "id": 20, "user_id": 42, "message": "new one",
                   "pts": 4, "pts_count": 1, "date": 1700000200})
app.net.run()
assert app.msgs["u42"][-1]["text"] == "new one"
app.client.update({"_": "updateReadHistoryOutbox", "peer": {"_": "peerUser", "user_id": 42},
                   "max_id": 12, "pts": 5, "pts_count": 1})
assert app.read_out("u42") == 12
app.back_to_chats()
toasts = []
_st = app.show_toast
app.show_toast = lambda a, b: (toasts.append((a, b)), _st(a, b))
app.client.update({"_": "updateShortChatMessage", "id": 3, "from_id": 42, "chat_id": 900,
                   "message": "group hello", "pts": 5, "pts_count": 1, "date": 1700000300})
app.net.run()
assert toasts and toasts[-1][0] == "Book club" and toasts[-1][1].find(u"Alice: group hello") >= 0, toasts
assert app.dialogs[0]["key"] == "c900" and app.dialogs[0]["unread"] == 1, app.dialogs[0]
screen_text()
# edit and delete my message 11, then an incoming Telegram call
app.chat_key = "u42"; app.back_to_chat()
mine = [m for m in app.msgs["u42"] if m["id"] == 11][0]
app.compose(0, mine)
assert app.editor.get() == u"Hello\nworld"
app.editor.set(u"Hello again")
app.send_now(); app.net.run()
mine = [m for m in app.msgs["u42"] if m["id"] == 11][0]
assert mine["text"] == "Hello again" and mine["edited"], mine
app.view_profile(); app.net.run()
pt = screen_text()
print "profile:", pt
assert pt.find(u"Retro phone fan") >= 0 and pt.find(u"+15550001111") >= 0, pt
app.mute("u42", 1); app.net.run()
assert state["muted"] == 2147483647 and app.dialog_for("u42")["muted"]
app.back_to_chat()
app.forward_message(mine); app.net.run()
assert state["forwarded"] == ([11], "inputPeerSelf", 1), state
popups[:] = [1]          # "Delete for me and Alice"
app.delete_message(mine); app.net.run()
assert state["deleted"] == ([11], 1), state
assert not [m for m in app.msgs["u42"] if m["id"] == 11]
def upd(c):
    app.client.update({"_": "updatePhoneCall", "phone_call": c})
    app.net.run()

def fp_of(kb):
    h = hashlib.sha1(kb).digest()[-8:]
    import struct
    return struct.unpack("<q", h)[0]

def incoming_req(cid, ga):
    upd({"_": "phoneCallRequested", "id": cid, "access_hash": 1, "date": 0, "admin_id": 42,
         "participant_id": 7, "g_a_hash": hashlib.sha256(i2b(ga)).digest(),
         "protocol": {"_": "phoneCallProtocol"}})

app.chat_key = "u42"
app.back_to_chat()
# incoming call, declined with the right softkey
ga = pow(G, 123456789123456789123456789, P)
incoming_req(555, ga)
assert app.screen == "call" and state["received"] == 555
t = screen_text(); print "call:", t
assert t.find(u"Incoming Telegram call") >= 0 and t.find(u"Alice B") >= 0, t
appuifw.app.exit_key_handler(); app.net.run()
assert state["discard"] == (555, "phoneCallDiscardReasonBusy", 0), state["discard"]
assert screen_text().find(u"Call ended") >= 0
app.close_call()
assert app.screen == "chat"

import callaudio_fake
retrotele.tgui.AUDIO_FACTORY = callaudio_fake.CallAudio
# incoming call accepted: caller (simulated) sends g_a_or_b after our g_b
ca = 98765432123456789987654321
ga = pow(G, ca, P)
incoming_req(555, ga)
app.call_primary(); app.net.run()
gb = tgcrypto.bytes_to_long(state["acc"]["g_b"])
assert 1 < gb < P - 1
kb = i2b(pow(gb, ca, P))
upd({"_": "phoneCall", "id": 555, "access_hash": 1, "date": 0, "admin_id": 42,
     "participant_id": 7, "g_a_or_b": i2b(ga), "key_fingerprint": fp_of(kb),
     "protocol": {"_": "phoneCallProtocol"}, "start_date": 0,
     "connections": [{"_": "phoneConnection", "id": 2, "ip": "5.6.7.8", "ipv6": "",
                      "port": 599, "peer_tag": "\x09" * 16}]})
t = screen_text(); print "call:", t
assert app.client.cs["state"] == "connected", app.client.cs
assert t.find(u"Connecting audio...") >= 0 and t.find(u"Key: ") >= 0, t
assert app.client.cs["kb"] == kb
fa = callaudio_fake.CallAudio.instances[-1]
assert fa.running and fa.relay[0] == kb and len(fa.relay[0]) == 256 and fa.relay[1] == 0, fa.relay
assert len(fa.relay[2]) == 1 and fa.relay[2][0]["ip"] == "5.6.7.8" and fa.relay[2][0]["peer_tag"] == "\x09" * 16
fa.helper_state("connected")
assert screen_text().find(u"Connected 00:") >= 0
fa.helper_state("reconnecting")
assert screen_text().find(u"Reconnecting...") >= 0
fa.helper_state("failed")
assert screen_text().find(u"Audio failed") >= 0
fa.helper_state("connected")
# in-call controls
t = screen_text()
assert t.find(u"[1] Mic | On") >= 0 and t.find(u"[2] Sound | Speaker") >= 0 and t.find(u"[3] Call | End") >= 0, t
mlabels = [m[0] for m in appuifw.app.menu]
assert u"Mute microphone" in mlabels and u"Sound output" in mlabels and u"Hang up" in mlabels, mlabels
assert u"Add person to call" not in mlabels and len(mlabels) <= 5, mlabels
sub = [m[1] for m in appuifw.app.menu if m[0] == u"Sound output"][0]
assert [x[0] for x in sub] == [u"Speaker", u"Earpiece", u"Bluetooth / auto"], sub
app.view.canvas.keys[ord("1")]()
assert fa.sent[-1] == "M1" and app.call_muted()
t = screen_text()
assert t.find(u"[1] Mic | Muted") >= 0, t
assert u"Unmute microphone" in [m[0] for m in appuifw.app.menu]
app.view.canvas.keys[ord("1")]()
assert fa.sent[-1] == "M0" and screen_text().find(u"[1] Mic | On") >= 0
app.view.canvas.keys[ord("2")]()
assert fa.sent[-1] == "R2" and screen_text().find(u"[2] Sound | Auto") >= 0
app.view.canvas.keys[ord("2")]()
assert fa.sent[-1] == "R0" and screen_text().find(u"[2] Sound | Earpiece") >= 0
app.view.canvas.keys[ord("2")]()
assert fa.sent[-1] == "R1" and screen_text().find(u"[2] Sound | Speaker") >= 0
sub[1][1]()
assert fa.sent[-1] == "R0"
# Options menu opened and cancelled (also its Sound output submenu): no menu callback runs and the
# call goes on. If the right softkey fires with the Cancel (some S60 builds), it asks first.
assert app.client.cs["state"] == "connected" and fa.running
state["discard"] = None
answers[:] = [None]                     # "End the call?" -> No / Cancel
appuifw.app.exit_key_handler(); app.net.run()
assert app.client.cs["state"] == "connected" and state["discard"] is None and fa.running and not notes[-1:] == [u"x"]
assert "End the call?" in qlog[-1] or u"End the call?" == qlog[-1], qlog[-1]
answers[:] = [0]
appuifw.app.exit_key_handler(); app.net.run()
assert app.client.cs["state"] == "connected" and state["discard"] is None
assert [m[0] for m in appuifw.app.menu][-1] == u"Hang up"      # the menu is intact
fa.helper_info(1, 0)
# timer tick keeps going, then hang up with centre
app.call_tick(); app.net.run()
state["discard"] = None
press("select")
assert state["discard"][:2] == (555, "phoneCallDiscardReasonHangup"), state["discard"]
assert not fa.running and "Q" in fa.sent, "hang-up must stop the audio helper"
app.close_call()

# a wrong fingerprint is refused
incoming_req(556, ga)
app.call_primary(); app.net.run()
upd({"_": "phoneCall", "id": 556, "access_hash": 1, "date": 0, "admin_id": 42,
     "participant_id": 7, "g_a_or_b": i2b(ga), "key_fingerprint": 12345,
     "protocol": {"_": "phoneCallProtocol"}, "start_date": 0, "connections": []})
assert app.client.cs["state"] == "ended" and app.client.cs["text"].find("FINGERPRINT") >= 0
app.close_call()

# outgoing call reaching connected
app.telegram_call("u42"); app.net.run()
req = state["req"]
assert req["user_id"]["user_id"] == 42 and req["protocol"]["max_layer"] == 92
assert app.screen == "call" and screen_text().find(u"Connecting...") >= 0
upd({"_": "phoneCallWaiting", "id": 777, "access_hash": 9, "date": 0, "admin_id": 7,
     "participant_id": 42, "protocol": {"_": "phoneCallProtocol"}, "receive_date": 5})
assert screen_text().find(u"Ringing...") >= 0
# busy: a second incoming call is declined without disturbing this one
incoming_req(600, ga)
assert state["discard"][:2] == (600, "phoneCallDiscardReasonBusy") and app.client.cs["id"] == 777
cb = 5555555555555555555555555
gbv = pow(G, cb, P)
upd({"_": "phoneCallAccepted", "id": 777, "access_hash": 9, "date": 0, "admin_id": 7,
     "participant_id": 42, "g_b": i2b(gbv), "protocol": {"_": "phoneCallProtocol"}})
conf = state["conf"]
assert hashlib.sha256(conf["g_a"]).digest() == req["g_a_hash"]
kb = i2b(pow(gbv, cb * 0 + 1, P))   # placeholder, replaced below
ga_n = tgcrypto.bytes_to_long(conf["g_a"])
kb = i2b(pow(ga_n, cb, P))
assert conf["key_fingerprint"] == fp_of(kb), "fingerprint"
assert app.client.cs["state"] == "connected" and app.client.cs["kb"] == kb
t = screen_text(); print "call:", t
assert t.find(u"Connecting audio...") >= 0, t
fo = callaudio_fake.CallAudio.instances[-1]
assert fo is not fa and fo.running and fo.relay[1] == 1 and fo.relay[0] == kb, fo.relay
# remote discard
upd({"_": "phoneCallDiscarded", "id": 777, "reason": {"_": "phoneCallDiscardReasonHangup"}})
assert screen_text().find(u"Call ended") >= 0 and app.client.cs["state"] == "ended"
assert not fo.running, "remote discard must stop the audio helper"
app.close_call()
assert app.screen == "chat"
# remote discard while ringing (incoming), then outgoing cancelled by us
incoming_req(557, ga)
upd({"_": "phoneCallDiscarded", "id": 557, "reason": {"_": "phoneCallDiscardReasonMissed"}})
assert app.client.cs["text"] == "Call ended (missed)"
app.close_call()
app.client.vcap_on = lambda: 1          # the capture flag file exists: it only turns the log on
app.telegram_call("u42"); app.net.run()
assert "video" not in state["req"] and not state["req"].get("video"), state["req"]    # always a voice call
del app.client.vcap_on
state["discard"] = None
appuifw.app.exit_key_handler(); app.net.run()
assert state["discard"][:2] == (777, "phoneCallDiscardReasonHangup"), state["discard"]
app.close_call()
screen_text()
app.save_cache()
assert os.path.getsize(TMP + "/cache.bin") > 100
# the cache restores the chat list
app2 = retrotele.App()
app2.dir = TMP + os.sep
app2.client = tgclient.Client(FakeNet(), app.schema, app2, app.store, 1, "x")
app2.load_cache()
assert [d["key"] for d in app2.dialogs] == [d["key"] for d in app.dialogs][:150]
assert app2.client.peer_name("u42") == "Alice B"
assert not errors, errors
assert open(TMP + "/session.txt").read().find("user_id=7") >= 0

# ---- Attach file
import struct, md5 as md5mod, filepick, fileinfo
UP = os.path.join(TMP, "up"); os.mkdir(UP)
def mkfile(name, size, head="", tail="", fill=None):
    path = os.path.join(UP, name)
    f = open(path, "wb")
    f.write(head)
    left = size - len(head) - len(tail)
    blk = fill or os.urandom(1024 * 1024)
    while left > 0:                       # repeated writes: never the whole file in memory
        n = min(left, len(blk))
        f.write(blk[:n]); left = left - n
    f.write(tail); f.close()
    return path
def reset_up():
    up["parts"] = []; up["md5"] = md5mod.new(); up["bytes"] = 0; up["fail"] = {}
    up["hook"] = None; up["media"] = []; up["media_err"] = []
def upload_ui(path, caption=u"", extra=()):
    reset_up()
    del qlog[:]
    if caption:
        popups[:] = [1]
        answers[:] = [caption, 1] + list(extra)
    else:
        answers[:] = [1] + list(extra)
    del notes[:]
    app.toast_text = None
    app.file_picked(path)
    seen = []
    old = app.redraw
    app.redraw = lambda: (seen.append(app.busy) if app.busy.startswith(u"Uploading") else None, old())
    app.net.run()
    app.redraw = old
    assert not answers, answers
    return seen
def check_parts(kind, size, psize=65536):
    ps = up["parts"]
    n = (size + psize - 1) // psize
    assert len(ps) == n, (len(ps), n)
    assert [p[2] for p in ps] == range(n), "part order"
    assert [p[3] for p in ps] == [psize] * (n - 1) + [size - psize * (n - 1)], "part sizes"
    assert len(set([p[1] for p in ps])) == 1 and ps[0][0] == kind
    assert up["bytes"] == size
    if kind == "upload.saveBigFilePart":
        assert [p[4] for p in ps] == [n] * n
app.back_to_chat()
appuifw.app.menu = []; app.update_chat_menu()
assert u"Attach file" in [m[0] for m in appuifw.app.menu], appuifw.app.menu
assert not [e for e in errors]

# 1. tiny picture -> inputFile + inputMediaUploadedPhoto, md5 of the whole file
p1 = mkfile("a.jpg", 100)
seen = upload_ui(p1, u"look")
m = up["media"][0]; fl = m["media"]["file"]
assert m["media"]["_"] == "inputMediaUploadedPhoto" and m["message"] == "look", m
assert fl["_"] == "inputFile" and fl["parts"] == 1 and fl["name"] == "a.jpg"
assert fl["md5_checksum"] == up["md5"].hexdigest() == md5mod.new(open(p1, "rb").read()).hexdigest()
assert fl["id"] == up["parts"][0][1] and up["parts"][0][0] == "upload.saveFilePart"
assert m["peer"]["user_id"] == 42 and "reply_to" not in m
assert app.toast_text and app.toast_text[0] == u"Sent", app.toast_text
assert app.upload is None and app.busy == u""
assert qlog == [u"Caption", u"Send a.jpg (100 B)?"], qlog
assert app.msgs["u42"][-1]["text"] == "look" and app.msgs["u42"][-1]["out"]
assert seen and seen[-1].startswith(u"Uploading a.jpg 100%"), seen

# 2. exactly one part, a document (pdf)
p2 = mkfile("doc.pdf", 65536)
upload_ui(p2)
check_parts("upload.saveFilePart", 65536)
m = up["media"][0]["media"]
assert m["_"] == "inputMediaUploadedDocument" and m["mime_type"] == "application/pdf"
assert m["attributes"] == [{"_": "documentAttributeFilename", "file_name": "doc.pdf"}], m
assert not m.get("force_file") and m["file"]["parts"] == 1

# 3. several parts, mp3: duration from the frame header, title/artist from ID3v1
tag = "TAG" + "Song".ljust(30, "\0") + "Artist".ljust(30, "\0") + "\0" * 65
assert len(tag) == 128
sz = 3 * 65536 + 5
p3 = mkfile("song.mp3", sz, "\xff\xfb\x90\x00", tag, "\0" * 4096)
upload_ui(p3)
check_parts("upload.saveFilePart", sz)
m = up["media"][0]["media"]
assert m["mime_type"] == "audio/mpeg"
aa = m["attributes"][0]
assert aa["_"] == "documentAttributeAudio" and aa["title"] == "Song" and aa["performer"] == "Artist", aa
assert aa["duration"] == int(sz * 8 / 128000.0 + 0.5), aa
assert m["attributes"][1]["file_name"] == "song.mp3"
assert m["file"]["md5_checksum"] == up["md5"].hexdigest()

# 4. > 10 MB: big upload, with the slow-phone warning above 20 MB
sz = 21 * 1024 * 1024 + 123
p4 = mkfile("huge.bin", sz)
seen = upload_ui(p4, u"", [1])
check_parts("upload.saveBigFilePart", sz)
assert qlog[-1] == u"This phone uploads slowly: about 4 minutes?", qlog
m = up["media"][0]["media"]
assert m["file"]["_"] == "inputFileBig" and not m["file"].has_key("md5_checksum")
assert m["file"]["parts"] == len(up["parts"]) and m["mime_type"] == "application/octet-stream"
assert seen[-1].find(u"100% (21.0/21.0 MB)") >= 0, seen[-1]

# 5. a picture over 10 MB is sent as a file (force_file); user can say no at the warning
sz = 10 * 1024 * 1024 + 1
p5 = mkfile("big.jpg", sz)
upload_ui(p5)
check_parts("upload.saveBigFilePart", sz)
m = up["media"][0]["media"]
assert m["_"] == "inputMediaUploadedDocument" and m["force_file"] and m["mime_type"] == "image/jpeg"
reset_up(); del qlog[:]
answers[:] = [1, 0]
app.file_picked(p4); app.net.run()
assert not up["parts"] and app.upload is None and not answers

# 6. video with duration and size from the mp4 boxes
def box(kind, body): return struct.pack(">I", 8 + len(body)) + kind + body
mvhd = box("mvhd", "\0" * 4 + "\0" * 8 + struct.pack(">II", 1000, 5400) + "\0" * 80)
tkhd = box("tkhd", "\0" * 4 + "\0" * 72 + struct.pack(">II", 320 << 16, 240 << 16))
mp4 = box("ftyp", "isom\0\0\0\0isom") + box("moov", mvhd + box("trak", tkhd))
p6 = os.path.join(UP, "clip.mp4"); open(p6, "wb").write(mp4 + "\0" * 5000)
assert fileinfo.mp4_info(p6) == (5.4, 320, 240), fileinfo.mp4_info(p6)
upload_ui(p6)
m = up["media"][0]["media"]
assert m["mime_type"] == "video/mp4" and not m.get("force_file")
assert m["attributes"][0] == {"_": "documentAttributeVideo", "duration": 5.0, "w": 320, "h": 240} or \
    m["attributes"][0]["duration"] == 5.0, m
assert m["attributes"][-1]["file_name"] == "clip.mp4"
p6b = os.path.join(UP, "odd.3gp"); open(p6b, "wb").write("junk" * 100)
upload_ui(p6b)
assert up["media"][0]["media"]["attributes"] == [{"_": "documentAttributeFilename", "file_name": "odd.3gp"}]

# 7. cancel in the middle
sz = 5 * 65536
p7 = mkfile("cancel.zip", sz)
reset_up(); up["hook"] = (2, app.cancel_upload)
answers[:] = [1]; app.file_picked(p7); app.net.run()
assert [p[2] for p in up["parts"]] == [0, 1, 2], up["parts"]
assert not up["media"] and app.upload is None and app.busy == u""
assert app.toast_text[0] == u"Upload cancelled", app.toast_text
# the app stays usable: the next upload works
upload_ui(p2)
assert len(up["media"]) == 1

# 8. retry: two failures of part 1 are survived, four are not
reset_up(); up["fail"] = {1: 2}
answers[:] = [1]; app.file_picked(mkfile("r.zip", 3 * 65536)); app.net.run()
assert [p[2] for p in up["parts"]] == [0, 1, 1, 1, 2] and len(up["media"]) == 1, up["parts"]
assert up["bytes"] == 5 * 65536
reset_up(); up["fail"] = {1: 9}
answers[:] = [1]; del notes[:]; app.file_picked(mkfile("r2.zip", 3 * 65536)); app.net.run()
assert [p[2] for p in up["parts"]] == [0, 1, 1, 1, 1] and not up["media"], up["parts"]
assert app.upload is None and notes and notes[-1].startswith(u"Not sent"), notes

# 9. server errors: plain text; unusable photo falls back to a document
reset_up(); up["media_err"] = ["FILE_PARTS_INVALID"]
answers[:] = [1]; del notes[:]; app.file_picked(p2); app.net.run()
assert notes[-1] == u"Not sent: " + retrotele.ERRORS["FILE_PARTS_INVALID"], notes
assert retrotele.err_msg(RpcError(400, "FILE_PART_5_MISSING")).find(u"part of the file") >= 0
reset_up(); up["media_err"] = ["PHOTO_INVALID_DIMENSIONS"]
answers[:] = [1]; app.file_picked(p1); app.net.run()
assert [x["media"]["_"] for x in up["media"]] == ["inputMediaUploadedPhoto", "inputMediaUploadedDocument"]
assert up["media"][1]["media"]["force_file"] and len(up["parts"]) == 1
assert app.toast_text[0] == u"Sent"
# empty and missing files
del notes[:]; app.file_picked(mkfile("empty.txt", 0)); assert notes[-1] == u"The file is empty.", notes
app.file_picked(os.path.join(UP, "nope.txt")); assert notes[-1] == u"Cannot read the file."

# 10. only one upload at a time; client level: reply_to and exact progress
reset_up()
prog = []
oks = []
h = app.client.send_file("u42", p3, u"c", 5, lambda d, t: prog.append((d, t)), oks.append, None)
app.upload = {"name": "x", "size": 1, "pct": 0, "key": "u42", "h": h}
del notes[:]
app.attach_file()
assert notes[-1] == u"An upload is already running."
app.update_chat_menu()
assert u"Cancel upload" in [m[0] for m in appuifw.app.menu] and u"Attach file" not in [m[0] for m in appuifw.app.menu]
app.upload = None
app.net.run()
sz = os.path.getsize(p3)
assert prog == [(min(sz, 65536 * (i + 1)), sz) for i in range(4)], prog
assert oks == [None] and up["media"][0]["reply_to"]["reply_to_msg_id"] == 5
assert up["media"][0]["message"] == "c"
# big parts: more than 4000 parts at 64 KB switches to larger parts
class Probe(tgclient.Upload):
    def next_part(self): pass
pr = Probe(app.client, "u42", p4, "", 0, None, None, None)
pr.start(); assert pr.part_size == 65536 and pr.parts == 337
pr.finish_file()

# 11. file browser
pk = os.path.join(TMP, "pick"); os.makedirs(pk + "/sys"); os.makedirs(pk + "/Zed"); os.makedirs(pk + "/alpha/in")
for nm, n in (("b.txt", 5), ("A.zip", 2048), ("c.sis", 3 * 1024 * 1024)):
    open(os.path.join(pk, nm), "wb").write("x" * n)
filepick.SEP = "/"
root = pk + "/"
filepick.is_root = lambda path: path == root or path == TMP + "/pickC/"
filepick.drives = lambda: [u"C:", u"E:", u"Z:"]
filepick.drive_path = lambda d: {u"C:": TMP + "/pickC/", u"E:": root}[d]
dd, ff = filepick.list_dir(root)
assert dd == ["alpha", "Zed"] and ff == [("A.zip", 2048), ("b.txt", 5), ("c.sis", 3145728)], (dd, ff)
assert filepick.parent(root) == u"" and filepick.parent(pk + "/alpha/in") == pk + "/alpha/"
assert filepick.parent(pk + "/alpha") == root
os.makedirs(TMP + "/pickC")
app.cfg.set("last_dir", None)
app.back_to_chat()
app.attach_file()
pkr = app.picker
assert app.screen == "filepick" and pkr.path == u"", pkr.path
assert [e[1] for e in pkr.entries] == [u"C:", u"E:"], pkr.entries
pkr.draw()
pkr.key("down"); pkr.key("down"); assert pkr.cur == 0   # wraps
pkr.key("down"); pkr.key("select")
assert pkr.path == root and [e[1] for e in pkr.entries] == ["alpha", "Zed", "A.zip", "b.txt", "c.sis"], pkr.entries
pkr.draw()
assert pkr.stat(pk + "/c.sis")[0] == 3 * 1024 * 1024
pkr.key("5")   # alpha
assert pkr.path == pk + "/alpha/" and app.cfg.get("last_dir") == pk + "/alpha/"
pkr.key("left"); assert pkr.path == root and pkr.entries[pkr.cur][1] == "alpha"
pkr.cycle_sort(); assert pkr.sort == 1 and [e[1] for e in pkr.entries][2:] == ["c.sis", "A.zip", "b.txt"], pkr.entries
pkr.cycle_sort(); pkr.cycle_sort(); assert pkr.sort == 0
pkr.goto([pk + "/nonexistent/"]); assert pkr.msg and pkr.path == root
pkr.key("6"); assert pkr.path == pk + "/alpha/"
pkr.key("left"); assert pkr.path == root
pkr.key("left"); assert pkr.path == u"" and app.picker is not None
pkr.key("left"); assert app.picker is None and app.screen == "chat"
# restart in the remembered folder, then pick a file through the whole flow
app.attach_file(); pkr = app.picker
assert pkr.path == root, pkr.path
pkr.cur = 3; reset_up()
answers[:] = [1]
pkr.key("0"); app.net.run()      # nothing marked: sends the highlighted file
assert app.picker is None and len(up["media"]) == 1
assert up["media"][0]["media"]["file"]["name"] == "b.txt" and up["media"][0]["media"]["mime_type"] == "text/plain"
assert app.screen == "chat" and not errors, errors
# exit while uploading asks first
reset_up(); answers[:] = [1]
app.file_picked(p7)
answers[:] = [0]
app.exit(); assert app.upload is not None and not answers
answers[:] = [1]
app.upload["h"].cancel(); app.upload = None
print "attach OK"
# caption popup: cancel, empty/cancelled caption text, multi-file queue
reset_up(); popups[:] = [2]; answers[:] = []
app.file_picked(p2); app.net.run()
assert not up["parts"] and not up["media"] and not popups
reset_up(); popups[:] = [1]; answers[:] = [None, 1]
app.file_picked(p2); app.net.run()
assert len(up["media"]) == 1 and up["media"][0]["message"] == "", up["media"]
m1 = mkfile("m1.zip", 2000); m2 = mkfile("m2.zip", 3000); m3 = mkfile("m3.zip", 4000)
reset_up(); popups[:] = [1]; answers[:] = [u"cap", 1]; del qlog[:]
seen = []
oldr = app.redraw
app.redraw = lambda: (seen.append(app.busy) if app.busy.startswith(u"Uploading") else None, oldr())
app.file_picked([m1, m2, m3]); app.net.run()
app.redraw = oldr
assert qlog[-1] == u"Send 3 files (9 KB)?", qlog
assert [x["message"] for x in up["media"]] == ["cap", "", ""], up["media"]
assert [x["media"]["file"]["name"] for x in up["media"]] == ["m1.zip", "m2.zip", "m3.zip"]
assert [s for s in seen if s.startswith(u"Uploading 2/3 m2.zip")], seen
assert app.toast_text[0] == u"Sent 3 files" and app.upload is None and app.queue is None
# first fails: continue with the rest; stop at the question
reset_up(); up["media_err"] = ["FILE_PARTS_INVALID"]; popups[:] = [0]; answers[:] = [1, 1]
app.file_picked([m1, m2]); app.net.run()
assert len(up["media"]) == 2 and up["media"][1]["media"]["file"]["name"] == "m2.zip" and app.toast_text[0] == u"Sent"
reset_up(); up["media_err"] = ["FILE_PARTS_INVALID"]; popups[:] = [0]; answers[:] = [1, 0]
app.file_picked([m1, m2]); app.net.run()
assert len(up["media"]) == 1 and app.queue is None and app.upload is None
# marks in the picker
app.attach_file(); pkr = app.picker
pkr.path = root; pkr.load(u""); pkr.cur = 3
pkr.key("select"); pkr.cur = 4; pkr.key("select")
assert len(pkr.marks) == 2 and pkr.entries[3][2] in pkr.marks
pkr.cur = 2; pkr.key("select"); assert len(pkr.marks) == 3; pkr.key("select"); assert len(pkr.marks) == 2
pkr.draw()
reset_up(); got = []
pkr.on_pick = lambda ps: got.append(ps)
pkr.key("0"); assert len(got[0]) == 2
pkr.unmark_all(); assert not pkr.marks
pkr.mark_all(); assert len(pkr.marks) == len([e for e in pkr.entries if e[0] == "file"]) >= 3, (pkr.marks, pkr.entries, pkr.path)
pkr.cancel(); assert app.picker is None
app.call_test()
app.view.toggle(); app.net.run(); app.view.tick()
ct = screen_text()
print "call test:", ct
assert ct.find(u"32000 B/s") >= 0 and ct.find(u"running") >= 0, ct
app.view.opus_test()
ot = screen_text()
print "opus test:", ot
assert ot.find(u"Self-test OK") >= 0 and ot.find(u"Effort 0: 4.0 ms") >= 0 and ot.find(u"fast enough") >= 0, ot
# ---- 2.7.7 (official apps): signalling plumbing + helper start
saved_view, saved_screen = app.view, app.screen
import callaudio
sent277 = []
started277 = []
class FakeE32Exe:
    pass
callaudio._open_orig = callaudio.CallAudio._open
callaudio.CallAudio._open = lambda self: "sock"
callaudio.CallAudio._arm = lambda self: None
callaudio.CallAudio._sendto = lambda self, d: (sent277.append(d), 1)[1]
callaudio.e32.start_exe = lambda *a: started277.append(a)
cfgs = []
callaudio.CallAudio.write_cfg = lambda self, t: (cfgs.append(t), "C:\\x")[1]
rca = callaudio.CallAudio()
states277 = []
sigs277 = []
conns277 = [{"_": "phoneConnection", "id": -4611686018427387905, "ip": "9.8.7.6", "port": 596,
             "peer_tag": "\xab" * 16},
            {"_": "phoneConnection", "tcp": 1, "id": 7, "ip": "9.8.7.7", "port": 80, "peer_tag": "\x01" * 16},
            {"_": "phoneConnectionWebrtc", "id": 8, "ip": "9.8.7.8", "port": 3478, "turn": 1}]
assert rca.start_relay277("K" * 256, 1, conns277, states277.append, 5, sigs277.append) == 1
assert started277 and started277[0][1] == u"relay 7200", started277
cl = cfgs[0].split("\n")
assert cl[0] == "ver=277" and cl[1] == "out=1" and cl[2] == "key=" + "4b" * 256, cl[:3]
assert cl[3].startswith("rnd=") and len(cl[3]) == 4 + 112
assert "c=-4611686018427387905,9.8.7.6,596," + "ab" * 16 + ",0,0" in cl, cl
assert "c=7,9.8.7.7,80," + "01" * 16 + ",1,0" in cl
assert "c=8,9.8.7.8,3478,,0,1" in cl
assert "iap=5" in cl
rca.send_signaling("one")
rca.send_signaling("two")
assert sent277 == [], sent277
rca._handle("S ready")
assert sent277[:2] == ["Gone", "Gtwo"], sent277
assert states277 == [], states277
rca.send_signaling("three")
assert sent277[-1] == "Gthree"
rca._handle("G\x01\x02blob")
assert sigs277 == ["\x01\x02blob"], sigs277
rca._handle("S connected")
assert states277 == ["connected"]
rca.stop()
# client: phone.sendSignalingData and the incoming update hook
cs277 = {"id": 4242, "hash": 77, "state": "connected", "start": 1, "kb": "K" * 256, "out": 1,
         "conns": conns277, "fp": 1, "g_a": "x", "emoji": "", "ver": 1}
app.client.send_signaling(cs277, "payload1")
app.net.run()
assert state["sigs"] == [(4242, "payload1")], state.get("sigs")
got_sig = []
app.call_signaling = got_sig.append
app.client.cs = cs277
app.client.one_update({"_": "updatePhoneCallSignalingData", "phone_call_id": 4242, "data": "d1"})
app.client.one_update({"_": "updatePhoneCallSignalingData", "phone_call_id": 1, "data": "other"})
assert got_sig == ["d1"], got_sig
del app.call_signaling
# early signalling is kept until the helper exists, then handed over in order
import callaudio_fake
retrotele.tgui.AUDIO_FACTORY = callaudio_fake.CallAudio
app.call_signaling("e1")
app.call_signaling("e2")
app.client.set_call_version("2.7.7")
app.call_ready(cs277)
f277 = callaudio_fake.CallAudio.instances[-1]
assert f277.v277 and f277.signals == ["e1", "e2"], f277.signals
assert f277.want_rx, "receiving the peer's video is on by default (0.15.0, config video_rx = 0 turns it off)"
f277.on_signal("out1")
assert state["sigs"][-1] == (4242, "out1"), state["sigs"]
app.call_signaling("late")
assert f277.signals[-1] == "late"
# send-only video: menu entries, key 4 / 6, status line, clean stop with the call
class FakeCV:
    made = []
    def __init__(self, audio, on_change, log):
        self.audio = audio; self.on_change = on_change; self.live = 0; self.cam = 1; self.stopped = 0
        self.sw = 0; self.txt = u"Video on - front camera"
        FakeCV.made.append(self)
    def start(self, cam):
        self.live = 1; self.audio.set_video(1); return 1
    def active(self): return self.live
    def status_text(self): return self.txt
    def stop(self):
        self.live = 0; self.stopped = self.stopped + 1; self.audio.set_video(0)
    def switch_camera(self): self.sw = self.sw + 1; return 1
    def frame(self): return None
    rx = 0; pf = None; ps = u""; pfail = 0; up = 0
    def helper_up(self): return self.up
    def start_rx(self): self.rx = 1; self.up = 1; return 1
    def peer_frame(self): return self.pf
    def peer_status(self): return self.ps
    def peer_failed(self): return self.pfail
    def stop_send(self): self.live = 0; self.audio.set_video(0)
import types as _types
_fake_mod = _types.ModuleType("callvideo")
_fake_mod.CallVideo = FakeCV
_fake_mod.CAM_FRONT = 1
sys.modules["callvideo"] = _fake_mod
app.client.cs = cs277
cs277["state"] = "connected"
cs277["key"] = "u42"
cs277["text"] = u""
app.audio_state = "connected"
app.call_ready(cs277)
app.audio_state = "connected"
fv = callaudio_fake.CallAudio.instances[-1]
saved_menu_view = app.view
app.screen = "call"
app.view = retrotele.tgui.CallView(app)
app.view.canvas = saved_view.canvas
app.call_menu()
labels = [m[0] for m in appuifw.app.menu]
assert u"Turn video on" in labels and u"Switch camera" not in labels, labels
_t0 = screen_text()
assert u"[4] Video" in _t0 and u"Off" in _t0, _t0
app.view.key("4")
cvf = FakeCV.made[-1]
assert cvf.live and fv.want_video and fv.sent[-1] == "V1", fv.sent
labels = [m[0] for m in appuifw.app.menu]
assert u"Turn video off" in labels and u"Switch camera" in labels, labels
t = screen_text()
assert t.find(u"Video on -") >= 0 and t.find(u"[7] show me") >= 0 and t.find(u"[6] Camera") >= 0 and t.find(u"Left: Options") >= 0, t
app.view.key("6")
assert cvf.sw == 1
fv.peer_video = 2
t = screen_text()
assert t.find(u"video is on (cannot be shown on this phone)") >= 0 or t.find(u"cannot be shown") >= 0, t
fv.peer_video = -1
# the peer's video: the helper starts when the peer turns video on, the picture fills the screen
app.stop_call_video(); app.call_video = None
fv.want_rx = 1; fv.peer_video = 2
app.audio_info()
pv = app.call_video
pv.txt = u""
assert pv is not None and pv.rx == 1 and pv.live == 0, pv
t = screen_text()
assert t.find(u"video is on (cannot be shown") >= 0, t           # no picture yet: the old notice
pv.ps = u"Peer video: decoder cannot decode this stream (High profile)"; pv.pfail = 1
t = screen_text()
assert t.find(u"cannot be shown") >= 0 and t.find(u"High profile") >= 0, t
pv.pfail = 0; pv.ps = u"Peer video: receiving 176x320"
t = screen_text()
assert t.find(u"cannot be shown") < 0 and t.find(u"receiving 176x320") >= 0, t
class _Img:
    size = (176, 320)
pv.pf = (_Img(), 176, 320)
t = screen_text()
assert t.find(u"8: show buttons") >= 0 and t.find(u"[1] Mic") < 0, t             # full screen picture
app.view.key("8")
t = screen_text()
assert t.find(u"8: full screen") >= 0 and t.find(u"[1] Mic") >= 0 and t.find(u"[4] Video") >= 0, t
app.view.key("8")
app.view.key("4")                                  # our camera on while the peer is shown
assert pv.live == 1 and fv.want_video
app.view.key("4")
assert pv.live == 0 and not fv.want_video
pv.pf = None
app.stop_call_audio()                 # hang up / app exit: video stops before the audio helper
assert cvf.stopped >= 1 and not fv.want_video and app.call_video is None
# voice-only call: no video entries when the call is not 2.7.7
app.client.set_call_version("2.4.4")
cs277["state"] = "connected"
app.call_ready(cs277)
app.call_menu()
labels = [m[0] for m in appuifw.app.menu]
assert not [l for l in labels if l.find(u"video") >= 0 or l.startswith(u"Switch")], labels
t = screen_text()
assert t.find(u"Video") < 0, t
del sys.modules["callvideo"]
app.client.set_call_version("2.4.4")
app.stop_call_audio()
app.client.cs = None
app.view, app.screen = saved_view, saved_screen
import callaudio_fake
retrotele.tgui.AUDIO_FACTORY = callaudio_fake.CallAudio
app.view.echo_call_audio()
fa = callaudio_fake.CallAudio.instances[-1]
fa.deliver("opus1")
assert fa.sent == ["opus1"], fa.sent
app.view.echo_tick()
assert screen_text().find(u"Helper packets 1") >= 0
app.view.stop()
assert fa.sent[-1] == "Q" and not fa.running
app.exit()
import tgcall
assert not tgcall._state["on"]
assert open(TMP + "/cache.bin").read()
print "flow OK"
shutil.rmtree(TMP)
