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
import retrotele, tgclient, tgui
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
         phone="15550001234", status=ONLINE, username="sam_n79",
         photo={"_": "userProfilePhoto", "photo_id": 5, "dc_id": 2}), U(12, "Mia", "Chen", contact=1,
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

PHOTO = {"_": "photo", "id": 99, "access_hash": 1, "file_reference": "r", "date": 0, "dc_id": 2,
         "sizes": [{"_": "photoSize", "type": "m", "w": 320, "h": 240, "size": 9000}]}
VIDEO = {"_": "document", "id": 98, "access_hash": 1, "file_reference": "r", "date": 0, "dc_id": 2,
         "mime_type": "video/mp4", "size": 1, "dc_id": 2,
         "thumbs": [{"_": "photoSize", "type": "m", "w": 320, "h": 180, "size": 5000}],
         "attributes": [{"_": "documentAttributeAnimated"}, {"_": "documentAttributeVideo", "duration": 3, "w": 320, "h": 180}]}
STICKER = {"_": "document", "id": 97, "access_hash": 1, "file_reference": "r", "date": 0, "dc_id": 2,
           "mime_type": "image/webp", "size": 1, "thumbs": [],
           "attributes": [{"_": "documentAttributeSticker", "alt": "\xf0\x9f\x98\x82", "stickerset": {"_": "inputStickerSetEmpty"}}]}
PDF = {"_": "document", "id": 96, "access_hash": 1, "file_reference": "r", "date": 0, "dc_id": 2,
       "mime_type": "application/pdf", "size": 2411724, "thumbs": [],
       "attributes": [{"_": "documentAttributeFilename", "file_name": "N79 user guide.pdf"}]}
ZIP = {"_": "document", "id": 95, "access_hash": 1, "file_reference": "r", "date": 0, "dc_id": 2,
       "mime_type": "application/zip", "size": 880000, "thumbs": [],
       "attributes": [{"_": "documentAttributeFilename", "file_name": "RetroTele-backup.zip"}]}

HISTORY = [
    {"_": "messageService", "id": 4380, "peer_id": P("h700"), "from_id": {"_": "peerUser", "user_id": 14},
     "date": NOW - 90000, "action": {"_": "messageActionChatJoinedByLink"}},
    M("h700", 4390, 13, "Anyone got Opera Mini 4.4 working on the N79? Mine keeps closing "
      "after the splash screen.", 86000),
    M("h700", 4391, 14, "Try the S60v3 signed build, the unsigned one crashes", 85000,
      reply_to={"_": "messageReplyHeader", "reply_to_msg_id": 4390},
      reactions={"_": "messageReactions", "results": [
          {"_": "reactionCount", "reaction": {"_": "reactionEmoji", "emoticon": "\xf0\x9f\x91\x8d"},
           "count": 4, "chosen_order": 0},
          {"_": "reactionCount", "reaction": {"_": "reactionEmoji", "emoticon": "\xf0\x9f\x94\xa5"},
           "count": 2}]}),
    M("h700", 4395, 13, "My N79 setup", 4000, media={"_": "messageMediaPhoto", "photo": PHOTO}),
    M("h700", 4396, 7, "Running RetroTele on my N79 right now \xf0\x9f\x98\x8e\xf0\x9f\x94\xa5", 3000, 1),
    M("h700", 4397, 14, "", 2500, media={"_": "messageMediaDocument", "document": STICKER}),
    M("h700", 4399, 14, "", 2000, media={"_": "messageMediaDocument", "document": VIDEO}),
    M("h700", 4402, 13, "", 1800, media={"_": "messageMediaDocument", "document": PDF}),
    M("h700", 4403, 13, "", 1700, media={"_": "messageMediaDocument", "document": ZIP}),
    M("h700", 4398, 13, "Also, cool cats", 1200,
      fwd_from={"_": "messageFwdHeader", "from_name": "Cat Facts", "date": 0}),
]

PRIVATE = [
    M("u11", 70, 11, "Bro did you install that app?", 9000),
    M("u11", 71, 7, "Yes! Telegram on the N79 :)", 8800, 1),
    M("u11", 72, 7, "It even shows read ticks and replies", 8700, 1),
    M("u11", 76, 11, "", 700, media={"_": "messageMediaDocument", "document": {
        "_": "document", "id": 55, "access_hash": 1, "file_reference": "r", "date": 0,
        "mime_type": "audio/mpeg", "size": 90000, "dc_id": 2, "thumbs": [],
        "attributes": [{"_": "documentAttributeAudio", "duration": 214, "title": "Nokia Tune (Remix)",
                        "performer": "Francisco Tarrega"}]}}),
    M("u11", 77, 11, "Hie \xf0\x9f\x91\x8b\xf0\x9f\x98\x8a", 600),
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
                {"_": "dialogFilter", "id": 4, "title": {"_": "textWithEntities", "text": u"Family \U0001F3E0", "entities": []},
                 "pinned_peers": [], "include_peers": [], "exclude_peers": []}]}
        elif n == "messages.getHistory":
            k = tgclient.input_peer_key(f["peer"], 7)
            ms = list(HISTORY)
            if k == "u11":
                ms = list(PRIVATE)
            ms.reverse()
            res = {"_": "messages.messages", "messages": ms, "users": USERS, "chats": CHATS}
        elif n == "users.getFullUser":
            res = {"_": "users.userFull", "full_user": {"_": "userFull", "id": 11,
                   "about": "Symbian fan \xf0\x9f\x93\xb1"}, "chats": [], "users": USERS}
        elif n == "upload.getFile":
            res = {"_": "upload.file", "type": {"_": "storage.fileJpeg"}, "mtime": 0,
                   "bytes": open(os.environ["RT_PHOTO"], "rb").read()}
        elif n == "contacts.getContacts":
            res = {"_": "contacts.contacts", "contacts": [
                {"_": "contact", "user_id": i, "mutual": 1} for i in (11, 12, 15)],
                "saved_count": 0, "users": USERS}
        self.net.later(0, lambda: ok(res))


