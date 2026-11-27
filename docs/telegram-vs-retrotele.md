# Telegram (Android 12.10.1) vs RetroTele (0.16.2/0.17.1) — what is done, what is not, what could be better

Companion to [`telegram-android-inventory.md`](telegram-android-inventory.md) (the app walkthrough
with screenshots). Test evidence and defect list: [`FEATURE-MATRIX.md`](FEATURE-MATRIX.md). This file maps every area of the Android app onto RetroTele's actual code
(`pys60/retrotele.py`, `tgclient.py`, `tgui.py`), so "done" means *implemented in the source*, not
just claimed in the README.

Legend:

| Mark | Meaning |
|---|---|
| ✅ **Done** | works in RetroTele, close enough to Telegram |
| 🟡 **Done, can improve** | works, but noticeably weaker or missing a detail Telegram users expect |
| ❌ **Not done** | not implemented at all |
| ⛔ **Out of scope** | needs hardware/framework the N79 + PyS60 don't have (or is server-only) |

---

## 1. Chat list

| Feature | Telegram | RetroTele | Status |
|---|---|---|---|
| List of chats with last message, time, unread count | yes | yes (`tab_rows`, `paint_row`) | ✅ |
| Tabs / folders | All, custom folders, Personal, Groups, Channels, Unread | same set built in + **server folders** merged (`App.tabs`, `BUILTIN_TABS`) | ✅ |
| Switch tabs | tap tab, swipe list horizontally | left/right keys (4/6) | 🟡 tap/swipe on a touch phone would be natural; keys are the only way |
| Folder unread badges | per-tab counters | `App.tab_badges()` counts unread chats once per repaint; the tab label shows `All (5)` | ✅ |
| Archived chats | own row + list | `Archived` tab (`tab_rows`, `spec == "archived"`) | 🟡 no "Archived Chats" row at the top of the list as in Telegram |
| Contacts tab in list | separate bottom tab | `Contacts` tab at the end of the tab row | ✅ |
| Pinned chats | pin icon, section at top | server order kept, `pinned` flag used for sorting (`move_to_top`, `dialog_row`) | 🟡 no pin/unpin from the app (no `messages.toggleDialogPin`) |
| Mute / unmute | long-press row → Mute | from the profile screen (`set_mute`) | 🟡 no mute from the list; muted icon is drawn |
| Read/unread ticks, online dot, muted icon, verified badge | all | ticks + online dot + muted drawn (`tgui.tick`, `paint_row`) | ✅ |
| Typing indicator (`typing…`) | header + row | `messages.setTyping` on compose; incoming typing with 6 s expiry in the header and the row | ✅ |
| Draft shown in list (`Draft:`) | yes | `draft_preview` is drawn by `paint_row` | ✅ |
| Story ring on avatars | yes | — | ⛔ (no stories support) |
| Long-press a row → Mark read / Hide / Archive / Delete / Pin / Clear | full sheet | none; only `Mark all read` for the whole tab | ❌ |
| Swipe row to archive | yes | — | ❌ |
| "Mark all read" | yes | `mark_tab_read` | ✅ |
| New chat by @username | FAB / search | menu `New chat (@username)` → `resolve_username` | ✅ |
| Create a group / channel | New Group | — | ❌ |
| Chat cache so the list opens instantly | yes | `cache.bin` (`save_cache`) | ✅ |
| Account switcher (multi-account) | tap the header title | single account | ⛔ (one session per run) |
| `Day Mode` switch in the list menu | yes | — (the theme is fixed) | ❌ |

## 2. Chat screen

