#!/bin/sh
# Builds tgopus.lib (static) with the GnuPoc toolchain. See README.md.
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
S=${SYMBIAN_SDK:-$(cd "$HERE/../../.." && pwd)/symbian-sdk}
export EPOCROOT="$S/s60_32/"
export PATH="$S/gnupoc-bin:$S/csl-gcc/bin:$PATH"
# fetch the pristine Opus 1.3.1 source (BSD licence) when it isn't here
if [ ! -f "$HERE/src/include/opus.h" ]; then
  curl -sSfL -o "$HERE/opus-1.3.1.tar.gz" https://downloads.xiph.org/releases/opus/opus-1.3.1.tar.gz
  mkdir -p "$HERE/src" && tar xzf "$HERE/opus-1.3.1.tar.gz" -C "$HERE/src" --strip-components=1
  rm -f "$HERE/opus-1.3.1.tar.gz"
fi
cd "$HERE/group"
bldmake bldfiles >/dev/null 2>&1
abld build gcce urel > "$HERE/build.log" 2>&1 || true
grep -iE "error" "$HERE/build.log" || echo "no errors"
ls -la "$EPOCROOT"epoc32/release/*/urel/tgopus.lib