class FakeNet:
    def __init__(self):
        self.q = []

    def later(self, sec, f):
        if sec < 1:
            self.q.append(f)   # repeating timers (player, toasts) don't run here

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
app.media = tgui.Media(app, TMP + os.sep)
tgui.set_asset_dir(os.path.join(HERE, "..", "..", "assets") + os.sep)


def snap(name):
    app.view.draw()
    screens.append({"name": name, "size": [240, 292], "ops": current["ops"]})


app.start(); app.net.run()
snap("1-welcome")
app.store.set("user_id", 7); app.store.set("dc2_key", "00")
app.client.me = 7
app.logged_in(); app.net.run()
# archived chats show as the first row of All (the folder-1 request returns none here)
app.archived = [app.dialogs[1], app.dialogs[0]]
app.rows_cache = {}
app.list_view.cur = 1
snap("2-chats")
app.list_view.show_archived()
snap("2b-archived")
app.list_view.close_archived()
def tab_index(spec):
    for _i, _t in enumerate(app.tabs()):
        if _t[1] == spec:
            return _i
    return 0


app.list_view.tab = tab_index("unread"); app.tab_changed(app.list_view.tab); app.list_view.cur = 0
snap("3-unread")
app.list_view.tab = tab_index("groups"); app.tab_changed(app.list_view.tab)
snap("4-groups")
tabs = app.tabs()
app.list_view.tab = len(tabs) - 1; app.tab_changed(len(tabs) - 1); app.net.run()
snap("5-contacts")
app.list_view.tab = 0
app.open_chat("h700"); app.net.run()
app.view.draw(); app.net.run()
snap("6-group-chat")
app.view.sel = 4
snap("7-selected")
for _i, _m in enumerate(app.msgs["h700"]):
    if _m["id"] == 4391:
        app.view.sel = _i
