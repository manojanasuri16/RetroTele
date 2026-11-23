#!/bin/sh
# Host (x86) build of h264dec + the test tool, same sources and config as the N79 build.
#   sh host_build.sh [extra CFLAGS...]   -> $OUT/h264dec_test (OUT defaults to $TMPDIR/h264dec_host)
set -e
H=$(cd "$(dirname "$0")" && pwd)
FF="$H/../third_party/ffmpeg-0.6.7"
O=${OUT:-${TMPDIR:-/tmp}/h264dec_host}; mkdir -p "$O/obj"
CF="-O2 -std=gnu99 -w -fno-strict-aliasing -DHAVE_AV_CONFIG_H -DH264DEC_HOOKS -I$H/config/catch -I$H/config -I$FF -I$H $*"
CF="$CF -Wno-error=incompatible-pointer-types -Wno-error=int-conversion -Wno-error=implicit-function-declaration"
OBJS=""
for s in $(cat "$H/sources.txt"); do
  o="$O/obj/$(echo "$s" | tr / _ | sed 's/\.c$/.o/')"
  gcc $CF -c "$FF/$s" -o "$o"
  OBJS="$OBJS $o"
done
gcc $CF -c "$H/src/h264dec.c" -o "$O/obj/h264dec.o"
gcc $CF "$H/tests/h264dec_test.c" "$O/obj/h264dec.o" $OBJS -lm -o "$O/h264dec_test"
echo "$O/h264dec_test"
