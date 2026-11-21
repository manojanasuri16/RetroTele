#!/bin/sh
# Builds the native S60 3rd Edition app: dist/RetroTele.sis
# (needs Python for S60 1.4.5 on the phone). Run ../tools/setup.sh once first.
# Installs to phone memory or the memory card (the phone asks).
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

$PY $ENS py2sis --uid=0xE7A3D5C2 --appname=RetroTele --version=$VERSION \
  --caption=RetroTele --shortcaption=RetroTele --vendor=RetroTele --icon=icon.svg \
  --caps=NetworkServices+LocalServices+ReadUserData+WriteUserData+UserEnvironment \
  --heapsize=4k,24M --cert=cert/retrotele_cert.pem --privkey=cert/retrotele_key.pem \
  $EXTRAS build/app dist/RetroTele.sis </dev/null >build/py2sis.log
echo "built dist/RetroTele.sis"
ls -la dist