app.view.draw()
snap("7b-reactions")
app.screen = "react"
app.reaction_list = list(app.REACTION_FALLBACK)
rv = tgui.ReactView(app, "h700", app.msgs["h700"][_i])
app.view = rv
rv.show()
snap("7c-react-strip")
rv.i = 4
snap("7d-react-strip-scrolled")
app.back_to_chats()
app.open_chat("u11"); app.net.run()
app.read_outs["u11"] = 71
app.show_toast(u"Retro Phone Club", u"Jakob: anyone tried RetroTele yet?")
app.net.q = []
snap("8-private")
app.play_audio(app.msgs["u11"][-2]); app.net.run()
snap("10-player")
app.close_player()
app.view_profile(); app.net.run(); app.view.draw(); app.net.run()
snap("9-profile")
import filepick
ft = os.path.join(TMP, "ft") + "/"
os.makedirs(ft + "Images"); os.makedirs(ft + "Sounds"); os.makedirs(ft + "A very long folder name for the test")
for nm, n in (("holiday.jpg", 2400000), ("song.mp3", 5100000), ("clip.mp4", 31000000),
              ("backup.zip", 880000), ("notes.txt", 1200), ("RetroTele.sis", 640000), ("data.bin", 90)):
    open(ft + nm, "wb").write("x" * 10)
    if nm.endswith(".jpg"):
        shutil.copy(os.environ["RT_PHOTO"], ft + nm)
    os.utime(ft + nm, (NOW - 86400 * 3, NOW - 86400 * 3))
filepick.SEP = "/"
filepick.is_root = lambda p: p == ft
filepick.drives = lambda: [u"C:", u"E:", u"Z:"]
filepick.drive_path = lambda d: ft
filepick.free_space = lambda: {u"C:": 123 * 1048576, u"E:": 3500 * 1048576}
app.screen = "filepick"
fv = filepick.FilePickView(app, u"", lambda p: None, lambda: None)
app.view = fv; fv.show()
fv.free = filepick.free_space()
snap("11-filepick-drives")
fv.key("down"); fv.key("select")
fv.cur = 4; fv.msg = u""
snap("12-filepick-folder")
shutil.copy(os.environ["RT_PHOTO"], ft + "IMG_0042.jpg")
shutil.copy(os.environ["RT_PHOTO"], ft + "IMG_0043.jpg")
fv.entries = []; fv.load(u"")
fv.sort = 0
fv.path = ft; fv.load(u"")
fv.cur = 0
fv.marks[ft + "IMG_0043.jpg"] = 1; fv.marks[ft + "song.mp3"] = 1
fv.top = 5; fv.cur = 6
app.view = fv
fv.draw(); app.net.run()
snap("13-filepick-thumbs-marks")

# ---- call screens
sys.path.insert(0, os.path.join(HERE, "..", "fake_s60"))
import callaudio_fake
cs = {"key": "u11", "id": 9, "hash": 1, "out": 1, "state": "ringing", "text": "Ringing...",
      "start": 0, "emoji": u"", "kb": "", "conns": []}
app.client.cs = cs
app.screen = "call"
app.view = tgui.CallView(app); app.view.canvas = tgui.appuifw.Canvas(redraw_callback=app.view.on_redraw)
snap("14-call-ringing")
cs["state"] = "connected"; cs["start"] = time.time() - 42; cs["emoji"] = u"1a2b 3c4d"
ca = callaudio_fake.CallAudio(); ca.v277 = 1; ca.running = 1
app.call_audio = ca; app.audio_state = "connected"
app.client.call_version = "2.7.7"
snap("15-call-connected")
class PV:
    cam = 1; state = 3
    def __init__(self): self.on = 1
    def active(self): return self.on
    def status_text(self): return u"Video on - front camera"
    def frame(self): return None
app.call_video = PV()
ca.peer_video = 2
snap("16-call-video-on")
PV.helper_up = lambda self: 1
PV.peer_status = lambda self: u"Peer video: decoder cannot decode this stream (High profile)"
PV.peer_failed = lambda self: 1
PV.peer_frame = lambda self: None
app.call_video.on = 0
snap("16b-call-peer-cannot-decode")
cs["state"] = "incoming"; cs["text"] = "Incoming Telegram call"; app.call_audio = None; app.call_video = None
snap("17-call-incoming")
json.dump(screens, open(os.environ["RT_OUT"] + "/screens.json", "w"))
shutil.rmtree(TMP)
