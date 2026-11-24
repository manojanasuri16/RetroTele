# RetroTele

A small Telegram client for **Nokia S60 3rd Edition** phones (written and tested for the Nokia N79), in Python for S60 1.4.5.

Modern Symbian Telegram apps such as Symbigram need Qt Quick Components (Symbian^3/Anna/Belle), so they don't install on S60 3rd Edition. RetroTele speaks Telegram's MTProto 2.0 protocol itself, so it doesn't need a PC, a bridge or a proxy. SHA-1, SHA-256, SHA-512, AES-IGE, Diffie-Hellman and the TL serializer are all pure Python 2.2.

![RetroTele screens](docs/screenshots.png)

## Status (0.16.1)

Tested on a real Nokia N79:

- chats: log in (incl. two-step password), read, write, reply, edit, delete, forward, pictures, files, music, emoji
- Telegram voice calls with the official apps (call library 2.7.7), both directions
- video calls: our camera video to the other side, and the other person's video on our screen (software H.264 decoder), in either order
- sound through the **phone speaker** or the **phone earpiece**, with the **phone's own microphone**; mic boost in calls (Settings), mute, call options

Not supported yet / known issues:

- **Bluetooth and wired headsets in calls.** They are ignored: calls always use the phone microphone and the phone speaker or earpiece (key 2 toggles); RetroTele asks the phone to keep the call audio on its own speaker/earpiece even when a headset is connected. (Modern earbuds such as the Galaxy Buds 2 Pro connect to the N79 for music (A2DP) only. An experimental Bluetooth routing exists behind a config flag, see docs/CALL-277-SPEC.md.)
- The other person's video above 240x480 is not shown until their app steps down (usually within seconds).
- The other person's video can be choppy at times (software decoding next to our camera and the call audio).
- Video needs the 2.7.7 call library (Settings > Call version).

## Requirements: a hacked (unlocked) phone

**RetroTele needs a hacked phone.** Its call helpers (`tgcallaudio.exe` and the other native helpers in `RetroTele.sis`) are built with the capabilities **MultimediaDD, ReadDeviceData and WriteDeviceData**, which are needed for the phone's audio and camera/video hardware. A self-signed package on a stock S60 3rd Edition phone can only be granted the user-grantable capabilities (NetworkServices, LocalServices, ReadUserData, WriteUserData, UserEnvironment, Location), so on a stock phone the install is refused. The rest of the package (the app and the `.pyd` modules) uses only user-grantable capabilities.

On the N79 this means the "Easy Hack Kit" (EasyHackKit 2.0, which installs **RomPatcher+**), with **Install Server RP+** and **Open4All RP+** applied:

