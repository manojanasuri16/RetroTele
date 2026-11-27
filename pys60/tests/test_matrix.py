# Feature matrix checks (Python 2.7, no network):
#   - every message media type -> label / preview / audio / poll as the chat draws it
#   - the message menu for a personal chat, a group and a read-only channel
#   - what can be opened, played or downloaded, and where the file goes
#   - sending is refused where we may not write (channel posts)
# Run: ../tools/mamba/py27/bin/python2 tests/test_matrix.py
import sys, os, time, tempfile, shutil
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "fake_s60"))
sys.path.insert(0, os.path.join(HERE, ".."))
TMP = tempfile.mkdtemp()
os.chdir(TMP)
shutil.copy(os.path.join(HERE, "..", "schema.txt"), TMP)

import appuifw
notes = []
popups = []
appuifw.note = lambda text, kind="info": notes.append(text)
appuifw.query = lambda *a, **k: None
def popup_menu(items, title=None):
    popups.append(list(items))
    return None                     # nothing chosen: the menu is only inspected
appuifw.popup_menu = popup_menu
appuifw.selection_list = lambda items, search_field=0: None

import tgclient, retrotele, tgui

# ----------------------------------------------------------------- helpers
def msg(**kw):
    d = {"id": 1, "key": "u42", "out": 0, "date": 1700000000, "text": "",
         "media": "", "reply_to": 0, "edited": 0, "fwd": "", "service": 0,
         "from": "Alice B", "from_key": "u42", "photo": None,
         "sticker": None, "audio": None, "poll": None, "buttons": None,
         "file": None, "photo_file": None}
    d.update(kw)
    return d

def thumbs(w=320, h=240):
    return [{"_": "photoSize", "type": "m", "w": w, "h": h, "size": 1000}]

def doc(mime, attrs, size=1000, tid=55, **kw):
    d = {"_": "document", "id": tid, "dc_id": 2, "access_hash": 9,
         "file_reference": "ref", "mime_type": mime, "size": size,
         "attributes": attrs, "thumbs": thumbs()}
    d.update(kw)
    return d

class StubClient(tgclient.Client):
    """Client with no session: only the peer book and the pure helpers are used."""
    def __init__(self):
        pass

class StubApp(retrotele.App):
    def __init__(self):
        pass

def client():
    c = StubClient()
    c.me = 7
    c.typing = {}
    c.peers = {
        "u42": {"kind": "user", "name": "Alice B", "phone": "15550001"},
        "u43": {"kind": "user", "name": "Bob"},
        "c900": {"kind": "group", "name": "Book club"},
        "h5": {"kind": "channel", "name": "News", "can_write": 0},
        "h6": {"kind": "channel", "name": "Mine", "can_write": 1},
        "u7": {"kind": "self", "name": "Saved Messages"},
    }
    c.peercache = c.peers
    c.log = lambda m: None
    c.server_time = lambda: 1700000000
    c.main_dc = 4
    return c

def app_for(key, write=1):
    a = StubApp()
    a.chat_key = key
    a.client = client()
    a.client.peers[key]["can_write"] = write
    a.screen = "chat"
    a.msg_sent = []
    a.media = type("M", (), {"folder": TMP + os.sep})()
    a.open_player = lambda info, path: a.msg_sent.append(("player", path))
    a.status = lambda text: None
    a.done_wait = lambda: None
    a.log = lambda m: None
    a.load_failed = lambda e: a.msg_sent.append(("failed", e))
    return a

def menu_for(m, key="u42", write=1):
    a = app_for(key, write)
    del popups[:]
    a.message_menu(m)
    assert popups, "message_menu showed nothing"
    return popups[-1]

def norm(cl, m):
    return cl.norm_message(m)

# ================================================================ 1. media
cl = client()
PH = {"_": "photo", "id": 11, "dc_id": 2, "access_hash": 1, "file_reference": "r",
      "sizes": [{"_": "photoStrippedSize", "bytes": "x"},
                {"_": "photoSize", "type": "m", "w": 320, "h": 240, "size": 900}]}

def m_photo():
    return norm(cl, {"_": "message", "id": 1, "peer_id": {"_": "peerUser", "user_id": 42},
                     "date": 1, "message": "pic", "out": 0,
                     "media": {"_": "messageMediaPhoto", "photo": PH}})
