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
    def __init__(self): self.q = []
    def later(self, sec, f): self.q.append(f)
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
                 {"_": "documentAttributeAudio", "voice": 1, "duration": 4}]}}}]}
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
    if n == "phone.discardCall":
        state["declined"] = f["peer"]["id"]
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
assert txt.find(u"Alice B") >= 0 and txt.find(u"hey there") >= 0 and txt.find(u"Work") >= 0, txt
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
popups[:] = [1]          # "Delete for me and Alice"
app.delete_message(mine); app.net.run()
assert state["deleted"] == ([11], 1), state
assert not [m for m in app.msgs["u42"] if m["id"] == 11]
popups[:] = [0]          # Decline
app.client.update({"_": "updatePhoneCall", "phone_call": {"_": "phoneCallRequested", "id": 555,
                   "access_hash": 1, "date": 0, "admin_id": 42, "participant_id": 7,
                   "g_a_hash": "", "protocol": {"_": "phoneCallProtocol"}}})
app.net.run()
assert state["declined"] == 555
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
print "flow OK"
shutil.rmtree(TMP)
