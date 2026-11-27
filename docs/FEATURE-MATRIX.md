# RetroTele feature matrix — what was tested, how, and what fails

Written 2026-11-27 against the working tree (RetroTele 0.17.1). Two kinds of evidence are used:

1. **Automated** — `pys60/tests/test_matrix.py` (new) drives the real `tgclient`/`tgui`/`retrotele`
   code with fake PyS60 UI and a fake network, and asserts every media type, message menu, chat kind
   and the download paths. It runs in the normal suite:
   `sh pys60/tests/run.sh` → `matrix OK: media labels, menus, chat kinds, download paths, saving files, per-kind rendering`.
The typing / reactions / copy / tab-badge checks are part of the same file (section 3c and the render
block).
2. **Code reading** — for paths that need a live server or the phone's codecs (sending, sockets,
   playback), the exact function is named so it can be re-checked.

Anything that can only be proven on the N79 itself is listed in §7. Nothing here was run on the
Nokia — there is no link to it from this machine.

---

## 1. Result of this pass

```
Python 2.2 check: OK (12 modules)      integer check: OK
crypto OK      tl OK      flow OK      matrix OK
videomirror tests OK      test_callvideo OK
sh pys60/tests/run.sh  ->  exit 0
```

The suite covers login (code + SRP two-step), chat list and tabs, opening a chat, playing an audio
message from the cache, compose/reply/edit/delete, live updates and read receipts, in-app banner,
upload of photos/documents/audio with retries and cancel, the 2.4.4 and 2.7.7 call flows, the
call-test screen, and now the media matrix below.

---

## 2. Media matrix (what happens to each kind of message)

"Download" = does a file land on the memory card, and where.

| Media | Shown in the chat | Opened / played | Download | Notes |
|---|---|---|---|---|
| Photo | 320 px preview; blurry stripped JPEG first, then the ~320 px version | ✅ full-screen viewer (`view_photo`) | ✅ preview to `<data>\media\<pID><size>.jpg`, and **`Save picture (original)`** fetches the largest size (up to 1280 px) | D9 fixed for saving; the viewer still shows the 320 px preview (deliberate: memory) |
| Video file | thumbnail + `Video 1:14` badge | ✅ **`Play video`** → downloads, then the phone's own video player (`open_media` → `Content_handler`) | ✅ **`Save video`** → `<data>\media\<fID>.mp4` | no in-app video canvas: S60 has no H.264 render API for Python, so playback hands over to the phone player |
| Round video message | thumbnail + `Video message 0:05` | ✅ `Play video` (phone player) | ✅ `Save video` | same naming/flow as video |
| GIF (animation) | thumbnail + `GIF` badge | ✅ `Play video` (phone player) | ✅ `Save file` (saves the .mp4) | |
| Sticker (static) | big emoji from the sprite sheet | ❌ | ❌ | animated/TGS stickers only show their emoji |
| Voice message | `Voice message 0:04` + play triangle | ✅ **`Play voice message`** hands the .ogg to the phone's player; the N79 has no Opus decoder, so that player may refuse it | ✅ **`Save voice message`** → `<data>\media\<fID>.ogg` | D3 fixed differently: no silent Play, the option is the phone player and an honest note when nothing opens it |
| Music (mp3/m4a/aac/wav/amr/flac) | play triangle, title, `performer  3:05` | ✅ `PlayerView` with play/pause, position bar, 4/6 skip 10 s | ✅ **`Save audio`** or `Play audio` → `<data>\media\<fID>.<ext>` | cached file is reused next time; download resumes from `.part` |
| PDF / zip / any document | file name (or `File`) | ✅ **`Open file`** → the phone's PDF reader / zip manager (`Content_handler.open_standalone`) | ✅ **`Save file`** → `<data>\media\<fID>.<ext>` | D2 fixed for every document; opening needs an app registered for the type |
| File with a JPEG thumbnail | thumbnail + file name badge | viewer shows the *thumbnail* only, at full-screen | ✅ the whole file can now be saved | thumb still used for the bubble |
| Location | `Location 12.97160, 77.59460` | ❌ (text only) | — | |
| Venue | `Venue …` | ❌ | — | |
| Contact | `Contact: Name +phone` | ❌ | — | |
| Poll | `Poll: <question>` + results in the bubble | ✅ results screen; ✅ voting while open and writable | — | live `updateMessagePoll` refresh works |
| Bot inline keyboard | message + `Bot buttons` | ✅ callback and URL buttons | — | URL buttons show the link to copy |
| Unsupported / webpage | `Unsupported message`; web page previews are ignored (the text shows) | — | — | |
| Service message | `X joined`, `pinned a message`, … | — | — | |
| Story / paid media / giveaway | label only | ❌ | — | out of scope |

