#!/bin/sh
# Host tests: python crosscheck vectors + C unit/sim tests (ASan/UBSan).
set -e
cd "$(dirname "$0")"
OUT=${TMPDIR:-/tmp}/call277_test.$$
mkdir -p "$OUT"
python3 -I tools/crosscheck.py > "$OUT/crosscheck.txt"
gcc -std=gnu89 -Wall -Wextra -O1 -g -fsanitize=address,undefined -fno-sanitize-recover=undefined \
    -o "$OUT/test_call277" test_call277.c c277_crypto.c c277_msg.c c277_conn.c c277_refl.c c277_stun.c
"$OUT/test_call277" "$OUT/crosscheck.txt"
rm -rf "$OUT"
