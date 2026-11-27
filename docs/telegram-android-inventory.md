# Telegram for Android 12.10.1 — screen-by-screen inventory

**What this is.** A reference walkthrough of the Telegram app that RetroTele interoperates with,
so we have one place that describes "what a Telegram client does", option by option and screen by
screen. Kept aside from the comparison: see [`telegram-vs-retrotele.md`](telegram-vs-retrotele.md)
for what RetroTele already does.

**How it was made.** Explored on a real phone over USB with `adb`
(`org.telegram.messenger.web`, versionName 12.10.1 (7038), Android on a Nothing Phone 3a,
1080x2392), logged into the same Telegram account RetroTele uses. Every screen below was opened
on the device and captured; the PNG/JPEGs are in
[`tg-android-explore/ui/`](tg-android-explore/ui/) and are named after the figure numbers here.
Not every settings sub-page was opened (scope is listed at the end).

Notation: **tap** = touch, **long-press** = press and hold, **⋮** = the three-dot button,
**swipe-up/down** = dragging the list. "back" always means hardware/gesture Back.

---

## 1. Global navigation model

Telegram 12.x has no hamburger drawer any more. The app is a bottom bar with four items and a
single activity, so Back only ever pops the screen stack.

- **Bottom bar (always visible except in a chat/camera/full-screen media):**
  `Chats` · `Contacts` · `Settings` · `Profile`, each with an icon and a label; the selected one is
  drawn in an accent pill. Tapping the *already selected* tab scrolls that list to the top.
- **Back behaviour:** from any screen it goes one step up (chat → chat list → exit app). From the
  story camera it leaves the app. From a bottom sheet it closes the sheet first. From a chat that
  was opened from search it returns to the search results, not the chat list.
- **Long-press on the app icon** opens App shortcuts; **back from the launcher-entry screen** exits.
- **Two floating buttons** on the chat list, stacked bottom-right: `Post Story` (camera bubble) and
  `New Message` (pencil). They hide while the list is scrolled down and reappear when scrolling back
  to the top.
- **Wireframe conventions:** every list row is a "cell" that highlights on press; ⋮ in the header is
  the context menu for that screen; the back arrow is top-left; the title in the header opens the
  related profile/info screen.

---

## 2. Chats screen (fig. 01, 12, 37)

Top to bottom:

- **Header:** `Telegram` + a star (Premium badge) on the title, ⋮ on the right. Tapping the title
  opens the account switcher (multi-account: add account, switch, log out).
- **Search bar** ("Search Chats"): tapping anywhere in it opens the global search screen.
- **Folder tabs** row, horizontally scrollable: `All`, then each custom folder with its emoji and a
  badge with the unread count (`Personal`, `Groups 1`, `Channels 4`, `Unread`, plus user folders).
  - **tap** switches the list (instant, cached);
  - **long-press** a folder tab opens folder editing for that folder;
  - dragging the list horizontally also switches folders;
  - the ⋮ on the tab row / Settings > Chat Folders edits the set, order and "Show Folder Tags".
- **`Archived Chats` row** (only when something is archived): stacked-avatar icon, preview of the
  archived chats, unread badge. **tap** opens the archive list (which has its own tabs and its own
  "Archived Chats" header), **long-press** offers `Unarchive all`-style actions.
- **Chat rows**, each: avatar (photo or coloured initials, online dot or story ring), title
  (verified tick, muted speaker icon, `@username`, premium star), second line (last message preview,
  with `Photo`/`Voice`/`Sticker` labels, sender prefix `You:` in groups, or a typing indicator
  `typing…`), right column (time, pin icon when pinned, read ticks for outgoing: one tick sent, two
  ticks read in blue, clock if scheduled/pending), unread badge (green counter, or a dot/`@` for
  mentions), and a "pinned message" bar when the chat has a pinned message.
  - **tap** opens the chat;
  - **long-press** opens a bottom sheet: `Mark all as read`, `Hide from Chat List`, and (scrolled up)
    `Pin`/`Unpin`, `Mute`/`Unmute`, `Archive`, `Delete`, `Clear history`, `Edit`, `Add to folder`,
    `Select`;
  - **swipe right on a row** archives it (or unarchives, depending on the setting), with an
    Undo toast; **swipe left** can be set to Pin/Mute/Delete/Read in Settings > Chat Settings.
