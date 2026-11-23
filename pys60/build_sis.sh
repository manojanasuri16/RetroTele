#!/bin/sh
# Builds the native S60 3rd Edition app (needs Python for S60 1.4.5 on the
# phone). Run ../tools/setup.sh once first. One package, dist/RetroTele.sis:
# the installer asks for phone memory or the memory card, and it works on
# either, wherever Python for S60 is installed: retrotele_rscfix.exe, run once
# by the installer, puts appuifw's resource file on the app's drive (see
# rscfix/README.md).
set -e
cd "$(dirname "$0")"
PY=../tools/mamba/py27/bin/python2
ENS=../tools/ensymble/src/ensymble.py
# the version lives in retrotele.py (VERSION = u"x.y.z"); bump it for every release
VERSION=$(sed -n 's/^VERSION = u"\([0-9.]*\)".*/\1/p' retrotele.py)
[ -n "$VERSION" ] || { echo "VERSION not found in retrotele.py"; exit 1; }
echo "building RetroTele $VERSION"
mkdir -p build dist cert

# Self-signed certificate, valid 2008-2037 so it also installs when the
# phone's date is set back. Keep the key private (cert/ is not committed).
if [ ! -f cert/retrotele_key.pem ]; then
  openssl req -x509 -newkey rsa:1024 -sha1 -nodes \
    -not_before 20080101000000Z -not_after 20371231000000Z \
    -subj "/CN=RetroTele/O=RetroTele" \
    -keyout cert/retrotele_key.pem -out cert/retrotele_cert.pem
  openssl rsa -in cert/retrotele_key.pem -traditional -out cert/retrotele_key.pem
fi

MODULES="tgcrypto.py tl.py mtproto.py fileinfo.py tgclient.py tgsrp.py tgui.py callaudio.py callvideo.py filepick.py"
for f in retrotele.py launcher.py videomirror.py $MODULES; do python3 tools/check_py22.py "$f" >/dev/null; done
python3 tools/check_ints.py retrotele.py launcher.py videomirror.py $MODULES