r = m_photo()
assert r["photo"] and r["photo"]["w"] == 320 and r["photo"]["id"] == "p11m", r["photo"]
assert r["photo"]["stripped"] == "x" and r["photo"]["badge"] == "", r["photo"]
assert r["audio"] is None and r["media"] == "Photo", r

# only the ~320 px preview size is used, even when the photo has a bigger one
big = {"_": "photo", "id": 12, "dc_id": 2, "access_hash": 1, "file_reference": "r",
       "sizes": [{"_": "photoSize", "type": "m", "w": 320, "h": 240, "size": 900},
                 {"_": "photoSize", "type": "x", "w": 800, "h": 600, "size": 4000}]}
inf = tgclient.photo_preview(big)
assert inf["w"] == 320 and inf["loc"]["thumb_size"] == "m", inf      # KNOWN LIMIT D9
# photos and audio share one folder; the name is <id><size>.jpg / <id>.<ext>
m = tgui.Media(app_for("u42"), TMP + os.sep)
assert m.path({"id": "p11m"}) == TMP + os.sep + "p11m.jpg", m.path({"id": "p11m"})

# video file: label + thumbnail with the "Video" badge, and nothing to play
def m_video(**kw):
    a = [{"_": "documentAttributeVideo", "duration": 74, "w": 320, "h": 240}]
    return norm(cl, {"_": "message", "id": 2, "peer_id": {"_": "peerChat", "chat_id": 900},
                     "date": 1, "message": "", "out": 0,
                     "media": {"_": "messageMediaDocument", "document": doc("video/mp4", a, **kw)}})
r = m_video()
assert r["media"] == "Video 1:14", r["media"]
assert r["photo"] and r["photo"]["badge"] == "Video 1:14", r["photo"]
assert r["audio"] is None, "a video must not be treated as audio"
assert r["sticker"] is None, r

# round video message
r = norm(cl, {"_": "message", "id": 3, "peer_id": {"_": "peerUser", "user_id": 42}, "date": 1,
              "message": "", "out": 0,
              "media": {"_": "messageMediaDocument",
                        "document": doc("video/mp4", [{"_": "documentAttributeVideo",
                                                       "duration": 5, "round_message": 1}])}})
assert r["media"] == "Video message 0:05", r["media"]

# GIF: badge kept (not a still image)
r = norm(cl, {"_": "message", "id": 4, "peer_id": {"_": "peerChat", "chat_id": 900}, "date": 1,
              "message": "", "out": 0,
              "media": {"_": "messageMediaDocument",
                        "document": doc("video/mp4", [{"_": "documentAttributeAnimated"}])}})
assert r["media"] == "GIF" and r["photo"]["badge"] == "GIF", (r["media"], r["photo"])

# sticker: drawn from its emoji, no picture download
r = norm(cl, {"_": "message", "id": 5, "peer_id": {"_": "peerUser", "user_id": 42}, "date": 1,
              "message": "", "out": 0,
              "media": {"_": "messageMediaDocument",
                        "document": doc("application/x-tgsticker",
                                        [{"_": "documentAttributeSticker", "alt": unichr(0x1F600)}])}})
assert r["sticker"] == unichr(0x1F600) and r["photo"] is None, r
assert r["media"] == "Sticker " + unichr(0x1F600), r["media"]

# a webp image document must not become a preview (the phone can't decode webp)
r = norm(cl, {"_": "message", "id": 6, "peer_id": {"_": "peerUser", "user_id": 42}, "date": 1,
              "message": "", "out": 0,
              "media": {"_": "messageMediaDocument",
                        "document": doc("image/webp", [{"_": "documentAttributeFilename",
                                                        "file_name": "x.webp"}])}})
assert r["photo"] is None and r["media"] == "x.webp", r

# voice message: label, ogg/opus, refused by play (the N79 has no Opus decoder)
voice = norm(cl, {"_": "message", "id": 7, "peer_id": {"_": "peerUser", "user_id": 42}, "date": 1,
                  "message": "", "out": 0,
                  "media": {"_": "messageMediaDocument",
                            "document": doc("audio/ogg", [
                                {"_": "documentAttributeAudio", "voice": 1, "duration": 4}])}})
assert voice["media"] == "Voice message 0:04", voice["media"]
assert voice["audio"]["voice"] == 1 and voice["audio"]["ext"] == "ogg", voice["audio"]
del notes[:]
app_for("u42").play_audio(voice)
assert notes and "can't play" in notes[-1], notes