- **General chat-list gestures:** pull down = nothing (no refresh), tap status bar = scroll to top,
  long-press a folder tab = edit, scroll far = floating "jump to next unread" arrow appears on the
  right.
- **⋮ menu on the chats screen:** `Day Mode/Night Mode` (theme switch), `New Group`, `Saved Messages`.
  In some versions also `New Channel`, `Contacts`, `Settings`.
- **Empty states:** "No chats yet" with a hint to start one; per-folder empty text.

---

## 3. Chat screen (fig. 32, 40, 44)

### 3.1 Header
Back arrow · avatar (tap = profile/info) · title (tap = profile/info) · subtitle
(`online`, `last seen recently`, `typing…`, `2 395 members, 85 online`, `channel, 91K subscribers`,
or the pinned/`N selected` state while selecting) · magnifier (in-chat search) · ⋮ (chat menu).

### 3.2 Pinned message bar
Under the header: small pin icon, `Pinned Message` + one line of the message; **tap** jumps to the
message; if the pinned message has an inline button, the button is drawn on the right (`Click me!`);
the bar can be dismissed with a swipe. In channels/groups this is the `Pinned Message`/`Discuss`
row.

### 3.3 Message area
- **Date dividers** ("November 27", "September 30") as floating pills.
- **Unread divider**: `Unread Messages` + a chevron; **tap the chevron** collapses everything above it
  ("Unread Messages" becomes a thin line you can tap to expand again).
- **Bubble contents:** sender name (coloured, in groups; tap = open that user), reply quote (avatar,
  name, text; **tap** jumps to the quoted message), forwarded-from header (`Forwarded from …`, with a
  tap to open the source), text with links/mentions/hashtags/bold/code, media
  (photo/video/GIF/sticker/voice/file/music/poll/location/contact), caption, an inline keyboard for
  bots, a bottom-right line with `edited` and the time (+ views and forwards for channels), and
  reaction chips under the bubble (`❤️ 3`, tap = toggle your reaction, long-press = who reacted).
- **Service messages** ("X joined", "Y pinned a message", "call ended") are centred, on a tinted row.
- **Reply count** (`↳ 3`) on channel posts opens the comments thread.
- **Selection checkbox** appears on every message when in selection mode.
- **Scroll:** swipe up loads older history automatically (spinner at the top); while scrolled up a
  round "jump to bottom" button appears bottom-right, with the unread count inside it and a tick that
  marks everything as read.
- **Swipe a bubble to the right** = reply to it (configurable); swipe far = nothing.

### 3.4 Long-press on a message (fig. 41, 46)
Modern Telegram merges the old popup into **selection mode**:

- **Top action bar:** `✕` (leave) · `N Selected` · copy · forward · (delete, when allowed) ·
  `⋮`/`Edit Message Tag`. For your own messages: `Edit` (pencil) appears instead of copy-only.
- **Bottom:** reaction row (`👍❤️🔥😂😢😮` plus custom emoji and `+` to add), and the pills `Reply` and
  `Forward` (channels: `Forward` only; the `+` opens the full emoji picker to pick any reaction).
- **Long-press on a *link* inside a bubble** instead gives a small sheet: `Open`, `Open In-App`,
  `Copy Link` (fig. 19). Long-press on plain text starts text selection with handles.
- **Long-press on a sticker/GIF/video** opens a preview with `Save to Gallery`, `Add to favourites`,
  `Delete`, `Forward`; **tap** on a photo/video opens the media viewer (pinch to zoom, swipe between
  media of the same chat, ⋮ for `Save`, `Forward`, `Delete`, `Show in chat`).
- **Selecting more than one message** turns the top bar into `N Selected` with `Copy`, `Forward`,
  `Delete`, `Reply`, `Pin`; the tab bar at the bottom gets `Copy`/`Forward`/`Reply`/`Delete` shortcuts.