### Where files actually go

`find_dir("RetroTele")` (`retrotele.py:117`) picks the first writable of
`E:\RetroTele\`, `C:\Data\RetroTele\`, `C:\RetroTele\`, then `media\` under it
(`retrotele.py:400`). Everything RetroTele saves goes in that **one** folder:

- photos: `media\<photo-id><size>.jpg` (also used by the viewer, so the chat preview and the full
  picture are separate files),
- audio: `media\<doc-id>.<ext>` (ext from the MIME type, or the file name's extension),
- thumbs/derived: `media\strip.jpg`,
- partial downloads: `<name>.part`, resumed in 32 KB pieces (`Client.download`, `tgclient.py:452`),
- video, document, GIF and voice files: `media\<fID>.<ext>` via **Options > Save file** (or `Save
  voice message`), and the original-size photo as `media\<pID><size>.jpg` via **Options > Save
  picture (original)**,
- no gallery hand-off, no choice of location, and no "open with" (the N79 has no generic file-open
  API; the note after saving shows the full path).

Upload side (`Upload.media`, `tgclient.py:1765`): images ≤ 10 MB (`PHOTO_LIMIT`) go as photos, other
images are forced to documents, audio gets `documentAttributeAudio` with duration/title/performer,
videos get `documentAttributeVideo` with duration/width/height, and every document carries
`documentAttributeFilename`. One upload at a time, cancel supported, 2000 MB cap, 64 KB parts with
retry.

---

## 3. Chat-kind matrix

Behaviour differences between a personal chat (`u`), a group (`c`/supergroup `h`, writable), a
channel we only read (`h`, `can_write = 0`) and a channel we administer (`h`, `can_write = 1`).
Rows marked ✔ are asserted in `test_matrix.py`.

| Action | Personal | Group | Channel (read-only) | Channel (admin) |
|---|---|---|---|---|
| Sender name inside the bubble | — ✔ | ✔ (coloured per sender) | — | — |
| Header: online / members / subscribers | ✔ | ✔ | ✔ | ✔ |
| Input bar | `Message` ✔ | `Message` ✔ | `Only admins can post here` ✔ | `Message` ✔ |
| Write / attach | ✔ | ✔ | refused before opening the editor ✔ | ✔ |
| Reply | ✔ | ✔ | hidden ✔ (Telegram has comments, RetroTele not) | ✔ |
| Forward out | ✔ | ✔ | ✔ | ✔ |
| Edit own text | ✔ | ✔ | hidden | ✔ |
| Delete | ✔ (own and their own messages) | ✔ | ⚠ shown for other people's posts (defect D4) | ✔ |
| Poll vote | ✔ | ✔ | hidden ✔ | ✔ |
| Poll results | ✔ | ✔ | ✔ | ✔ |
| "Message <sender>" (open a DM from a group) | — | ✔ (users only) | — | — |
| Bot buttons | ✔ | ✔ | ✔ | ✔ |
| Mute / unmute (profile screen) | ✔ | ✔ | ✔ | ✔ |
| Profile / member count | ✔ | ✔ | ✔ | ✔ |
| Search inside the chat | ✔ | ✔ | ✔ | ✔ |
| Telegram call / phone call | ✔ | via member's profile only | — | — |
| Read receipts, ticks, online dot | ✔ | ✔ | channel: views | channel: views |
| Typing indicator (send + show) | ✔ | ✔ `Bob is typing...` | ✔ (shows only if the channel allows it) | ✔ |
| Reactions (show + send) | ✔ | ✔ chips under the bubble, `React` opens a scrollable emoji strip | ✔ | ✔ |
| Copy text | ✔ `Copy text` | ✔ copy + `Paste` in the message box | ✔ | ✔ |

---

## 4. Messaging action matrix

| Action | Works | Where |
|---|---|---|
| Send text (multi-line kept) | ✅ | `compose` → `send_text` |
| Reply (quoted bar, sent as reply) | ✅ | `compose(reply_to)`, `inputReplyToMessage` |
| Edit own text | ✅ | `compose(0, m)` → `edit_text` |
| Edit a caption of my own photo/file | ❌ | `message_menu` only offers Edit when `not m["media"]` (defect D5) |
| Delete for me / for everyone | ✅ | `delete_message` asks, passes `revoke` |
| Forward to a chat | ✅ | `forward_message` → `messages.forwardMessages`, picker lists chats |
| Copy text | ✅ | `Copy text` puts the text in RetroTele's own clipboard (PyS60 1.4.5 has no system one) and `Paste` in the message box inserts it (D6 fixed) |
| React (20 emoji strip + remove) | ✅ | `React` opens `ReactView`: a horizontal strip scrolled with left/right, sent with `messages.sendReaction`; chips update live via `updateMessageReactions` |
| Typing indicator, outgoing | ✅ | `messages.setTyping` when the editor opens and every 4 s while it has text, cancelled on send/cancel |
| Typing indicator, incoming | ✅ | `updateUserTyping` / `updateChatUserTyping` / `updateChannelUserTyping`, drawn at once, 6 s expiry, shown in the header and the chat list |
| Multi-select | ❌ | one message at a time |
| Pin/unpin, copy link, translate, save to Saved Messages | ❌ | not implemented |
| Drafts | ⚠ memory only | `self.drafts`, not written to `settings.txt` (defect D7) |
| Mark read | ✅ | `mark_read` on open and on the last message visible |
| Search chats / contacts | ✅ | `App.search`, `resolve_username` |
| Search messages in a chat + jump | ✅ | `search_chat`, `jump_to_message`, `fetch_around` |
| Global message search | ❌ | — |
| Folder tabs from the server | ✅ read-only | `get_filters`, `tabs()`: **All**, then your own folders in the server's order, then Unread / Personal / Groups / Channels / Archived / Contacts — the order Telegram for Android uses; each label carries its unread count, e.g. `All (5)` (D8 fixed) |

---

## 5. Media/call extras

| Item | Status |
|---|---|
| Audio player: play/pause, position bar, ±10 s, auto-close at end | ✅ (`PlayerView`) |
| Photo viewer: full screen, back returns to the chat | ✅ |
| Photo download progress | ✅ in the status line; no cancel button |
| `Save file` / `Save video` / `Save audio` / `Save voice message` | ✅ whole file to `media\<fID>.<ext>`, progress, `.part` resume, "Already saved" on repeat |
| `Open file` / `Play video` / `Play voice message` | ✅ downloads if needed, then `Content_handler.open_standalone` hands it to the phone's own reader/player |
| `Save picture (original)` | ✅ largest photo size (`photo_full`), not the 320 px preview |
| Audio download progress + "keep using other chats meanwhile" | ✅ |
| Voice-note Opus decoding | ❌ (device/codec work, not UI) |
| Video decoding/playback | ❌ |
| Calls 2.4.4 / 2.7.7 voice, mute, speaker/earpiece, video both ways, self-view, camera switch | ✅ (covered by `test_flow.py` / `test_callvideo.py`) |
| Bluetooth/wired headset in calls | ⛔ disabled by design, documented in `CALL-277-SPEC.md` |
| In-chat sounds; notifications Off / In-app banner / Popup, chosen from a list | ✅ |

---

## 6. Defects (status after the save/Play pass)

Fixed in this change: **D2** (documents/videos/GIFs/voice notes can be saved), **D3** (no `Play` on
Opus voice notes; they are saved instead), **D9** (the original-size photo can be saved). **D1** is
half fixed: videos can now be *downloaded*, but there is still no decoder, so nothing plays them.
The rest are open.

| # | Defect | Evidence | Severity |
|---|---|---|---|
| **D1** | **Video files cannot be played.** A received video shows its thumbnail and `Video 0:04`; it can now be saved to the card, but no player exists for MP4/3GP, so nothing opens it in-app. | `message_menu` has no video branch; no video decoder | high (playback still missing) |
| ~~**D2**~~ | ~~Documents, videos, GIFs, stickers and voice notes cannot be downloaded at all.~~ **Fixed:** `Save file` / `Save voice message` in the message menu (`save_file`, `download_to`) writes the whole file to `media\<fID>.<ext>`, with progress, resume and the big-file warning. | `tgclient.doc_file`, `retrotele.save_file`, `download_to` | fixed |
| ~~**D3**~~ | ~~`Play` is offered on voice messages and then always refused.~~ **Fixed:** `tgclient.audio_playable` decides the menu item; voice notes show `Save voice message` instead of `Play`. | `tgclient.audio_playable`, `message_menu`, `play_audio` | fixed |
| **D4** | **`Delete` appears on other people's channel posts.** `if not m["service"] or m["out"]: Delete` — in a channel we are a plain subscriber, the server rejects deleting someone else's post. | asserted in `test_matrix.py` (documented as known) | low (fails at the server) |
| **D5** | **Captions cannot be edited.** Telegram allows editing the caption of a photo/video/document; RetroTele only offers Edit on text-only messages. | `not m["media"]` guard | medium |
| ~~**D6**~~ | ~~No `Copy` in the message menu.~~ **Fixed:** `Copy text` uses the S60 clipboard when the Python build exposes it, else explains the *Read full message* route. | `copy_text` | fixed |
| **D7** | **Drafts are lost when the app restarts** (kept in `self.drafts` only, not in `settings.txt`/`cache.bin`). Telegram keeps them in the cloud. | `cancel_compose`, `save_cache` | low |
| ~~**D8**~~ | ~~Folder tab unread badges are computed and dropped.~~ **Fixed:** `App.tab_badges()` counts unread chats for all tabs in one pass (the tab bar asks once per repaint, not once per tab) and the tab label is drawn as `All (5)` — the count is part of the label, so it widens the tab instead of overlapping it. | `tab_badges`, `tab_match`, `ChatListView.paint` | fixed |
| **D9** | **Photos in the viewer are preview resolution.** `view_photo` still shows the ~320 px preview scaled to the screen (memory). **The original is now reachable**: `Save picture (original)` uses `tgclient.photo_full` (largest size, e.g. 800/1280 px) and writes `media\<pID><size>.jpg`. | `photo_preview` vs `photo_full`, `save_photo` | fixed for saving, viewer unchanged |
| — | *Checked and fine:* the Options menu is gated on `can_write`, so a read-only channel never offers `Write message`/`Attach file`; `ChatView` shows `Only admins can post here` instead. | `update_chat_menu`, `ChatView.paint` | — |

---

## 6b. Added in the typing / reactions pass

- **Typing indicator, both ways.** `messages.setTyping` when the editor opens (not while editing),
  cancelled on send and cancel; `updateUserTyping`, `updateChatUserTyping` and
  `updateChannelUserTyping` are stored with a 6 s expiry and shown as `typing...` /
  `Bob is typing...` in the chat header (`status_text`) and in the chat-list preview.
- **Reactions.** `messageReactions` is parsed into chips (`reaction_emoji` / `reactions_of`, custom
  emoji skipped), drawn under the bubble with the emoji from the sprite sheet and highlighted when
  it is ours; `React` in the message menu sends one of six (thumbs up, heart, fire, laugh, cry, wow)
  or clears it, and `updateMessageReactions` refreshes the chat live.
- **Copy text** in the message menu (clipboard when available).
- **Folder tab badges** now drawn.
- **Schema whitelist fixed:** `schema/make_schema.py` was missing `messages.search`,
  `messages.getBotCallbackAnswer` and `messages.sendVote`, which the shipped `schema.txt` had by hand;
  regenerating it would have silently removed search-in-chat, bot buttons and poll voting. Those three
  plus the new `messages.sendReaction` are in the list now, and `schema.txt` gained exactly one line.

Known limits of this batch: the reaction set is fixed (a chat that restricts reactions to other
emoji will reject it with a server error shown as a toast); custom/animated emoji reactions are not
rendered; `messages.search` is still used only for in-chat search, not global search.

## 6c. Added in the 0.19.0 pass (the N79 test report)

- **Emoji never drew.** `tgui.emoji_index()` incremented an undefined `n`, so the index build threw
  and was swallowed: every emoji fell back to the phone font's empty box (reactions, stickers).
  Fixed with `n = 0`; `react_label` now runs its text through `prep`, so chips use the sprite sheet.
- **Reaction bar.** `React` opens `ReactView`, a horizontal strip of Telegram's 20 default reactions
  (`REACTION_FALLBACK`, kept as UTF-8 bytes because this Python's unicode is UCS-2) that scrolls
  with left/right and sends with Select; the last slot removes our reaction.
- **Copy / paste.** PyS60 1.4.5 has no `set_clipboard`: `Copy text` now stores the text in
  `App.clipboard` and the message box offers `Paste`.
- **Documents open.** `Open file`, `Play video` and `Play voice message` save if needed and call
  `appuifw.Content_handler.open_standalone`, i.e. the phone's own PDF reader, zip manager or player.
- **Video is no longer labelled like a picture** (`Play video` / `Save video`) and its thumbnail no
  longer offers `View picture`.
- **`Save audio`** writes mp3/m4a/aac like the photos do.
- **Typing.** The incoming line is drawn immediately (it used to wait for the 7 s expiry redraw) and
  `messages.setTyping` is renewed every 4 s while the editor holds text, so it no longer times out
  after ~5 s.
- **Edited-time bug.** The bubble layout cache did not include the timezone, so a bubble laid out
  before the offset was known kept a UTC time (`edited 05:41` for 11:11 IST). The cache key now has
  `app.tz`, `local_offset` falls back to `time.timezone` when Symbian reports localtime as UTC, and
  the offset is written to the log at connect.
- **Tab order** now matches Telegram for Android: All, your folders, then the built-in tabs.
- **Notification settings** are a three-item list (Off / In-app banner / Popup for every message)
  instead of a rotating toggle; the banner mode still shows a small global note when RetroTele is in
  the background.

## 7. What still needs the phone (cannot be proven on the PC)

These are the checks the harness cannot do; each needs the N79 and (for several) a second account.

1. **Codec reality:** does the phone's audio stack really play MP3/M4A/AAC/WAV/AMR the way the
   player expects, and how does a 3 MB MP3 behave while a call is up.
2. **Memory**: a chat with 20 photos + an MP3 open, then a video call — does the app survive
   (`Media.LIMIT` is 10 pictures).
3. **Sockets**: real long-poll/keepalive, reconnect after Wi-Fi loss, access-point switch.
4. **Downloads**: resume after killing the app mid-download (`.part` truncation), and free-space
   behaviour when the card is full.
5. **Calls**: 2.7.7 against an official app, video up/down at 240x480, the send-only/recv-only
   fallbacks, and the audio helper's watchdog (already documented in `CALL-277-SPEC.md`).
6. **Notifications**: banner vs system popup while another app is in front; muted chats.
7. **Uploads**: a 10 MB photo (photo vs document switch), a 2000 MB guard, cancel in the middle.
8. **Channel posting** as an admin (this test account is a plain member), and deleting a post of
   another author to confirm D4 on the server.

---

## 8. How to re-run

```sh
sh pys60/tests/run.sh                 # everything, no network
cd pys60 && ../tools/mamba/py27/bin/python2 tests/test_matrix.py   # matrix alone
```

`test_matrix.py` is part of `run.sh` now, so a regression in any of the tables above fails the
suite.