# The installed app is split into modules (the phone compiles each one
# separately), plus the TL schema. Files go to \private\e7a3d5c2\.
rm -rf build/app && mkdir -p build/app
cp launcher.py build/app/default.py
cp retrotele.py build/app/rt_app.py
cp $MODULES schema.txt build/app/
cp assets/* build/app/          # emoji sheets (Twemoji, CC-BY 4.0)
# compiled crypto (native/build_native.sh) goes to C:\sys\bin\tgnative.pyd
EXTRAS=""
if [ -f native/tgnative.pyd ] && [ "$NATIVE" != 0 ]; then
  mkdir -p build/app/extras/sys/bin
  cp native/tgnative.pyd build/app/extras/sys/bin/
  EXTRAS="--extrasdir=extras"
  echo "including native/tgnative.pyd"
fi
# the call audio helper: runs the call itself (Opus, VoIP audio, relay protocol)
if [ -f native/tgcallaudio.exe ]; then
  mkdir -p build/app/extras/sys/bin
  cp native/tgcallaudio.exe build/app/extras/sys/bin/
  EXTRAS="--extrasdir=extras"
  echo "including native/tgcallaudio.exe (calls)"
fi
# send-only video in calls: the camera/encoder helper (UID E9, MultimediaDD + UserEnvironment
# in its own capability set, same binary as the videomirror package) and tgvdisp.pyd (EA, self-view).
# Both are optional at runtime: without them calls stay voice-only. Installed to the app's
# drive next to tgcallaudio.exe (--drive=any; rscfix needs nothing extra: no Python UI in them).
if [ -f native/tgvideo.exe ] && [ -f native/tgvdisp.pyd ]; then
  mkdir -p build/app/extras/sys/bin
  cp native/tgvideo.exe native/tgvdisp.pyd build/app/extras/sys/bin/
  EXTRAS="--extrasdir=extras"
  echo "including native/tgvideo.exe + native/tgvdisp.pyd (video calls)"
fi
if [ -f native/retrotele_rscfix.exe ]; then
  mkdir -p build/app/extras/sys/bin build/app/extras/resource/retrotele
  cp native/retrotele_rscfix.exe build/app/extras/sys/bin/
  cp rscfix/appuifwmodule.rsc build/app/extras/resource/retrotele/
  EXTRAS="--extrasdir=extras"
  echo "including native/retrotele_rscfix.exe (any-drive install)"
fi

OPTS="--uid=0xE7A3D5C2 --appname=RetroTele --version=$VERSION \
  --caption=RetroTele --shortcaption=RetroTele --vendor=RetroTele --icon=icon.svg \
  --caps=NetworkServices+LocalServices+ReadUserData+WriteUserData+UserEnvironment \
  --heapsize=4k,24M --cert=cert/retrotele_cert.pem --privkey=cert/retrotele_key.pem $EXTRAS"
rm -f dist/RetroTele-card.sis
$PY tools/py2sis_rscfix.py "$(dirname $ENS)" $OPTS --drive=any build/app dist/RetroTele.sis \
  </dev/null >build/py2sis.log
grep "rscfix" build/py2sis.log || true
echo "built dist/RetroTele.sis"
ls -la dist

# Video hardware probe (E:\retrotele_videoprobe.txt). Own package, own UID; not part of RetroTele.sis.
if [ -f native/tgvprobe.exe ]; then
  rm -rf build/vidprobe_app && mkdir -p build/vidprobe_app/extras/sys/bin
  cp native/tgvprobe.exe build/vidprobe_app/extras/sys/bin/
  cat > build/vidprobe_app/default.py <<'PYEOF'
# RetroTele video probe: runs tgvprobe.exe, waits for its report file.
import e32
import appuifw
import os

PATHS = ["E:\\retrotele_videoprobe.txt", "C:\\Data\\retrotele_videoprobe.txt"]


def finished():
    for p in PATHS:
        try:
            f = open(p, "r")
            t = f.read()
            f.close()
        except:
            continue
        if t.find("probe end") >= 0:
            return p
    return None


def main():
    for p in PATHS:
        try:
            os.remove(p)
        except:
            pass
    try:
        e32.start_exe(u"tgvprobe.exe", u"")
    except:
        appuifw.note(u"Cannot start tgvprobe.exe", "error")
        return
    appuifw.note(u"Video probe running, please wait...", "info")
    done = None
    n = 0
    while n < 180:
        e32.ao_sleep(1)
        done = finished()
        if done is not None:
            break
        n = n + 1
    if done is None:
        appuifw.note(u"Probe did not finish. Look for retrotele_videoprobe.txt", "error")
    else:
        appuifw.note(u"Done: " + unicode(done), "info")


main()
PYEOF
  $PY $ENS py2sis --uid=0xE7A3D5E5 --appname="RetroTele video probe" --version=$VERSION \
    --caption="RetroTele video probe" --shortcaption="Video probe" --vendor=RetroTele \
    --caps=NetworkServices+LocalServices+ReadUserData+WriteUserData+UserEnvironment \
    --drive=C --extrasdir=extras \
    --cert=cert/retrotele_cert.pem --privkey=cert/retrotele_key.pem \
    build/vidprobe_app dist/RetroTele-videoprobe.sis </dev/null >build/vidprobe.log
  echo "built dist/RetroTele-videoprobe.sis"
fi

# Video benchmark (E:\retrotele_videobench.txt). Own package, own UID; not part of RetroTele.sis.
if [ -f native/tgvbench.exe ]; then
  rm -rf build/vidbench_app && mkdir -p build/vidbench_app/extras/sys/bin
  cp native/tgvbench.exe build/vidbench_app/extras/sys/bin/
  cat > build/vidbench_app/default.py <<'PYEOF'
# RetroTele video bench: runs tgvbench.exe, waits for its report file.
import e32
import appuifw
import os

PATHS = ["E:\\retrotele_videobench.txt", "C:\\Data\\retrotele_videobench.txt"]


def finished():
    for p in PATHS:
        try:
            f = open(p, "r")
            t = f.read()
            f.close()
        except:
            continue
        if t.find("bench end") >= 0:
            return p
    return None


def main():
    for p in PATHS:
        try:
            os.remove(p)
        except:
            pass
    try:
        e32.start_exe(u"tgvbench.exe", u"")
    except:
        appuifw.note(u"Cannot start tgvbench.exe", "error")
        return
    appuifw.note(u"Video bench running (about 4 min), please wait...", "info")
    done = None
    n = 0
    while n < 600:
        e32.ao_sleep(1)
        done = finished()
        if done is not None:
            break
        n = n + 1
    if done is None:
        appuifw.note(u"Bench did not finish. Look for retrotele_videobench.txt", "error")
    else:
        appuifw.note(u"Done: " + unicode(done), "info")


main()
PYEOF
  $PY $ENS py2sis --uid=0xE7A3D5E8 --appname="RetroTele video bench" --version=$VERSION \
    --caption="RetroTele video bench" --shortcaption="Video bench" --vendor=RetroTele \
    --caps=NetworkServices+LocalServices+ReadUserData+WriteUserData+UserEnvironment \
    --drive=C --extrasdir=extras \
    --cert=cert/retrotele_cert.pem --privkey=cert/retrotele_key.pem \
    build/vidbench_app dist/RetroTele-videobench.sis </dev/null >build/vidbench.log
  echo "built dist/RetroTele-videobench.sis"
fi

# H.264 software decoder benchmark (E:\retrotele_h264bench.txt): tgh264bench.exe (UID EC) in a
# small Python wrapper app (ED). Own package, not part of RetroTele.sis.
if [ -f native/tgh264bench.exe ]; then
  rm -rf build/h264bench_app && mkdir -p build/h264bench_app/extras/sys/bin
  cp native/tgh264bench.exe build/h264bench_app/extras/sys/bin/
  cat > build/h264bench_app/default.py <<'PYEOF'
# RetroTele H.264 decoder bench: runs tgh264bench.exe, waits for its report file, shows the summary.
import e32
import appuifw
import os

PATHS = ["E:\\retrotele_h264bench.txt", "C:\\Data\\retrotele_h264bench.txt"]


def report():
    for p in PATHS:
        try:
            f = open(p, "r")
            t = f.read()
            f.close()
        except:
            continue
        if t.find("bench end") >= 0:
            return p, t
    return None, None


def main():
    for p in PATHS:
        try:
            os.remove(p)
        except:
            pass
    try:
        e32.start_exe(u"tgh264bench.exe", u"")
    except:
        appuifw.note(u"Cannot start tgh264bench.exe", "error")
        return
    appuifw.note(u"H.264 bench running (about 1.5 min), please wait...", "info")
    p = None
    n = 0
    while n < 400:
        e32.ao_sleep(1)
        p, t = report()
        if p is not None:
            break
        n = n + 1
    if p is None:
        appuifw.note(u"Bench did not finish. Look for retrotele_h264bench.txt", "error")
        return
    lines = []
    for l in t.split("\n"):
        if l.find("SUMMARY") >= 0 or l.find("check:") >= 0 or l.find("PANIC") >= 0:
            lines.append(unicode(l.strip()))
    appuifw.app.title = u"H.264 bench"
    txt = appuifw.Text()
    txt.set(u"Report: " + unicode(p) + u"\n\n" + u"\n".join(lines))
    appuifw.app.body = txt
    lock = e32.Ao_lock()
    appuifw.app.exit_key_handler = lock.signal
    lock.wait()


main()
PYEOF
  $PY $ENS py2sis --uid=0xE7A3D5ED --appname="RetroTele h264 bench" --version=$VERSION \
    --caption="RetroTele h264 bench" --shortcaption="H264 bench" --vendor=RetroTele \
    --caps=NetworkServices+LocalServices+ReadUserData+WriteUserData+UserEnvironment \
    --drive=C --extrasdir=extras \
    --cert=cert/retrotele_cert.pem --privkey=cert/retrotele_key.pem \
    build/h264bench_app dist/RetroTele-h264bench.sis </dev/null >build/h264bench.log
  echo "built dist/RetroTele-h264bench.sis"
fi

# Video mirror, STAGE 1 of video calls: camera -> H.264 encode -> decode -> screen on this phone
# (E:\retrotele_videomirror.txt). Own package, own UID; not part of RetroTele.sis.
# tgvideo.exe (MultimediaDD) does the codecs, tgvdisp.pyd draws its frames into graphics.Image.
if [ -f native/tgvideo.exe ] && [ -f native/tgvdisp.pyd ]; then
  rm -rf build/vidmirror_app && mkdir -p build/vidmirror_app/extras/sys/bin
  cp native/tgvideo.exe native/tgvdisp.pyd build/vidmirror_app/extras/sys/bin/
  cp videomirror.py build/vidmirror_app/default.py
  $PY $ENS py2sis --uid=0xE7A3D5EB --appname="RetroTele video mirror" --version=$VERSION \
    --caption="RetroTele video mirror" --shortcaption="Video mirror" --vendor=RetroTele \
    --caps=NetworkServices+LocalServices+ReadUserData+WriteUserData+UserEnvironment \
    --drive=C --extrasdir=extras \
    --cert=cert/retrotele_cert.pem --privkey=cert/retrotele_key.pem \
    build/vidmirror_app dist/RetroTele-videomirror.sis </dev/null >build/vidmirror.log
  echo "built dist/RetroTele-videomirror.sis"
fi

# LOCAL-ONLY bundle: embeds Nokia's VoIP Audio Services (VoIPAudioSrvc SISX) so
# one file installs everything. Nokia's licence forbids distributing that file,
# so this package is NOT published (dist/ is git-ignored and never uploaded).
# Set VOIP_SIS=/path/to/VoIPAudioSrvc_3132_0x10207b9e.SISX to enable.
VOIP_SIS=${VOIP_SIS:-$(cd .. && pwd)/../symbian-sdk/apipack/x/voip/InstallToDevice/VoIPAudioSrvc_3132_0x10207b9e.SISX}
if [ -f "$VOIP_SIS" ]; then
  $PY $ENS mergesis --cert=cert/retrotele_cert.pem --privkey=cert/retrotele_key.pem \
    dist/RetroTele.sis "$VOIP_SIS" dist/RetroTele-full.sis </dev/null >build/mergesis.log 2>&1
  echo "built dist/RetroTele-full.sis (local only: contains Nokia's VoIP service)"
fi
