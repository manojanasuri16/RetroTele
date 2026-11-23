#!/bin/sh
# Builds h264dec.lib (static library) and tgh264bench.exe (benchmark) with the GnuPoc toolchain
# and copies the benchmark to pys60/native/. The bench clips are generated on the PC
# (ffmpeg + x264, tests/make_bench_clips.sh) into bench/gen/ (git-ignored) when missing.
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
S=${SYMBIAN_SDK:-$(cd "$HERE/../../.." && pwd)/symbian-sdk}
export EPOCROOT="$S/s60_32/"
export PATH="$S/gnupoc-bin:$S/csl-gcc/bin:$PATH"
if [ ! -f "$HERE/bench/gen/h264bench_clips.h" ]; then
  sh "$HERE/tests/make_bench_clips.sh" >/dev/null 2>&1 || echo "h264bench clips not generated (needs ffmpeg, x264)"
fi
cd "$HERE/group"
bldmake bldfiles >/dev/null 2>&1
abld build gcce urel > "$HERE/build.log" 2>&1 || true
# abld exits 0 on errors: look for them (file names like error_resilience.c are not errors)
grep -iE "error:|\*\*\* |undefined reference" "$HERE/build.log" || echo "h264dec: no errors"
ls -la "$EPOCROOT"epoc32/release/armv5/urel/h264dec.lib
OUT="$EPOCROOT/epoc32/release/gcce/urel/tgh264bench.exe"
if [ -f "$OUT" ]; then
  cp "$OUT" "$HERE/../../pys60/native/tgh264bench.exe"
  ls -la "$HERE/../../pys60/native/tgh264bench.exe"
fi