| Feature | Telegram | RetroTele | Status |
|---|---|---|---|
| Header: name, status, member count / online | yes | `ChatView.header` (`members, N online`, status text) | ✅ |
| Open profile from header | tap title/avatar | right key or Options > View profile | 🟡 no touch target on the header |
| Pinned message bar with jump | yes | no in-chat pinned bar (only the `pinned a message` service line) | ❌ |
| Unread divider + collapse | yes | unread tracking exists, no divider UI | ❌ |
| Date dividers | yes | `day_label` in `ChatView.paint` | ✅ |
| Bubbles, grouping, colours, sender names | yes | `layout()` + `paint_msg` | ✅ |
| Reply quotes (tap to jump) | yes | reply header drawn; jumping only through search/`focus_message` | 🟡 the quote is not tappable |
| Forwarded-from header | yes | `forwarded from` label | ✅ |
| `edited` marker | yes | yes in the bubble footer | ✅ |
| Views + time on channel posts | yes | views drawn for channels | ✅ |
| Reaction chips under bubbles | yes | chips drawn, `React` menu with six emoji, live `updateMessageReactions` | ✅ (fixed set; custom emoji not shown) |
| Reply count / comments thread on channel posts | yes | not read (`replies` not parsed) | ❌ |
| Service messages | yes | `action_text` handles joins, pins, calls, etc. | ✅ |
| Scroll up loads older automatically | yes | `load_older` on scroll/up key | ✅ |
| Jump-to-bottom button with unread count | yes | `Jump to latest` menu item only | 🟡 |
| Long-press message → reactions / reply / forward / edit / delete / copy | one gesture | `message_menu` popup with Reply, Forward, Edit, Delete, View picture, Play, Poll, Bot buttons, Message sender | 🟡 works, but it is a scroll menu, not the two-tap action bar; no Copy, no Select-multiple, no reactions |
| Multi-select several messages | yes | — | ❌ |
| Copy message text | long-press → copy | `Copy text` (clipboard when the build has one, else a hint to use Read full message) | ✅ |
| Pin / unpin a message | yes (admins) | — | ❌ |
| Delete for me / for everyone | yes | `delete_message` asks and passes `revoke` | ✅ |
| Edit own text message | yes | `compose(0, m)` → `edit_text` | ✅ |
| Telegram voice/video call from the chat | yes | `telegram_call` (2.7.7 engine) | ✅ |
| Read receipts / online status | yes | `mark_read`, `is_online` | ✅ |
| In-chat search with hits and jump | magnifier + ‹ › | `search_chat` → list of hits → `jump_to_message` | ✅ |
| Message links / mentions / hashtags tappable | yes | links, @mentions and #hashtags are drawn as plain text; only bot URL buttons give a copyable `Link:` note (`bot_buttons`) | ❌ nothing in a message body is tappable |
| Inline bot keyboards | yes | `bot_buttons` + callback queries | ✅ |
| Polls: vote, results, live updates | yes | `vote_poll`, `show_poll`, `updateMessagePoll` | ✅ |
| "Select all"/"Copy selection" in a channel | yes | — | ❌ |
| Secret chats | yes | — | ⛔ (separate protocol, not planned) |
| Topics (forum groups) | yes | — | ❌ |
| Scheduled messages / "Remind me later" | yes | — | ❌ |

## 3. Composing and sending

| Feature | Telegram | RetroTele | Status |
|---|---|---|---|
| Write and send text | yes | `compose`/`send_now` | ✅ |
| Any number key starts a message from the chat | — | yes (`ChatView.key`) | ✅ |
| Reply | yes | reply bar in compose, `reply_to` | ✅ |
| Edit | yes | ✅ | ✅ |
| Drafts kept per chat | yes (cloud drafts) | local, in memory only (`self.drafts`) — lost on restart | 🟡 |
| Emoji picker | full panel with categories | emoji are drawn as images; insertion via `emoji.txt` list → `emoji_index` | 🟡 no categories/search, small set |
| Stickers | send from packs | received stickers drawn as big emoji; **sending stickers not implemented** | 🟡 |
| GIFs | send/search | — | ❌ |
| Voice messages | hold mic to record | **not implemented** (records nothing; Opus/OGG playback not possible either) | ❌ |
| Video messages (round) | yes | — | ❌ |
| Attach photo / any file | Gallery, File | `attach_file` → `filepick` → upload with caption (`send_file`) | ✅ |
| Send location | yes | — | ❌ |
| Send contact | yes | — | ❌ |
| Create poll | yes | — (voting only) | ❌ |
| Checklist / article / gift | yes | — | ⛔ |
| Scheduled send | yes | — | ❌ |
| Typing indicator to the other side | yes | no `messages.setTyping` | ❌ |
| Markdown/bold in messages | yes | text sent as plain text (`send_text`) | 🟡 |
| Link previews in compose | yes | — | ❌ |
| Bot commands `/` list | yes | — | ❌ |
| Multi-line text | yes | `\u2029` → `\n` conversion | ✅ |

## 4. Media