# music: label "Music Artist - Title", plays from the media folder
music = norm(cl, {"_": "message", "id": 8, "peer_id": {"_": "peerUser", "user_id": 42}, "date": 1,
                  "message": "", "out": 0,
                  "media": {"_": "messageMediaDocument",
                            "document": doc("audio/mpeg", [
                                {"_": "documentAttributeAudio", "duration": 185,
                                 "title": "Nokia Tune", "performer": "Nokia"}],
                                tid=77, size=300000)}})
assert music["media"] == "Music Nokia - Nokia Tune", music["media"]
assert music["audio"]["ext"] == "mp3" and music["audio"]["id"] == "f77", music["audio"]
# already downloaded: plays from <folder>/<id>.<ext> without asking for a download
open(TMP + os.sep + "f77.mp3", "wb").write("x" * 300000)
a = app_for("u42")
del a.msg_sent[:]
a.play_audio(music)
assert a.msg_sent == [("player", TMP + os.sep + "f77.mp3")], a.msg_sent

# a plain PDF: label only, no preview, no player, no download path at all
pdf = norm(cl, {"_": "message", "id": 9, "peer_id": {"_": "peerChat", "chat_id": 900}, "date": 1,
                "message": "", "out": 0,
                "media": {"_": "messageMediaDocument",
                          "document": doc("application/pdf",
                                          [{"_": "documentAttributeFilename",
                                            "file_name": "report.pdf"}],
                                          size=65536, thumbs=[])}})
assert pdf["media"] == "report.pdf" and pdf["photo"] is None and pdf["audio"] is None, pdf
# ... the menu opens it with the phone's own reader and can save it
items = menu_for(pdf, key="c900")
assert u"Open file" in items and u"Save file" in items, items
assert u"View picture" not in items and u"Play video" not in items, items
assert u"Read full message" in items, items

# location / venue / contact / poll / unsupported / webpage
r = norm(cl, {"_": "message", "id": 10, "peer_id": {"_": "peerUser", "user_id": 42}, "date": 1,
              "message": "", "media": {"_": "messageMediaGeo",
                                       "geo": {"_": "geoPoint", "lat": 12.9716, "long": 77.5946}}})
assert r["media"].startswith(u"Location 12.97160, 77.59460"), r["media"]
r = norm(cl, {"_": "message", "id": 11, "peer_id": {"_": "peerUser", "user_id": 42}, "date": 1,
              "message": "", "media": {"_": "messageMediaContact", "first_name": "Alice",
                                       "phone_number": "15550001"}})
assert r["media"] == "Contact: Alice 15550001", r["media"]
poll = {"_": "poll", "id": 3, "question": "Lunch?", "closed": 0, "answers": [
    {"text": "Yes", "option": "a"}, {"text": "No", "option": "b"}]}
r = norm(cl, {"_": "message", "id": 12, "peer_id": {"_": "peerChat", "chat_id": 900}, "date": 1,
              "message": "", "media": {"_": "messageMediaPoll", "poll": poll,
                                       "results": {"total_voters": 4, "results": [
                                           {"option": "a", "voters": 3, "chosen": 1}]}}})
assert r["poll"]["question"] == "Lunch?" and r["poll"]["total"] == 4, r["poll"]
assert r["poll"]["chosen"] == ["a"] and r["media"] == "Poll: Lunch?", r
r = norm(cl, {"_": "message", "id": 13, "peer_id": {"_": "peerUser", "user_id": 42}, "date": 1,
              "message": "", "media": {"_": "messageMediaUnsupported"}})
assert r["media"] == "Unsupported message", r["media"]
r = norm(cl, {"_": "message", "id": 14, "peer_id": {"_": "peerUser", "user_id": 42}, "date": 1,
              "message": "see this", "media": {"_": "messageMediaWebPage",
                                                "webpage": {"url": "http://x"}}})
assert r["media"] == "" and r["text"] == "see this", r

# every audio mime maps to the extension the phone needs
for mime, ext in tgclient.AUDIO_EXT.items():
    inf = tgclient.audio_info(doc(mime, [{"_": "documentAttributeAudio", "title": "t"}]))
    assert inf["ext"] == ext, (mime, inf["ext"])
inf = tgclient.audio_info(doc("audio/x-nope", [{"_" : "documentAttributeFilename",
                                               "file_name": "song.FLAC"}]))
assert inf["ext"] == "flac", inf["ext"]

