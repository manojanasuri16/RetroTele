#!/bin/sh
# Compiles native/tgnative into pys60/native/tgnative.pyd, and native/rscfix
# into pys60/native/retrotele_rscfix.exe, with a GnuPoc
# Symbian toolchain for S60 3rd Edition FP2 (CodeSourcery GCCE 3.4.3,
# S60 3.2 SDK, PyS60 1.4.5 SDK plugin). SYMBIAN_SDK points at that setup
# (default: ../../symbian-sdk next to the repo).
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
S=${SYMBIAN_SDK:-$(cd "$HERE/../.." && pwd)/symbian-sdk}
export EPOCROOT="$S/s60_32/"
export PATH="$S/gnupoc-bin:$S/csl-gcc/bin:$PATH"
cd "$HERE/tgnative/group"
bldmake bldfiles >/dev/null 2>&1
abld build gcce urel 2>&1 | grep -iE "error" || true
OUT="$EPOCROOT/epoc32/release/gcce/urel/tgnative.pyd"
[ -f "$OUT" ] || { echo "build failed"; exit 1; }
mkdir -p "$HERE/../pys60/native"
cp "$OUT" "$HERE/../pys60/native/tgnative.pyd"
ls -la "$HERE/../pys60/native/tgnative.pyd"

# retrotele_rscfix.exe: run by the installer (see pys60/rscfix/README.md)
cd "$HERE/rscfix/group"
bldmake bldfiles >/dev/null 2>&1
abld build gcce urel 2>&1 | grep -iE "error" || true
OUT="$EPOCROOT/epoc32/release/gcce/urel/retrotele_rscfix.exe"
[ -f "$OUT" ] || { echo "rscfix build failed"; exit 1; }
cp "$OUT" "$HERE/../pys60/native/retrotele_rscfix.exe"
ls -la "$HERE/../pys60/native/retrotele_rscfix.exe"

# tgcall.pyd: live audio for the call experiments (Settings > Call test)
cd "$HERE/tgcall/group"
bldmake bldfiles >/dev/null 2>&1
abld build gcce urel 2>&1 | grep -iE "error" || true
OUT="$EPOCROOT/epoc32/release/gcce/urel/tgcall.pyd"
[ -f "$OUT" ] || { echo "tgcall build failed"; exit 1; }
cp "$OUT" "$HERE/../pys60/native/tgcall.pyd"
ls -la "$HERE/../pys60/native/tgcall.pyd"