### 3.5 Input bar
Left to right: **emoji button** (smiley) · **text field** (`Message`, or `Broadcast` in a channel you
admin) · **attach** (paperclip) · **mic** (hold to record a voice message: slide right to lock, slide
up to cancel) which becomes a **send** arrow as soon as there is text.

Typing behaviours: `@` starts a member autocomplete; `:` opens emoji autocomplete; `/` opens the bot
command list at the start of a message; Enter sends (or inserts a newline if set to); pasting
multi-line text keeps the newlines; a draft is kept per chat (`Draft:` label in the chat list) and
survives app restarts (cloud drafts); a **reply bar** appears above the field with the quoted message
and an ✕; an **edit bar** the same way when editing, with a ✕ to cancel.

### 3.6 Attach (+) sheet (fig. 35)
A single scrollable row of tiles, then the content:
`Gallery` · `File` · `Location` · `Article` (link preview) · `Poll` · `Checklist` · `Contact` ·
`Music` · `Gift` (where available).
- Gallery opens first with a permission prompt ("Allow Access to Photos", with `Allow Access` and
  `Open Camera`); after granting it shows the media grid with album tabs, multi-select, and a caption
  field.
- `File` opens the system file picker; `Location` the map picker; `Poll` the poll composer
  (question, options, quiz mode, multiple answers, anonymous, close timer); `Checklist` the checklist
  composer.
- Attachments open as a **bottom sheet that can be dragged up to full-screen**; drag down/back closes it.

### 3.7 Emoji / sticker panel (fig. 36)
Opens over the keyboard from the smiley button; `back` closes it and keeps the keyboard.
- Top row: clock (recent), smiley (all emoji categories), then your sticker-set tabs (each with a
  picture/emoji icon), `+` to add packs, gear = sticker settings.
- Search field with emoji results *and* a row of reaction emoji under it.
- `Trending Emoji Packs` (with ✕ to hide), `Recently Used`, then the emoji grid; per-emoji
  long-press shows variants/skin tones and a preview with a copy button.
- Bottom tabs `Emoji` · `GIFs` · `Stickers`; `GIFs` has search + trending; `Stickers` lists packs
  with `Add Stickers`/gear.

### 3.8 Chat ⋮ menu (fig. 34)
As a plain member: `Mute/Unmute`, `Search`, `Boost Group`, `Report`, `Leave Group`.
As an admin the list grows: `Edit` (info), `Manage Group`/`Channel settings`, `Add members`,
`Permissions`, `Invite links`, `Statistics`, `Video chat`, `Topics`, `Recent actions`, `Delete chat`.
1-to-1 chat: `Mute`, `Search`, `Video call`, `Clear history`, `Delete chat`, `Block user`, `Report`.
`Saved Messages`: `Search`, `Clear history`.

### 3.9 In-chat search
Magnifier or ⋮ > Search: the header turns into a field; results appear as a list with sender and
date snippets; `‹ ›` arrows jump between hits and highlight them in the chat; result filters
(`Members`, `Media`, `Links`, `Music`, `Files`).

---

## 4. User profile (fig. 47)

Photo (tap = full-screen viewer, ⋮ = `Save to Gallery`) · name · status · **action buttons**
`Message` · `Mute/Unmute` · `Call` · `Video` · bio · `@username` + QR button · phone number (tap =
copy / call) · birthday, links, "Forwarded messages" etc. · `Add to contacts` / `Share contact` ·
tab row `Media` · `Files` · `Groups` · `Links` · `Music` · `Voice` (grids of shared media) ·
`Stories` row when the user posts stories.
⋮ menu: `Share contact`, `Edit` (own profile), `Delete contact`, `Block user`, `Report`, `Add to
contacts`, `Set photo` (own).

## 5. Group info (fig. 33)

