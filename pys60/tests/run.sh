#!/bin/sh
# Python 2.2 checks, then the PC tests with Python 2.7. LIVE=1 also talks to Telegram.
set -e
cd "$(dirname "$0")/.."
PY2=../tools/mamba/py27/bin/python2
for f in retrotele.py launcher.py tgcrypto.py tl.py mtproto.py tgclient.py tgsrp.py tgui.py callaudio.py fileinfo.py filepick.py; do
  python3 tools/check_py22.py "$f"
done
python3 tools/check_ints.py *.py
"$PY2" tests/test_crypto.py
"$PY2" tests/test_tl.py
"$PY2" tests/test_flow.py
if [ "$LIVE" = 1 ]; then
  "$PY2" -u tests/live_dh.py
  FUNC=help.getConfig "$PY2" -u tests/live_dh.py | tail -1 | cut -c1-200
fi
