# RetroTele

A small Telegram client for **Nokia S60 3rd Edition** phones (written and tested for the Nokia N79), in Python for S60 1.4.5.

Modern Symbian Telegram apps such as Symbigram need Qt Quick Components (Symbian^3/Anna/Belle), so they don't install on S60 3rd Edition. RetroTele speaks Telegram's MTProto 2.0 protocol itself, so it doesn't need a PC, a bridge or a proxy. SHA-1, SHA-256, SHA-512, AES-IGE, Diffie-Hellman and the TL serializer are all pure Python 2.2.

![RetroTele screens](docs/screenshots.png)

## Features

- Telegram-style look: blue header, round avatars (initials or the chat's photo thumbnail), unread badges, online dots, chat bubbles, read ticks
- Tabs: **All, Unread, Personal, Groups, Channels**, your own Telegram folders, **Archived** and **Contacts**. Switch with left/right.
- Log in with your phone number and the code Telegram sends you, including the two-step verification password
- Read chats and load older messages automatically by scrolling up. Replies, forwards and media show as labels such as `Photo`, `Voice message 0:04` and `Sticker`.
- Write messages and reply to a selected one. Any number key in a chat starts a message.
- **Edit**, **delete** (for you, or for everyone) and **forward** messages
- **Pictures:** photos, GIFs and videos show a preview in the chat (a blurry one at once, then the real picture). Select a message, then *View picture* to see it full screen. Downloads can be turned off in Settings.
- **Music and audio files** (MP3, M4A, AAC, AMR, WAV): select the message > Play. The file downloads once to the memory card, then plays with a play/pause button and position bar (4/6 skip 10 s). Voice messages use Opus/OGG, which the N79 can't decode yet.
- **Emoji** are drawn as pictures (the phone's fonts have none), and **stickers** show as their big emoji
- An **incoming Telegram call** pops up so you can decline it, call back by phone, or reply with a message
- Live incoming messages with a pop-up banner (muted chats stay quiet), plus read receipts and online status
- Search your chats and contacts, or open any @username
- **Call** a contact's phone number as a normal phone call
- The chat list is cached, so it appears instantly when the app starts
- **Profile** of any chat (Options > View profile, or right key in a chat): big photo, status, phone, username, bio or description, members, and Mute/Unmute
- **Fast mode** (on by default): received data is decrypted but its SHA-256 integrity hash isn't checked, which makes loading 2-3x faster on the phone. Switch it off in Settings for the full check. Big packets are decrypted in slices so keys keep working meanwhile.

There's no secret chats, file/video download, playback of GIFs or animated stickers, or answering **Telegram** voice/video calls. Calls need real-time audio streaming with the Opus codec and GIFs/stickers are MP4/WebP/Lottie, none of which Python for S60 1.4.5 can decode, so "Call" uses the normal phone line.

### Keys

| Where | Key | Does |
|---|---|---|
| Chat list | Up/down | Move |
| Chat list | Left/right | Switch tab |
| Chat list | Centre | Open chat |
| Chat | Up/down | Select message (scrolling up loads older ones) |
| Chat | Centre | On a message: reply / read in full. On the input bar: write |
| Chat | Any number key | Write a message |
| Chat | Right | Profile |
| Chat | Left or right softkey | Back to chats |

## Install

1. Install **Python for S60 1.4.5** (`PythonForS60_1_4_5_3rdEd.sis`) if it's not on the phone yet.
2. Install `RetroTele.sis` and choose **phone memory or memory card**: either works, wherever Python for S60 is installed, on an unlocked phone (e.g. the Open4All patch). A Python for S60 1.4.5 app on a different drive from Python normally closes at once, because Python's `appuifw` looks for its resource file `appuifwmodule.rsc` on the app's drive. The package includes that file and a tiny native program that the installer runs once to put it in place (see [pys60/rscfix/README.md](pys60/rscfix/README.md)). On a phone that isn't unlocked, install RetroTele on the same drive as Python.
3. On a computer, open <https://my.telegram.org>, go to **API development tools** and create an app. Note the **api_id** and **api_hash**.
4. Open RetroTele and enter api_id and api_hash once. Choose an access point (Wi-Fi or packet data), then log in.

The first connection creates a secure key with Telegram, which takes a few seconds of 2048-bit math on the phone. After that, start-up is quick. Data lives in `E:\RetroTele\` (session, settings). The log is `E:\retrotele_log.txt`.

### Two-step verification

If your account has a cloud password, Telegram wants a hash made with 100,000 rounds of PBKDF2-SHA512. In pure Python on an N79, that takes roughly an hour. You have two options:

- **Enter password (phone)**: keep RetroTele open on the charger and watch the progress in the title bar.
- **Use hash from PC helper**: RetroTele writes `RetroTele\2fa_salts.txt` to the memory card. Connect the phone as mass storage and run `python3 tools/tg2fa.py /path/to/card/RetroTele`, then type the password. Back on the phone, select **Continue**.

This is needed only once, at login.

## Native crypto module

`native/tgnative/tgnative.c` is a small compiled extension (AES-256-IGE, SHA-1, SHA-256, PBKDF2-SHA512) that replaces the pure-Python crypto when it's installed. It's hundreds of times faster: chats, pictures and music download quickly, the integrity check stays on, and two-step login takes seconds. The `.sis` installs it as `C:\sys\bin\tgnative.pyd`. If it's missing or fails its self-test, RetroTele falls back to Python automatically. **About** shows which one is in use.

A prebuilt `pys60/native/tgnative.pyd` is in the repo. To rebuild it, set up a GnuPoc toolchain for S60 3rd Edition FP2 (CodeSourcery GCCE 3.4.3, the S60 3.2 SDK and the PyS60 1.4.5 SDK plugin), then run `SYMBIAN_SDK=/path/to/it sh native/build_native.sh`.

## Build and test (Linux)

```sh
tools/setup.sh                 # private Python 2.7 + Ensymble (once)
sh pys60/tests/run.sh          # Python 2.2 checks + PC tests (LIVE=1 also talks to Telegram)
sh pys60/tests/preview/preview.sh out/   # PNG screenshots of every screen (python3 + Pillow)
sh pys60/build_sis.sh          # -> pys60/dist/RetroTele.sis
```

`schema/make_schema.py` regenerates `pys60/schema.txt` from Telegram Desktop's `api.tl` and `mtproto.tl` (currently layer 233).

The PyS60 networking pitfalls (main-thread sockets, never `close()`) are the same as in [RetroSend](https://github.com/manojanasuri16/RetroSend/blob/main/docs/PYS60-NOTES.md). Crypto code follows the Python 2.2 integer rules described at the top of `pys60/tgcrypto.py`, which `tools/check_ints.py` enforces.

## Credits

Emoji images: [Twemoji](https://github.com/twitter/twemoji) by Twitter, Inc and other contributors, licensed under [CC-BY 4.0](https://creativecommons.org/licenses/by/4.0/). The sprite sheets in `pys60/assets/` are built by `tools/emoji/make_emoji.py`.
