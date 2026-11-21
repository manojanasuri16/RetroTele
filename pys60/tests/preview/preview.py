# Drives RetroTele with sample chats and records each screen's drawing
# (Python 2.7). Run via preview.sh, which renders the PNGs.
import sys, os, json, time, tempfile, shutil
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "fake_s60"))
sys.path.insert(0, os.path.join(HERE, "rec"))      # recording graphics wins
sys.path.insert(0, os.path.join(HERE, "..", ".."))
TMP = tempfile.mkdtemp()
shutil.copy(os.path.join(HERE, "..", "..", "schema.txt"), TMP)
os.chdir(TMP)
import appuifw, graphics
screens = []
current = {}


class Canvas:
    def __init__(self, redraw_callback=None, event_callback=None):
        self.size = (240, 292)
        self.keys = {}

    def bind(self, code, cb):
        self.keys[code] = cb

    def blit(self, img, **k):
        current["ops"] = list(img.ops)


appuifw.Canvas = Canvas
appuifw.note = lambda *a: None
import retrotele, tgclient
from mtproto import RpcError

NOW = int(time.time())
ME = {"_": "user", "id": 7, "self": 1, "first_name": "Alex", "last_name": "Rivera"}


def U(i, first, last="", **kw):
    d = {"_": "user", "id": i, "access_hash": i * 3, "first_name": first, "last_name": last}
    d.update(kw)
    return d


def C(i, title, kind, n=0):
    if kind == "chat":
        return {"_": "chat", "id": i, "title": title, "participants_count": n, "date": 0,
                "version": 1, "photo": {"_": "chatPhotoEmpty"}}
    d = {"_": "channel", "id": i, "access_hash": i, "title": title, "date": 0,
         "photo": {"_": "chatPhotoEmpty"}, "participants_count": n}
    if kind == "mega":
        d["megagroup"] = 1
    else:
        d["broadcast"] = 1
    return d


ONLINE = {"_": "userStatusOnline", "expires": NOW + 300}
USERS = [ME, U(777000, "Telegram", verified=1), U(11, "Sam", "Carter", contact=1,
         phone="15550001234", status=ONLINE), U(12, "Mia", "Chen", contact=1,
         status={"_": "userStatusOffline", "was_online": NOW - 1500}),
         U(13, "Jakob"), U(14, "Cyan"), U(15, "Leo", "Park", contact=1,
         status={"_": "userStatusRecently"})]
CHATS = [C(500, "Retro Phones", "chat", 6), C(600, "Daily Deals", "channel", 90000),
         C(700, "Retro Phone Club", "mega", 412), C(800, "Job Alerts", "channel", 5000)]


def P(k):
    return {"u": {"_": "peerUser", "user_id": int(k[1:])},
            "c": {"_": "peerChat", "chat_id": int(k[1:])},
            "h": {"_": "peerChannel", "channel_id": int(k[1:])}}[k[0]]


def M(k, mid, frm, text, ago, out=0, **kw):
    m = {"_": "message", "id": mid, "peer_id": P(k), "date": NOW - ago, "message": text,
         "out": out}
    if frm:
        m["from_id"] = {"_": "peerUser", "user_id": frm}
    m.update(kw)
    return m


DIALOGS = [
    ("u7", M("u7", 50, 7, "QT 4.6.3 (legacy installer, for S60v3)", 4000, 1), 0, 1, 0),
    ("u777000", M("u777000", 900, 777000, "New login. Dear Alex, we detected a login into your "
                  "account from a new device.", 600), 1, 0, 0),
    ("c500", M("c500", 30, 7, "Photos from the weekend", 7200, 1),
     0, 0, 0),
    ("h600", M("h600", 7000, 0, "Headphones 40% off today only",
               9000), 36, 0, 1),
    ("u11", M("u11", 77, 11, "Hie", 10000), 0, 0, 0),
    ("h700", M("h700", 4400, 13, "Also, cool cats", 12000), 119, 0, 0),
    ("h800", M("h800", 300, 0, "New role: junior designer, remote", 13000), 11, 0, 0),
    ("u12", M("u12", 88, 12, "ok see you tomorrow at the office", 90000), 1, 0, 0),
]

HISTORY = [
    {"_": "messageService", "id": 4380, "peer_id": P("h700"), "from_id": {"_": "peerUser", "user_id": 14},
     "date": NOW - 90000, "action": {"_": "messageActionChatJoinedByLink"}},
    M("h700", 4390, 13, "Anyone got Opera Mini 4.4 working on the N79? Mine keeps closing "
      "after the splash screen.", 86000),
    M("h700", 4391, 14, "Try the S60v3 signed build, the unsigned one crashes", 85000,
      reply_to={"_": "messageReplyHeader", "reply_to_msg_id": 4390}),
    M("h700", 4395, 13, "", 4000, media={"_": "messageMediaPhoto"}),
    M("h700", 4396, 7, "Running RetroTele on my N79 right now \\o/", 3000, 1),
    M("h700", 4397, 14, "", 2500, media={"_": "messageMediaDocument", "document": {
        "_": "document", "attributes": [{"_": "documentAttributeSticker", "alt": ""}]}}),
    M("h700", 4398, 13, "Also, cool cats", 1200,
      fwd_from={"_": "messageFwdHeader", "from_name": "Cat Facts", "date": 0}),
]