# full-size photo and whole-file download locations (what "Save" uses)
assert tgclient.photo_full(big)["w"] == 800 and tgclient.photo_full(big)["loc"]["thumb_size"] == "x"
assert tgclient.photo_full({"id": 1}) is None
pdf_doc = doc("application/pdf", [{"_": "documentAttributeFilename",
                                   "file_name": "report.pdf"}], size=65536, thumbs=[])
f = tgclient.doc_file(pdf_doc)
assert f["ext"] == "pdf" and f["name"] == "report.pdf" and f["loc"]["thumb_size"] == "", f
assert tgclient.doc_file(doc("video/mp4", [{"_": "documentAttributeFilename",
                                          "file_name": "Holiday.MP4"}]))["ext"] == "mp4"
assert tgclient.doc_file(doc("application/octet-stream", []))["ext"] == "bin"
# audio_playable decides the Play menu item
assert tgclient.audio_playable({"ext": "mp3", "voice": 0}) == 1
assert tgclient.audio_playable({"ext": "ogg", "voice": 1}) == 0
assert tgclient.audio_playable({"ext": "ogg", "voice": 0}) == 0
assert tgclient.audio_playable(None) == 0

# =========================================================== 2. chat kinds
# personal chat, incoming photo
items = menu_for(msg(photo={"id": "p11m"}))
for want in (u"Reply", u"Forward", u"View picture", u"Read full message", u"Delete"):
    assert want in items, (want, items)
assert u"Edit" not in items, items                      # not my message

# personal chat, my own text: editable, deletable
items = menu_for(msg(out=1, text="hi", from_key="u7"))
assert u"Edit" in items and u"Delete" in items, items

# own media message cannot be edited (Telegram text only), but can be deleted
items = menu_for(msg(out=1, media="Photo", photo={"id": "p11m"}))
assert u"Edit" not in items and u"Delete" in items, items

# group chat: reply allowed, sender action offered for someone else's message
items = menu_for(msg(key="c900", from_key="u43", photo={"id": "p11m"}), key="c900")
assert u"Reply" in items and u"Message Bob" in [i for i in items if i.startswith(u"Message")], items

# read-only channel: read/forward only, no reply/edit/vote, and no sending
items = menu_for(msg(key="h5", photo={"id": "p11m"}), key="h5", write=0)
assert u"Reply" not in items and u"Edit" not in items, items
assert u"Forward" in items and u"View picture" in items, items
# KNOWN DEFECT (see docs/FEATURE-MATRIX.md, M3): Delete is offered on somebody
# else's channel post; the server refuses it (channels allow deleting your own
# messages only). Recorded here so the behaviour is visible if it changes.
assert u"Delete" in items, items

# channel where we are an admin: reply and edit work again
items = menu_for(msg(key="h6", out=1, text="post", from_key="u7"), key="h6", write=1)
assert u"Reply" in items and u"Edit" in items, items

# service messages carry no reply/forward
items = menu_for(msg(service=1, text="Alice joined", from_key="u43"))
assert u"Reply" not in items and u"Forward" not in items, items

# polls: results always, voting only while open and writable
open_poll = {"id": 3, "question": "Lunch?", "closed": 0, "answers": [], "total": 0, "chosen": []}
closed_poll = dict(open_poll, closed=1)
items = menu_for(msg(poll=open_poll, key="c900"), key="c900")
assert u"Poll results" in items and u"Vote in poll" in items, items
items = menu_for(msg(poll=closed_poll, key="c900"), key="c900")
assert u"Poll results" in items and u"Vote in poll" not in items, items
items = menu_for(msg(poll=open_poll, key="h5"), key="h5", write=0)
assert u"Vote in poll" not in items, items

# inline keyboard from a bot
items = menu_for(msg(buttons=[{"text": "Go", "kind": "url", "url": "http://x"}]))
assert u"Bot buttons" in items, items

# voice message: played by the phone's player and savable
items = menu_for(msg(audio={"voice": 1, "ext": "ogg", "id": "f1", "size": 1, "title": "v"},
                     file={"id": "f1", "ext": "ogg", "size": 1, "name": "voice.ogg"}))
assert items[0] == u"Play voice message", items
assert u"Save voice message" in items, items

# music: plays here, and saves to the media folder like the pictures
items = menu_for(msg(audio={"voice": 0, "ext": "mp3", "id": "f8", "size": 1, "title": "m"},
                     file={"id": "f8", "ext": "mp3", "size": 1, "name": "m.mp3"}))