Photo · name · `2 395 members, 85 online` · buttons `Message` (opens the chat) / `Unmute` / `Leave` ·
description (expandable with `more`) · invite link `t.me/xxx` + `Get QR code` · tab row
`Members` · `Media` · `Files` · `Links` · `Music` · `Polls` · member list (avatar, name, online/last
seen, member tag such as `Overtalkative`, `Add Tag`) with admin badges · `Invite a Friend` ·
`Add Members`/`Create Invite Link`. Admins additionally get `Administrators`, `Permissions`,
`Members can…` toggles, `Restrict`, `Remove`, `Ban`, `Promote`, `Recent Actions`, `Statistics`.
⋮: `Edit`, `Manage Group`, `Add Members`, `Permissions`, `Invite Links`, `Statistics`, `Leave`,
`Report`.

## 6. Channel info

Same skeleton: photo/name/`91K subscribers`/`Mute`/`Discuss`/`Share`, description, link, tab row
`Media` · `Files` · `Links` · `Music` · `Polls`, admin tools (`Edit`, `Administrators`,
`Subscribers`, `Signatures`, `Statistics`, `Reactions`), and for channel posts a per-post `Share`
arrow on the right of each bubble plus views and time.

## 7. Contacts tab (fig. 48)

Header `Contacts` + `Add contact` (+ icon) + ⋮ (`Sort by`, `Hide contacts without phone numbers`,
`Invite friends`, `Manage contacts`).
Rows: `Invite Friends` (with icon), `Recent Calls` (opens the calls list), then contacts A–Z with
online dots and story rings; tap opens the chat (not the profile), long-press gives the same sheet as
a chat row (`Send message`, `Call`, `Video call`, `Edit`, `Delete`, `Share contact`, `Block`).
Search field on top searches contacts and usernames.

## 8. Profile tab (own) 

Big photo, name, bio, `@username`, `+91 …`, buttons `Set/Edit photo`, `Edit info`, `Settings`,
`Add a post` (profile posts), and a grid icon top-left for other accounts. It is the same screen as
your own user profile but with edit affordances.

## 9. Stories

- **Post Story** (chat-list FAB): camera preview, gallery thumbnails, flash/flip, `Gallery`, text and
  sticker tools, `Next` → privacy (`Everyone`/`Contacts`/`Close Friends`/selected), caption,
  `Share to…` (chats), then post.
- **Viewer**: full-screen, progress bars at the top per story, tap right/left = next/previous, hold =
  pause, swipe down = close, reply field at the bottom, reaction chips, `⋮` = `Save`, `Forward`,
  `Copy link`, `Report`, `Hide`, viewers list ("Seen by N") for your own stories, mute/hide a
  poster's stories.

## 10. Calls

**Calls list** (Contacts > Recent Calls): rows with direction icon (incoming/outgoing/missed in red),
name, `Video`/`Call` label, date; tap row = open the contact's profile (or call again from its ⋮);
⋮ on the page = `Clear history`. There is no separate Calls tab in this version.
**Call screen**: avatar + name + status/timer, buttons `Mute`, `Video`, `Speaker`, `End` (red), `⋮`
(`Effects`, `Flip camera`, `Camera`, `Share screen`), `Minimize` to a floating bubble; call
notification with `Answer`/`Decline`; incoming call shows `Accept`, `Decline`, `Reply with message`.
**Call-ended screen** shows duration, `Call again`, `Message`, `Close`.

## 11. Global search (fig. 04, 31)

Tapping the search bar opens: a field, tab row `Chats` · `Channels` · `Apps` · `Posts` · `Media` ·
`Docs`/`Links`, "recent searches" (circles of avatars you searched before, with `Clear All`), recent
chats list, and grouped results:
`Chats and Contacts`, `Global search`, `Messages` (with `From all chats` toggle), `Channels`,
`Posts`, `Media`. Typing `@name` looks up a username; typing a phone number looks up a contact;
selecting a result opens the chat and jumps to the message when it was a message hit.

## 12. Settings tree (fig. 05, 08, 21, 30)