1. Hack the phone once with EasyHackKit (see the [unlock guide](https://github.com/manojanasuri16/symbian-unlock-guide) for the step-by-step).
2. Before installing, open **RomPatcher+**, tick **Open4All rp+** and apply it (a green tick). Use *Options > Add to Auto* so it is applied on every boot.
3. Then install `RetroTele.sis`.

If it isn't on, the install fails with **"Update error"** or **"requested application access not granted"**. Only do this on a phone you own; a hacked phone no longer checks signatures. The same Open4All patch also lets the memory-card fix (below) write to `\resource`.

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
- **Telegram voice calls** with the official Telegram apps (call library version 2.7.7), with full-duplex audio, and **send-only video** (your camera is sent to the other side, with a self-view; the other side's video isn't shown)
- The chat list is cached, so it appears instantly when the app starts
- **Profile** of any chat (Options > View profile, or right key in a chat): big photo, status, phone, username, bio or description, members, and Mute/Unmute
- **Fast mode** (on by default): received data is decrypted but its SHA-256 integrity hash isn't checked, which makes loading 2-3x faster on the phone. Switch it off in Settings for the full check. Big packets are decrypted in slices so keys keep working meanwhile.

There's no secret chats, file/video download or playback of GIFs or animated stickers (they are MP4/WebP/Lottie, which Python for S60 1.4.5 can't decode). Voice messages use Opus/OGG, which the N79 can't decode yet.

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

0. Make sure the phone is hacked and **Open4All rp+** is on (see [Requirements](#requirements-a-hacked-unlocked-phone)).
1. Install `RetroTele.sis`. It is one file with everything: the app, the **Python for S60 1.4.5** runtime and Nokia's **VoIP Audio Services** (see [What's in RetroTele.sis](#whats-in-retrotelesis)). If Python for S60 1.4.5 or VoIP Audio Services are already on the phone (for example for RetroSend or RetroTorch), the installer keeps them. Choose **phone memory or memory card**: either works, wherever Python for S60 is installed, on a hacked phone (Open4All on, see Requirements). A Python for S60 1.4.5 app on a different drive from Python normally closes at once, because Python's `appuifw` looks for its resource file `appuifwmodule.rsc` on the app's drive. The package includes that file and a tiny native program that the installer runs once to put it in place (see [pys60/rscfix/README.md](pys60/rscfix/README.md)). Tested on a Nokia N79 with RetroTele on the memory card and Python in phone memory. On a phone that isn't unlocked, install RetroTele on the same drive as Python.
3. On a computer, open <https://my.telegram.org>, go to **API development tools** and create an app. Note your own **api_id** and **api_hash**: RetroTele ships none, you enter yours.
4. Open RetroTele and enter your api_id and api_hash once. Choose an access point (Wi-Fi or packet data), then log in.

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

## More apps for the Nokia N79

- **[RetroTorch](https://github.com/manojanasuri16/RetroTorch)**: a torch app: the camera's LED flash as a steady light, plus the screen, keypad and extra lights.
- **[RetroSend](https://github.com/manojanasuri16/RetroSend)**: send and receive files and text with the LocalSend app on phones and computers, over Wi-Fi.

Like this app, both are Python for S60 1.4.5 apps that install to phone memory or the memory card.

## What's in RetroTele.sis

One file, `RetroTele.sis`, installs everything:

- the app, the native crypto module, the call audio helper (Opus, full-duplex VoIP audio, Telegram call protocol 2.7.7), the video helpers (camera/H.264 encoder, the software H.264 decoder for the other person's video), the Bluetooth routing helper and the memory-card fix;
- the **Python for S60 1.4.5** runtime (Nokia, Apache License 2.0), embedded unmodified (UID 0x2000b1a0, version 1.4.5, its own signatures);
- Nokia's **VoIP Audio Services** system component (needed for two-way call audio; (c) Nokia, from the S60 3rd Edition FP2 API Plug-In Pack), embedded unmodified (UID 0x10207b9e).

The two Nokia components belong to their owners and are included only for convenience; if a rights holder asks, they will be removed from the package. Already-installed copies in the same version are kept by the installer. The phone hack (Open4All, see Requirements) is still needed: bundling cannot grant the helpers' capabilities. Not bundled: the Python script shell (not needed). `pys60/build_sis.sh` builds it with `ensymble mergesis` (it also makes `RetroTele-app-only.sis`, for debugging only) and lists the embedded packages with `tools/sisinfo.py`.

## Credits

Emoji images: [Twemoji](https://github.com/twitter/twemoji) by Twitter, Inc and other contributors, licensed under [CC-BY 4.0](https://creativecommons.org/licenses/by/4.0/). The sprite sheets in `pys60/assets/` are built by `tools/emoji/make_emoji.py`.

## Source code of components

The reusable parts of RetroTele live in their own open-source repos (all MIT unless noted):

- [telegram-call-engine-c](https://github.com/manojanasuri16/telegram-call-engine-c): the Telegram call engine (library 2.7.7) in portable C, with tests and the protocol notes.
- [mtproto-py22](https://github.com/manojanasuri16/mtproto-py22): MTProto 2.0, TL, 2FA SRP and the native crypto module for Python 2.2 / PyS60.
- [opus-symbian-s60](https://github.com/manojanasuri16/opus-symbian-s60): Opus built for Symbian S60 3rd Edition, with the porting notes.
- [symbian-s60v3-media-notes](https://github.com/manojanasuri16/symbian-s60v3-media-notes): N79 camera, H.264 and audio findings with the helper sources (needs a hacked phone).
- [pys60-toolbox](https://github.com/manojanasuri16/pys60-toolbox): the memory-card fix (rscfix), packaging tools and Python 2.2 checkers.

The full list is on the [RetroArchive Open source page](https://manojanasuri16.github.io/RetroArchive/opensource/).

## License

MIT, see [LICENSE](LICENSE). Third-party components keep their own licences (for example Opus: BSD; Python for S60: Apache 2.0; Nokia's VoIP Audio Services: Nokia's terms; both Nokia components are bundled in RetroTele.sis for convenience and are removed on a rights holder's request). The H.264 decoder in `native/third_party/ffmpeg-0.6.7/` (FFmpeg's, used to show the other person's video) is LGPL 2.1; see its NOTICE for the source and how to rebuild with a changed copy.