assert items[0] == u"Play audio" and u"Save audio" in items, items
assert u"Save file" not in items, items

# video: play it in the phone's player, save it as a video (never "picture")
items = menu_for(msg(media="Video 0:04", file={"id": "f2", "ext": "mp4", "size": 1,
                                               "mime": "video/mp4", "name": "clip.mp4"}))
assert items[0] == u"Play video" and u"Save video" in items, items
assert u"View picture" not in items and u"Save picture (original)" not in items, items
assert u"Save file" in menu_for(pdf, key="c900"), menu_for(pdf, key="c900")

# photo: view the preview, and save the original size
items = menu_for(msg(photo={"id": "p11m"}, photo_file={"id": "p11x", "ext": "jpg"}))
assert u"View picture" in items and u"Save picture (original)" in items, items

# ============================================== 3. writing gates (per chat)
def refuse(fn, a):
    ok = False
    try:
        fn(a)
    except Exception:
        raise
    return a.screen

a = app_for("h5", write=0)
a.set_screen = lambda *x: None
a.compose(); assert a.screen == "chat" and not hasattr(a, "editor"), "compose in a channel"
a.attach_file(); assert a.screen == "chat" and not hasattr(a, "picker"), "attach in a channel"
a = app_for("h6", write=1)
a.set_screen = lambda *x: None
a.editor = None
try:
    a.compose()
except Exception:
    pass
# compose on a writable channel proceeds to the editor screen
assert a.screen == "compose", a.screen

# can_write defaults to True when the peer carries no flag
c = client()
assert c.can_write("c900") == 1
assert c.can_write("h5") == 0

# can_write is what every sender checks
assert tgclient.Client.can_write(client(), "h5") == 0



# ==================================== 3b. saving a file / the original photo
def with_download(a, data="DATA"):
    def download(info, path, ok, err, progress=None):
        f = open(path + ".part", "wb")
        f.write(data)
        f.close()
        os.rename(path + ".part", path)
        if progress:
            progress(len(data))
        ok(path)
    a.client.download = download
    return a

video_m = msg(media="Video 0:04", file={"id": "f2", "ext": "mp4", "size": 4,
                                         "name": "clip.mp4"})
a = with_download(app_for("u42"))
del notes[:]
a.save_file(video_m)
assert os.path.exists(TMP + os.sep + "Videos" + os.sep + "clip.mp4"), os.listdir(TMP)
assert notes and notes[-1].find(u"Saved") >= 0 and notes[-1].find(u"clip.mp4") >= 0, notes
del notes[:]
a.save_file(video_m)                                   # already saved: no second download
assert notes and notes[-1].find(u"Already saved") >= 0, notes

pdf_m = msg(key="c900", media="report.pdf",
            file={"id": "f9", "ext": "pdf", "size": 4, "name": "report.pdf"})
a = with_download(app_for("c900"))
del notes[:]
a.save_file(pdf_m)                                     # also in a group, no write needed
assert os.path.exists(TMP + os.sep + "Files" + os.sep + "report.pdf"), os.listdir(TMP)
assert notes[-1].find(u"report.pdf") >= 0, notes

voice_m = msg(audio={"voice": 1, "ext": "ogg", "id": "f1", "size": 4, "title": "v"},
              file={"id": "f1", "ext": "ogg", "size": 4, "name": "voice.ogg"})
a = with_download(app_for("u42"))
del notes[:]
a.save_file(voice_m)                                   # the .ogg can at least be saved
assert os.path.exists(TMP + os.sep + "Sounds" + os.sep + "voice.ogg"), os.listdir(TMP)

# the original picture carries the extension the save path needs (it used to
# crash with KeyError, so "Save picture (original)" did nothing)
pf = tgclient.photo_full({"_": "photo", "id": 5, "access_hash": 6, "file_reference": "r",
                          "dc_id": 2, "sizes": [
                              {"_": "photoSize", "type": "m", "w": 320, "h": 240},
                              {"_": "photoSize", "type": "y", "w": 1280, "h": 960,
                               "size": 123456}]})
assert pf["ext"] == "jpg" and pf["loc"]["thumb_size"] == "y", pf
assert pf["size"] == 123456 and pf["w"] == 1280 and pf["h"] == 960, pf