Root (scrolls): account block (photo, name, phone, `@username`) · `Accounts` (multi-account) ·
`Account` (Number, Username, Bio, birthday, profile photo, login email) · `Chat Settings`
(Wallpaper, Night Mode, Animations, text size, chat list view, message corners, swipe actions,
"Save to Gallery", "Show folder tags", "Double tap to…") · `Privacy & Security` (Last Seen, Devices,
Passkeys; inside: Blocked Users, Phone Number, Last Seen, Profile Photo, Calls, Forwarded Messages,
Groups & Channels, Voice Messages, Messages, Auto-Delete, Passcode, Two-Step Verification, Active
Sessions) · `Notifications` (Show notifications, Private Chats / Groups / Channels / Stories /
Reactions with per-type "On, N exceptions", Calls: Vibrate + Ringtone, Badge Counter: Show Badge
Icon / Include Muted Chats, in-app sounds, priority, exceptions) · `Data and Storage` (Storage Usage,
Data Usage, Automatic media download for mobile/Wi-Fi/roaming with size thresholds, Reset
Auto-Download Settings, Save to Gallery per chat type, Streaming: Stream Videos and Audio Files,
Proxy, Data usage circle) · `Chat Folders` (list, drag to reorder, ⋮ per folder, Create New Folder,
Show Folder Tags) · `Devices` (`Add Device` QR, `This device`, `Terminate All Other Sessions`,
Active sessions with location/time) · `Power Saving` (slider Off–On with "When below 10%",
per-effect toggles: Animated Stickers, Animated Emoji, Effects in Chats, Animations in Calls,
Autoplay Videos, Autoplay GIFs, Particles, Enable Smooth Transitions) · `Language` · `Telegram
Premium` · `Telegram Stars` · `My Grams` · `Telegram Business` · `Send a Gift` · `Help` (Ask a
Question, Telegram FAQ, Telegram Features, Privacy Policy) · version line (long-press = build info).

Every sub-page follows the same rules: rows with a right-hand value or toggle, section headers in
accent colour, red rows for destructive actions, back returns to the parent page, and toggles apply
immediately (no save button).

---

## 13. Cross-cutting behaviours worth copying

1. **Optimistic UI:** a sent message appears greyed with a clock, then gets a tick when the server
   acks; failing shows a red `!` and `Tap to retry`.
2. **Reactions** on every message, with a quick row and a "who reacted" sheet.
3. **Reply / forward / edit / delete** available from one long-press; forward shows a target picker
   with recent chats at the top and `Forward` with sender attribution kept.
4. **Drafts** are kept per chat and shown in the list as `Draft:`.
5. **Typing indicators** in the chat header and in the row's second line.
6. **Unread discipline:** unread counters, mention badges, "Mark all as read", unread divider with
   collapse, jump-to-bottom-with-count.
7. **Media pipeline:** thumbnail first, then full picture; tap = viewer; save to gallery; play audio
   inline with a progress bar; video plays in a floating player.
8. **Pinned messages** in a bar with jump; **archived** chats; **folders** with unread counts.
9. **Sessions/security:** device list, terminate others, passcode, 2FA, auto-delete.
10. **Power/notice controls:** power saving throttles animations; per-category notifications with
    exceptions; per-chat mute.

---

## 14. Scope / gaps of this pass

Opened and captured: chat list (all tabs' header state), chat list ⋮, chat row long-press sheet,
global search, New Message picker, Post Story camera, a group chat, its ⋮ menu, message selection
toolbar, link long-press sheet, attach sheet, emoji panel, group info, user profile, Settings root
(top and bottom), Account, Chat Settings, Privacy & Security, Notifications, Data and Storage, Chat
Folders, Devices, Power Saving, Contacts tab, media viewer and pins as seen inline.

Not opened in this pass (described from the app's own labels and general behaviour):
inside Privacy & Security sub-pages, inside Data & Storage sub-pages (Storage Usage, Data Usage,
Proxy), folder editor, poll/checklist composers, sticker settings, premium/stars/business screens,
story viewer, the live call UI, and admin-only group/channel tools (this account is a plain member).
Screenshots for the ones that were opened are in `tg-android-explore/ui/`.
