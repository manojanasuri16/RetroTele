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
def query(label, kind, initial=None):
    assert answers, "unexpected query: %r" % label
    a = answers.pop(0)
    print "  query %r -> %r" % (label, a)
    return a
appuifw.query = query
appuifw.popup_menu = lambda items, title=None: popups.pop(0)

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
    if n == "phone.receivedCall":
        state["received"] = f["peer"]["id"]
        return True
    if n == "phone.discardCall":
        state["declined"] = f["peer"]["id"]
        state["discard"] = (f["peer"]["id"], f["reason"]["_"], f["duration"])
        return {"_": "updates", "users": [], "chats": [], "date": 0, "seq": 0, "updates": []}
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
app.log = lambda m: (errors.append(m) if (str(m).startswith("paint") or str(m).startswith("error")) else None)
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
assert t.find(u"Connected 00:") >= 0 and t.find(u"audio coming soon") >= 0 and t.find(u"Key: ") >= 0, t
assert app.client.cs["kb"] == kb
# timer tick keeps going, then hang up with centre
app.call_tick(); app.net.run()
state["discard"] = None
press("select")
assert state["discard"][:2] == (555, "phoneCallDiscardReasonHangup"), state["discard"]
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
assert app.screen == "call" and screen_text().find(u"Calling...") >= 0
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
assert t.find(u"Connected 00:") >= 0, t
# remote discard
upd({"_": "phoneCallDiscarded", "id": 777, "reason": {"_": "phoneCallDiscardReasonHangup"}})
assert screen_text().find(u"Call ended") >= 0 and app.client.cs["state"] == "ended"
app.close_call()
assert app.screen == "chat"
# remote discard while ringing (incoming), then outgoing cancelled by us
incoming_req(557, ga)
upd({"_": "phoneCallDiscarded", "id": 557, "reason": {"_": "phoneCallDiscardReasonMissed"}})
assert app.client.cs["text"] == "Call ended (missed)"
app.close_call()
app.telegram_call("u42"); app.net.run()
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
app.call_test()
app.view.toggle(); app.net.run(); app.view.tick()
ct = screen_text()
print "call test:", ct
assert ct.find(u"32000 B/s") >= 0 and ct.find(u"running") >= 0, ct
app.view.opus_test()
ot = screen_text()
print "opus test:", ot
assert ot.find(u"Self-test OK") >= 0 and ot.find(u"Effort 0: 4.0 ms") >= 0 and ot.find(u"fast enough") >= 0, ot
app.exit()
import tgcall
assert not tgcall._state["on"]
assert open(TMP + "/cache.bin").read()
print "flow OK"
shutil.rmtree(TMP)