photo_m = msg(photo={"id": "p11m"}, photo_file={"id": "p11x", "ext": "jpg", "size": 4})
a = with_download(app_for("u42"))
del notes[:]
a.save_photo(photo_m)
assert os.path.exists(TMP + os.sep + "Pictures" + os.sep + "photo_p11x.jpg"), os.listdir(TMP)
del notes[:]
a.save_photo(msg(photo={"id": "p11m"}, photo_file=pf))   # the real photo_full shape
# Telegram's generic "photo.jpg" is numbered by the file id
assert os.path.exists(TMP + os.sep + "Pictures" + os.sep + "photo_p5y.jpg"), os.listdir(TMP)
del notes[:]
a.save_photo(msg(photo={"id": "p11m"}))                # nothing to save
assert notes and notes[-1].find(u"no picture") >= 0, notes


# ============================== 3c. typing, reactions, copy, folder badges
# reactions arrive as messageReactions and become chips
mr = {"_": "messageReactions", "results": [
    {"_": "reactionCount", "reaction": {"_": "reactionEmoji", "emoticon": "\xf0\x9f\x91\x8d"},
     "count": 3, "chosen_order": 0},
    {"_": "reactionCount", "reaction": {"_": "reactionCustomEmoji", "document_id": 5}, "count": 9},
    {"_": "reactionCount", "reaction": {"_": "reactionEmoji", "emoticon": "\xe2\x9d\xa4"},
     "count": 1}]}
r = norm(cl, {"_": "message", "id": 20, "peer_id": {"_": "peerChat", "chat_id": 900},
              "date": 1, "message": "lol", "reactions": mr})
assert len(r["reactions"]) == 2, r["reactions"]           # custom emoji have no picture
assert r["reactions"][0]["count"] == 3 and r["reactions"][0]["chosen"] is True, r["reactions"]
assert r["reactions"][1]["chosen"] is False, r["reactions"]

c = client()
sent = []
c.call = lambda f, ok, err=None: sent.append(f)
c.set_typing("u42")
c.set_typing("u42", 1)
assert sent[0]["_"] == "messages.setTyping" and sent[0]["action"]["_"] == "sendMessageTypingAction", sent
assert sent[1]["action"]["_"] == "sendMessageCancelAction", sent

# typing state: shown per chat, "Alice is typing..." in a group, expires
class UI(object):
    def __init__(self): self.changed = []
    def typing_changed(self, key): self.changed.append(key)
c.ui = UI()
c.someone_typing("u42", None, {"_": "sendMessageTypingAction"})
assert c.typing_text("u42") == "typing..."
assert c.status_text("u42") == "typing..."            # the chat header shows it too
c.someone_typing("c900", "u43", {"_": "sendMessageTypingAction"})
assert c.typing_text("c900") == "Bob is typing...", c.typing_text("c900")
assert c.ui.changed == ["u42", "c900"], c.ui.changed
c.someone_typing("c900", "u43", {"_": "sendMessageRecordAudioAction"})
assert c.typing_text("c900") == "Bob is recording audio...", c.typing_text("c900")
c.someone_typing("c900", None, {"_": "sendMessageUploadDocumentAction"})
assert c.typing_text("c900") == "sending a file...", c.typing_text("c900")
c.someone_typing("u42", None, {"_": "sendMessageCancelAction"})
assert c.typing_text("u42") is None
c.someone_typing("u42", None, {"_": "sendMessageTypingAction"})
c.typing["u42"] = (0, "")                      # an expired entry disappears
assert c.typing_text("u42") is None and not c.typing.has_key("u42")
assert c.typing_text("c1") is None

# the chat list shows typing instead of the last message
a = app_for("u42")
a.dialogs = []
a.tz = 0
a.now = lambda: 1700000000
a.client.typing["u42"] = (time.time() + 6, "")
row = a.decorate({"key": "u42", "date": 1, "preview": "old text"})
assert row["preview"] == u"typing...", row["preview"]

# copy: with a clipboard it copies, without one it explains
copied = []
appuifw.app.set_clipboard = lambda t: copied.append(t)
a = app_for("u42")
a.show_toast = lambda x, y: None
a.copy_text(msg(text="hello"))
assert copied == ["hello"], copied
del appuifw.app.set_clipboard            # back to the dummy (accepts anything)
a = app_for("u42")
a.client.call = lambda f, ok, err=None: None

