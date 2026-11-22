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

MODULES="tgcrypto.py tl.py mtproto.py tgclient.py tgsrp.py tgui.py"
for f in retrotele.py launcher.py $MODULES; do python3 tools/check_py22.py "$f" >/dev/null; done
python3 tools/check_ints.py retrotele.py launcher.py $MODULES

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
if [ -f native/tgcall.pyd ]; then
  mkdir -p build/app/extras/sys/bin
  cp native/tgcall.pyd build/app/extras/sys/bin/
  EXTRAS="--extrasdir=extras"
  echo "including native/tgcall.pyd (call test)"
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

# Separate helper package for the call test on unlocked phones: tgaudiotest.exe
# has MultimediaDD, which only installs where the Install Server patch lets
# self-signed packages have device capabilities. Kept out of RetroTele.sis so
# the app itself still installs everywhere.
if [ -f native/tgaudiotest.exe ]; then
  rm -rf build/audiotest && mkdir -p build/audiotest/sys/bin
  cp native/tgaudiotest.exe build/audiotest/sys/bin/
  $PY $ENS simplesis --uid=0xE7A3D5C6 --version=$VERSION --drive=C \
    --caption="RetroTele audio test" --vendor=RetroTele \
    --cert=cert/retrotele_cert.pem --privkey=cert/retrotele_key.pem \
    build/audiotest dist/RetroTele-audiotest.sis </dev/null >build/simplesis.log
  echo "built dist/RetroTele-audiotest.sis"
fi
# VoIP echo test (needs Nokia's VoIPAudioSrvc SISX on the phone too). Own
# package and ID range 0xE7A3D5E0-EF: RetroTorch already uses 0xE7A3D5C7.
if [ -f native/tgvoiptest.exe ]; then
  rm -rf build/voiptest && mkdir -p build/voiptest/sys/bin
  cp native/tgvoiptest.exe build/voiptest/sys/bin/
  $PY $ENS simplesis --uid=0xE7A3D5E1 --version=$VERSION --drive=C \
    --caption="RetroTele VoIP test" --vendor=RetroTele \
    --cert=cert/retrotele_cert.pem --privkey=cert/retrotele_key.pem \
    build/voiptest dist/RetroTele-voiptest.sis </dev/null >>build/simplesis.log
  echo "built dist/RetroTele-voiptest.sis"
fi