| Feature | Telegram | RetroTele | Status |
|---|---|---|---|
| Photo preview in chat (blurry → full) | yes | `PhotoLoader` progressive preview | 🟡 only the ~320 px size is ever fetched, so the viewer upscales it (FEATURE-MATRIX D9) |
| Full-screen photo viewer | yes | `PhotoView` | ✅ |
| Photo send with caption | yes | `send_file` with caption query | ✅ |
| Video preview + playback | yes | preview drawn; the file can now be **saved** (Save file), still **no player** | 🟡 |
| GIF playback | yes | — | ⛔ |
| Animated stickers / Lottie | yes | static big emoji only | ⛔ |
| Music/audio playback with bar, skip 10 s | yes | `PlayerView` (play/pause, position, 4/6 skip) | ✅ |
| Voice message playback (Opus/OGG) | yes | no playback; the menu offers `Save voice message` instead of a Play that fails | 🟡 |
| File download with progress and resume | yes | `download` + `.part` resume; `Save file` covers documents, videos, GIFs and voice notes | ✅ |
| Download on/off setting | per media type and network | one `Auto-download pictures` toggle | 🟡 |
| Save files to the phone | yes (gallery / Downloads) | `Save file` and `Save picture (original)` write into `RetroTele\media\` and show the path; no gallery hand-off | 🟡 |
| Open a file with the phone's own apps | yes | `fileinfo` shows info; no "open with" | 🟡 |
| Sticker/GIF panel | yes | — | ❌ |

## 5. Profiles

| Feature | Telegram | RetroTele | Status |
|---|---|---|---|
| Photo, name, status, phone, username, bio/description | yes | `view_profile` → `get_profile` + `ProfileView` | ✅ |
| Members count / online | yes | yes in group profile | ✅ |
| Media / Files / Links / Music tab grids | yes | profile shows the info block; no media grids | ❌ |
| Mute / unmute | yes | yes | ✅ |
| Telegram call button | yes | yes (menu) | 🟡 no on-screen Call/Video buttons |
| Normal phone call | yes | `telephone.dial` when a number is shared | ✅ |
| Add to contacts / share contact | yes | — | ❌ |
| Block / unblock / report | yes | — (only the word "block" in a comment) | ❌ |
| Edit own profile (name, bio, photo) | yes | — | ❌ |
| QR / invite link | QR code, `t.me/…` | — | ❌ |
| Profile posts / stories | yes | — | ⛔ |

## 6. Calls

| Feature | Telegram | RetroTele | Status |
|---|---|---|---|
| Incoming call popup (decline, call back by phone, reply with message) | yes | `incoming call` screen + those options | ✅ |
| Voice call 1:1, both directions | yes | 2.7.7 engine, full duplex | ✅ |
| Video: send our camera, see their video | yes | implemented (H.264 encoder + software decoder) | ✅ |
| Self-view, hide self-view, switch camera | yes | call menu items | ✅ |
| Mute microphone | yes | ✅ | ✅ |
| Speaker / earpiece switch (key 2) | output picker | ✅ | ✅ |
| Bluetooth / wired headset | yes | ⛔ on this phone, documented (helpers exist, disabled by default) | ⛔ |
| In-call effects, screen share, flip | yes | — | ⛔ |
| Call duration, call again, message after call | yes | ended screen + close | 🟡 |
| Call list with missed/incoming/outgoing | yes | — (no call history) | ❌ |
| Group calls / video chats | yes | — | ❌ |
| Ringing/vibrate settings | yes | settings exist on the phone side only | 🟡 |

## 7. Search

| Feature | Telegram | RetroTele | Status |
|---|---|---|---|
| Search chats and contacts by name | yes | `search` (dialogs + archived + contacts) | ✅ |
| Search messages in the current chat | yes | `search_chat` | ✅ |
| Search messages across all chats | yes | — | ❌ |
| Look up @username / phone | yes | `resolve_username` | ✅ |
| Search result filters (media/links/music) | yes | — | ❌ |
| Recent searches | yes | — | ❌ |
| In-chat search jump ‹ › | yes | hit list + highlight | 🟡 |

## 8. Settings and account

| Feature | Telegram | RetroTele | Status |
|---|---|---|---|
| Settings screen | ~15 pages | 8 items (`settings()`): Access point, API key, Log out, data folder, auto-download pictures, fast mode, mic boost, notifications | 🟡 far smaller, but each item is meaningful on this phone |
| Night mode / theme / wallpaper | yes | fixed Telegram-style theme | ❌ |
| Text size / chat list view / bubble corners | yes | — | ❌ |
| Notification modes | per-chat and per-type exceptions | off / in-app banner / system popup; per-chat mute | 🟡 no per-type or per-chat exceptions |
| Privacy settings (last seen, photo, calls, groups, messages) | yes | — | ❌ |
| Active sessions / devices / terminate others | yes | — | ❌ |
| Passcode, 2FA setup | yes | 2FA **login** supported (`tgsrp`), no setup/passcode | 🟡 |
| Auto-delete timers | yes | — | ❌ |
| Data & storage / cache size | yes | data folder path shown only | ❌ |
| Chat folders management (create, edit) | yes | folders are read from the server and shown as tabs; no editor | 🟡 |
| Power saving | yes | Fast mode (skip SHA-256 verify) is the equivalent lever | ✅ (different approach) |
| Proxy | yes | access point picker instead | 🟡 |
| Language | yes | English only | ❌ |
| About / version / log path | yes | `about()` | ✅ |
| Log out | yes | yes | ✅ |

## 9. Groups and channels

| Feature | Telegram | RetroTele | Status |
|---|---|---|---|
| Read group chats, sender names and colours | yes | ✅ | ✅ |
| Read-only channels detected | yes | `can_write` (broadcast check) | ✅ |
| Member list | yes | profile shows `members`; no list | 🟡 |
| Admin tools (promote, restrict, ban, permissions) | yes | — | ❌ |
| Invite links, add members | yes | — | ❌ |
| Leave / delete a chat | yes | — | ❌ |
| Create group/channel | yes | — | ❌ |
| Boost, statistics, recent actions | yes | — | ⛔ |
| Discussion/comments threads | yes | — | ❌ |
| Member tags, "Add Tag" | yes | — | ❌ |

## 10. App-level / platform

| Feature | Telegram | RetroTele | Status |
|---|---|---|---|
| Full client without a PC/proxy | yes | yes (MTProto 2.0 in pure Python + native crypto) | ✅ |
| Login: code + 2FA (phone or PC helper for PBKDF2) | yes | ✅ | ✅ |
| Fast start (session, cached chat list) | yes | ✅ | ✅ |
| Live updates + background notifications | yes | ✅ (`new_message`, notify modes) | ✅ |
| Connection status / auto-reconnect | yes | `PhoneNet`, `status` line | ✅ |
| Story posting/viewing | yes | — | ⛔ |
| Premium / Stars / Gifts / Business | yes | — | ⛔ |
| Saved Messages as a notebook | yes | appears as a chat (`kind == "self"`) | ✅ |
| Multi-account | yes | — | ⛔ |
| Share sheet ("Share to Telegram" from other apps) | yes | — | ❌ |
| Deep links `t.me/…`, `tg://` | yes | `@username` lookup only | 🟡 |
| Data usage screen | yes | — | ❌ |
| Accessibility / TTS | yes | — | ⛔ |