# react: the strip sends the picked emoji as UTF-8 bytes, and an empty one removes it
sent = []
a.client.call = lambda f, ok, err=None: sent.append(f)
a.chat_key = "u42"
a.send_reaction(msg(id=21), a.REACTION_FALLBACK[0])
assert sent and sent[-1]["_"] == "messages.sendReaction", sent
assert sent[-1]["msg_id"] == 21, sent
assert sent[-1]["reaction"][0]["emoticon"] == "\xf0\x9f\x91\x8d", sent
a.send_reaction(msg(id=21), "")
assert sent[-1]["reaction"] == [], sent[-1]     # an empty vector removes ours

# the reaction strip scrolls through its emoji and the last slot removes ours
class ReactionApp(object):
    reaction_list = ["\xf0\x9f\x91\x8d", "\xe2\x9d\xa4"]
    def __init__(self): self.picked = []
    def send_reaction(self, m, e): self.picked.append(e)
ra = ReactionApp()
rv = tgui.ReactView(ra, "u42", {"id": 21, "reactions": [
    {"emoji": "\xe2\x9d\xa4", "count": 3, "chosen": 0}]})
rv.draw = lambda: None
rv.key("right")
assert rv.i == 1 and rv.count(ReactionApp.reaction_list[1]) == 3, rv.i
rv.key("select")
assert ra.picked == ["\xe2\x9d\xa4"], ra.picked
rv.key("right")
rv.key("select")
assert ra.picked[-1] == "", ra.picked

# the emoji sprite index must actually build: a NameError in it turned every
# emoji on screen into an empty box
tgui.set_asset_dir(os.path.join(HERE, "..", "assets") + os.sep)
assert tgui.emoji_k("\xf0\x9f\x91\x8d") >= 0, tgui.emoji_k("\xf0\x9f\x91\x8d")
assert max(tgui.prep("\xf0\x9f\x91\x8d")) >= tgui.SENT, tgui.prep("\xf0\x9f\x91\x8d")

# the clock follows the phone: localtime vs gmtime gives the zone offset even
# when time.timezone is not set (Symbian) and time.time() is UTC
class FakeClock(object):
    timezone = 0
    daylight = 0
    def __init__(self, off): self.off = off
    def time(self): return 1700000000.0
    def gmtime(self, t=None):
        import calendar
        return time.gmtime(t if t is not None else self.time())
    def localtime(self, t=None):
        return time.gmtime((t if t is not None else self.time()) + self.off)
real_time = retrotele.time
retrotele.time = FakeClock(19800)
assert retrotele.local_offset(1700000000) == 19800, retrotele.local_offset(1700000000)
retrotele.time = FakeClock(-18000)
assert retrotele.local_offset(1700000000) == -18000
retrotele.time = real_time
stub = StubApp()
stub.tz = 19800
stub.client = client()
assert stub.hhmm(1) == u"05:30", stub.hhmm(1)     # 00:00 UTC is 05:30 in India

# folder badges: unread chats per tab, all in one pass over the chats
a = StubApp()
a.client = client()
a.tabs = lambda: [(u"All", "all"), (u"Unread", "unread"), (u"Personal", "personal"),
                  (u"Groups", "groups"), (u"Contacts", "contacts")]
a.dialogs = [{"key": "u42", "unread": 2}, {"key": "c900", "unread": 0},
             {"key": "u43", "unread": 0, "mark": 1}]
a.archived = [{"key": "h5", "unread": 1}]
assert a.tab_badges() == [2, 2, 2, 0, 0], a.tab_badges()
a.dialogs = []
a.archived = None
assert a.tab_badges() == [0, 0, 0, 0, 0], a.tab_badges()

# Archived is not a tab: it is the first row of All chats, with its own icon
app = app_for("u42")
app.filters = []
assert app.tabs() == [(u"All", "all"), (u"Unread", "unread"), (u"Personal", "personal"),
                      (u"Groups", "groups"), (u"Channels", "channels"),
                      (u"Contacts", "contacts")], app.tabs()
app.archived = None
assert app.archived_row() is None
app.archived = [{"key": "h5", "unread": 2}, {"key": "c900", "unread": 0}]
ar = app.archived_row()
assert ar["archived_row"] and ar["unread"] == 2 and ar["preview"] == u"2 chats", ar
app.archived = [{"key": "h5"}]
assert app.archived_row()["preview"] == u"1 chat"

# ===================================== 4. what the chat screen draws per kind
import graphics

class StubAvatars(object):
    def draw(self, g, key, name, photo, x, y, s, special=None):
        pass

