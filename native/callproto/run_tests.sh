#!/bin/sh
# Host tests: python crosscheck vectors + C unit/sim tests.
set -e
cd "$(dirname "$0")"
OUT=${TMPDIR:-/tmp}/callproto_test.$$
mkdir -p "$OUT"
python3 -I tools/crosscheck.py > "$OUT/crosscheck.txt"
gcc -std=gnu89 -Wall -Wextra -O1 -g -fsanitize=address,undefined -o "$OUT/test_callproto" \
    test_callproto.c callproto.c callproto_crypto.c
"$OUT/test_callproto" "$OUT/crosscheck.txt"
rm -rf "$OUT"