PRIVATE = [
    M("u11", 70, 11, "Bro did you install that app?", 9000),
    M("u11", 71, 7, "Yes! Telegram on the N79 :)", 8800, 1),
    M("u11", 72, 7, "It even shows read ticks and replies", 8700, 1),
    M("u11", 77, 11, "Hie", 600),
]


class FakeSession:
    def __init__(self, net, schema, events, dc_id, *a):
        self.net = net; self.events = events; self.dc_id = dc_id
        self.time_offset = 0; self.state = "ready"; self.gen = 0
        self.auth_key = "k" * 256; self.salt = "s" * 8

    def start(self):
        self.net.later(0, lambda: self.events.connected(self))

    def close(self):
        pass

    def invoke(self, f, ok, err):
        n = f["_"]
        res = {"_": "boolTrue"}
        if n == "messages.getDialogs":
            if f.get("folder_id"):
                res = {"_": "messages.dialogs", "dialogs": [], "messages": [], "users": [], "chats": []}
            else:
                ds = []
                ms = []
                for k, m, unread, pinned, muted in DIALOGS:
                    ns = {"_": "peerNotifySettings"}
                    if muted:
                        ns["mute_until"] = NOW + 99999
                    ds.append({"_": "dialog", "peer": P(k), "top_message": m["id"],
                               "unread_count": unread, "pinned": pinned, "notify_settings": ns,
                               "read_outbox_max_id": 10 ** 6})
                    ms.append(m)
                res = {"_": "messages.dialogs", "dialogs": ds, "messages": ms,
                       "users": USERS, "chats": CHATS}
        elif n == "messages.getDialogFilters":
            res = {"_": "messages.dialogFilters", "filters": [
                {"_": "dialogFilter", "id": 3, "title": {"_": "textWithEntities", "text": "Work", "entities": []},
                 "pinned_peers": [], "include_peers": [], "exclude_peers": [], "groups": 1},
                {"_": "dialogFilter", "id": 4, "title": {"_": "textWithEntities", "text": "Family", "entities": []},
                 "pinned_peers": [], "include_peers": [], "exclude_peers": []}]}
        elif n == "messages.getHistory":
            k = tgclient.input_peer_key(f["peer"], 7)
            ms = list(HISTORY)
            if k == "u11":
                ms = list(PRIVATE)
            ms.reverse()
            res = {"_": "messages.messages", "messages": ms, "users": USERS, "chats": CHATS}
        elif n == "contacts.getContacts":
            res = {"_": "contacts.contacts", "contacts": [
                {"_": "contact", "user_id": i, "mutual": 1} for i in (11, 12, 15)],
                "saved_count": 0, "users": USERS}
        self.net.later(0, lambda: ok(res))


class FakeNet:
    def __init__(self):
        self.q = []

    def later(self, sec, f):
        self.q.append(f)

    def run(self):
        while self.q:
            self.q.pop(0)()

    def cancel_all(self):
        self.q = []


tgclient.mtproto.Session = FakeSession
app = retrotele.App()
app.log = lambda m: sys.stderr.write(str(m) + "\n")
app.net = FakeNet()
app.dir = TMP + os.sep
app.cfg = tgclient.Store(TMP + "/s.txt")
app.store = tgclient.Store(TMP + "/x.txt")
app.cfg.set("api_id", 1); app.cfg.set("api_hash", "a" * 32); app.cfg.set("apid", 1)
app.setup_ap = lambda force=0: 1


def snap(name):
    app.view.draw()
    screens.append({"name": name, "size": [240, 292], "ops": current["ops"]})


app.start(); app.net.run()
snap("1-welcome")
app.store.set("user_id", 7); app.store.set("dc2_key", "00")
app.client.me = 7
app.logged_in(); app.net.run()
app.list_view.cur = 1
snap("2-chats")
app.list_view.tab = 1; app.tab_changed(1); app.list_view.cur = 0
snap("3-unread")
app.list_view.tab = 3; app.tab_changed(3)
snap("4-groups")
tabs = app.tabs()
app.list_view.tab = len(tabs) - 1; app.tab_changed(len(tabs) - 1); app.net.run()
snap("5-contacts")
app.list_view.tab = 0
app.open_chat("h700"); app.net.run()
snap("6-group-chat")
app.view.sel = 2
snap("7-selected")
app.back_to_chats()
app.open_chat("u11"); app.net.run()
app.read_outs["u11"] = 71
app.show_toast(u"Retro Phone Club", u"Jakob: anyone tried RetroTele yet?")
app.net.q = []
snap("8-private")
json.dump(screens, open(os.environ["RT_OUT"] + "/screens.json", "w"))
shutil.rmtree(TMP)
