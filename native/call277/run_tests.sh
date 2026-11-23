#!/bin/sh
# Host tests: python crosscheck vectors + C unit/sim tests (ASan/UBSan).
# fixtures/ (a real call capture) is git-ignored; capture tests skip when it is absent.
set -e
cd "$(dirname "$0")"
OUT=${TMPDIR:-/tmp}/call277_test.$$
mkdir -p "$OUT"
python3 -I tools/crosscheck.py > "$OUT/crosscheck.txt"
CF="-std=gnu89 -Wall -Wextra -O1 -g -fsanitize=address,undefined -fno-sanitize-recover=undefined"
LIB="c277_crypto.c c277_msg.c c277_conn.c c277_refl.c c277_stun.c c277_ice.c c277_rtp.c c277_video.c c277_session.c"
gcc $CF -o "$OUT/test_call277" test_call277.c $LIB
gcc $CF -o "$OUT/test_session" test_session.c $LIB
gcc $CF -o "$OUT/test_video" test_video.c c277_video.c c277_rtp.c c277_crypto.c
gcc $CF -o "$OUT/test_agc" test_agc.c c277_agc.c
"$OUT/test_call277" "$OUT/crosscheck.txt"
"$OUT/test_session" "$OUT/crosscheck.txt"
"$OUT/test_video"
"$OUT/test_agc" | tail -1
rm -rf "$OUT"