---

## 11. Summary

**Solidly done (parity with what the phone can do):** chat list with tabs/folders/archive/contacts,
message reading with reply/forward/edit/delete, media previews, audio playback with a player, photo
and file upload with captions and resume, profile screen with mute, polls and bot keyboards, in-chat
search, login with 2FA, live updates and notifications, and — the hard part — real Telegram voice
calls with video in both directions plus camera self-view.

**Biggest gaps, in the order a Telegram user would notice them:**

1. **Reactions** on messages (send + show) — smallest visible modern-Telegram feature, only one new
   method (`messages.sendReaction`).
2. **Typing indicator** (send `messages.setTyping`, show `updateUserTyping`).
3. **Copy message** in the message menu, and **multi-select** (forward several at once).
4. **Pinned message bar** in the chat + **pin/unpin** from the menu.
5. **Long-press row actions in the chat list** (mute, archive, mark read, delete) — currently only
   `Mark all read` for the whole folder.
6. **Leave / delete a chat**, **block a user**, **add to contacts**, **edit own profile** — the
   "manage my account" half of the app.
7. **Voice messages** (record Opus + play Opus). Playback is blocked on the codec; the README says
   the N79 can't decode Opus, so this is a hardware/work item rather than a UI one.
8. **Folder badges** on tabs (already computed, just not drawn) and **drafts across restarts** (write
   them into the settings/cache file).
9. **Media**: video playback and "open with", save-to-gallery, per-type auto-download.
10. **Search everywhere** (messages across chats, filters, recent searches) and **call history**.

**Deliberately out of scope for the N79** (do not chase): GIF/Lottie animation, animated stickers,
secret chats, topics, stories, premium/stars/gifts, multi-account, group calls, Bluetooth call audio
(experiment documented and disabled), and the full settings tree (themes, languages, privacy
toggles) — the phone has one theme and one user.

## 12. Suggested small first batch (if you want a quick visible win)

`messages.sendReaction` + reaction chips under bubbles, `messages.setTyping` on compose, `Copy` in
`message_menu`, and drawing the folder badge numbers that are already computed — four localised
changes, no new native code, and the chat screen starts looking like today's Telegram.