class StubViewApp(object):
    busy = None
    tz = 0
    toast_text = None
    avatars = StubAvatars()

    def __init__(self, key, rows):
        self.chat_key = key
        self.client = client()
        self.client.peers[key]["can_write"] = 1 if key != "h5" else 0
        self.msgs = {key: rows}
        self.drafts = {}

    def chat_messages(self, key): return self.msgs.get(key, [])
    def chat_empty_text(self): return u"No messages here yet"
    def draft_preview(self, key): return self.drafts.get(key, u"")
    def read_out(self, key): return 0
    def quote_for(self, key, mid): return (u"You", u"earlier")
    def hhmm(self, ts): return u"12:34"

def render(key, rows):
    a = StubViewApp(key, rows)
    v = tgui.ChatView(a, key)
    del graphics.drawn[:]
    v.paint(graphics.Image.new((240, 292)), 240, 292)
    return [t[2] for t in graphics.drawn]

# group: the sender of every incoming message is named in the bubble
rows = [msg(key="c900", id=1, from_key="u43", **{"from": "Bob"}), msg(key="c900", id=2, from_key="u42")]
rows[1]["from"] = "Alice B"
rows[0]["text"] = "hello group"
texts = render("c900", rows)
assert u"Book club" in texts, texts
assert u"Bob" in texts and u"hello group" in texts, texts
assert u"Alice B" in texts, texts

# personal chat: no sender name inside the bubble, only the header title
rows = [msg(key="u42", id=1, text="hey there")]
texts = render("u42", rows)
assert texts.count(u"Alice B") == 1, texts          # header only
assert u"hey there" in texts, texts

# reactions are drawn as chips and make the bubble taller
react_row = msg(key="u42", id=3, text="nice",
                reactions=[{"emoji": "\xf0\x9f\x91\x8d", "count": 3, "chosen": True}])
texts = render("u42", [react_row])
assert u"3" in u" ".join(texts), texts
a = StubViewApp("u42", [react_row])
v = tgui.ChatView(a, "u42")
g = graphics.Image.new((240, 292))
h_react = v.layout(g, react_row, 200, 0)["h"]
plain = dict(react_row)
plain["reactions"] = []
h_plain = v.layout(g, plain, 200, 0)["h"]
assert h_react == h_plain + 20, (h_react, h_plain)

# a document (PDF, zip...) is a card of its own: type badge, name and size
pdf_doc = {"id": "f9", "ext": "pdf", "size": 2411724, "name": "N79 user guide.pdf",
           "mime": "application/pdf"}
rows = [msg(key="u42", id=4, media="N79 user guide.pdf", file=pdf_doc)]
texts = render("u42", rows)
assert u"N79 user guide.pdf" in texts, texts
assert u"PDF \xb7 2.3 MB" in texts, texts          # type and size, not a plain line
a = StubViewApp("u42", rows)
v = tgui.ChatView(a, "u42")
lay = v.layout(graphics.Image.new((240, 292)), rows[0], 200, 0)
assert lay["body"][0][0] == "file" and lay["h"] > 60, lay
zip_doc = {"id": "f10", "ext": "zip", "size": 880000, "name": "photos.zip"}
texts = render("u42", [msg(key="u42", id=5, file=zip_doc)])
assert u"photos.zip" in texts and u"ZIP \xb7 859 KB" in texts, texts
assert tgui.file_badge({"ext": "apk"})[0] == u"APK", tgui.file_badge({"ext": "apk"})
assert tgui.file_badge({"ext": "xyz"})[0] == u"XYZ", tgui.file_badge({"ext": "xyz"})

# read-only channel: input bar says posting is not possible
rows = [msg(key="h5", id=1, text="news post")]
texts = render("h5", rows)
assert u"Only admins can post here" in texts, texts
assert u"news post" in texts, texts

# channel where we are an admin: normal "Message" input bar
a = StubViewApp("h6", [msg(key="h6", id=1, text="my post")])
a.client.peers["h6"]["can_write"] = 1
v = tgui.ChatView(a, "h6")
del graphics.drawn[:]
v.paint(graphics.Image.new((240, 292)), 240, 292)
texts = [t[2] for t in graphics.drawn]
assert u"Message" in texts and u"Only admins can post here" not in texts, texts


print "matrix OK: media labels, menus, chat kinds, download paths, saving files, per-kind rendering"
shutil.rmtree(TMP)
