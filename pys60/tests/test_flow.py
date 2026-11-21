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

USER = {"_": "user", "id": 42, "access_hash": 999, "first_name": "Alice", "last_name": "B"}
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
                "dialogs": [{"_": "dialog", "peer": {"_": "peerUser", "user_id": 42}, "top_message": 10, "unread_count": 2}],
                "messages": [{"_": "message", "id": 10, "peer_id": {"_": "peerUser", "user_id": 42},
                              "from_id": {"_": "peerUser", "user_id": 42}, "date": 1700000000, "message": "hey there"}],
                "users": [USER], "chats": []}
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
        assert f["message"] == "Hello\nworld", repr(f["message"])
        return {"_": "updateShortSentMessage", "id": 11, "pts": 3, "pts_count": 1, "date": 1700000100, "out": 1}
    raise AssertionError("unexpected call " + n)

tgclient.mtproto.Session = FakeSession
# fewer PBKDF2 rounds for the test (the server side above uses 50 too)
_orig = tgsrp.PasswordHash
tgsrp.PasswordHash = lambda pw, s1, s2: _orig(pw, s1, s2, 50)

app = retrotele.App()
app.net = FakeNet()
app.dir = TMP + os.sep
app.cfg = tgclient.Store(TMP + "/settings.txt")
app.store = tgclient.Store(TMP + "/session.txt")
app.cfg.set("api_id", 12345); app.cfg.set("api_hash", "a" * 32); app.cfg.set("apid", 1)
app.setup_ap = lambda force=0: 1
answers[:] = ["+15551234567", "12345", PASSWORD]
popups[:] = [0]
app.start()
app.net.run()
assert app.client.main_dc == 4, app.client.main_dc
assert app.client.me == 7
assert app.screen == "chats", app.screen
rows = app.chat_list.rows
print "chats:", rows
assert rows[0][0] == u"(2) Alice B" and rows[0][1].find(u"hey there") >= 0

app.chat_list.cur = 0
app.open_selected()
app.net.run()
mrows = app.msg_list.rows
print "messages:", mrows
assert mrows[0][0].startswith(u"You") and mrows[0][1] == u"[Voice message 4s] hi"
assert mrows[1][1] == u"hey there" and mrows[-1][0].find(u"Write") >= 0
assert "messages.readHistory" in calls
assert app.dialogs[0]["unread"] == 0

app.compose()
app.editor.set(u"Hello\u2029world")
app.send_now()
app.net.run()
assert app.msg_list.rows[-2][1] == u"Hello world", app.msg_list.rows[-2]

# live update in the open chat, and in another chat
app.client.update({"_": "updateShortMessage", "id": 12, "user_id": 42, "message": "new one",
                   "pts": 4, "pts_count": 1, "date": 1700000200})
app.net.run()
assert app.msg_list.rows[-2][1] == u"new one"
app.back_to_chats()
app.client.update({"_": "updateShortMessage", "id": 3, "user_id": 43, "message": "who is this",
                   "pts": 5, "pts_count": 1, "date": 1700000300})
app.net.run()   # unknown user -> refresh_needed -> getDialogs again
print "chats now:", app.chat_list.rows
assert notes[-1].find(u"who is this") >= 0
assert open(TMP + "/session.txt").read().find("user_id=7") >= 0
print "flow OK"
shutil.rmtree(TMP)
