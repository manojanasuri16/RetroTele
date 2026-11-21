#!/usr/bin/env python3
"""PC helper for RetroTele's two-step verification login.

The phone needs a slow password hash (100000 rounds of PBKDF2-SHA512), which
takes about an hour in Python on an N79. This computes it in a second:

  1. In RetroTele choose "Use hash from PC helper": it writes
     RetroTele/2fa_salts.txt to the memory card.
  2. Connect the phone (mass storage) and run:
        python3 tg2fa.py /run/media/$USER/<card>/RetroTele
  3. Type your Telegram password. 2fa_hash.txt is written next to the salts;
     the password itself is never stored.
  4. On the phone select Continue. The hash file is deleted after use.
"""
import getpass
import hashlib
import os
import sys


def sh(data, salt):
    return hashlib.sha256(salt + data + salt).digest()


def main():
    folder = sys.argv[1] if len(sys.argv) > 1 else "."
    salts = {}
    with open(os.path.join(folder, "2fa_salts.txt")) as f:
        for line in f:
            if "=" in line:
                k, v = line.strip().split("=", 1)
                salts[k] = bytes.fromhex(v)
    s1, s2 = salts["salt1"], salts["salt2"]
    pw = getpass.getpass("Telegram two-step verification password: ").encode("utf-8")
    x = sh(hashlib.pbkdf2_hmac("sha512", sh(sh(pw, s1), s2), s1, 100000), s2)
    out = os.path.join(folder, "2fa_hash.txt")
    with open(out, "w") as f:
        f.write(x.hex() + "\n")
    print("wrote", out, "- now select Continue in RetroTele")


if __name__ == "__main__":
    main()
