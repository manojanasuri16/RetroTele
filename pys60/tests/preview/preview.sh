#!/bin/sh
# Renders RetroTele's screens to PNGs (needs python3 + Pillow and Noto Sans).
#   sh tests/preview/preview.sh [out_dir]
set -e
cd "$(dirname "$0")"
OUT=${1:-/tmp/retrotele-preview}
mkdir -p "$OUT"
python3 widths.py "$OUT/widths.json"
python3 -c "
from PIL import Image, ImageDraw
im = Image.new('RGB', (320, 240), (40, 60, 90)); d = ImageDraw.Draw(im)
d.rectangle([100, 30, 220, 210], fill=(25, 25, 30)); d.rectangle([110, 45, 210, 130], fill=(120, 190, 240))
for i in range(12): d.ellipse([118 + (i % 3) * 30, 140 + (i // 3) * 16, 132 + (i % 3) * 30, 152 + (i // 3) * 16], fill=(200, 200, 205))
im.save('$OUT/sample.jpg', quality=85)"
RT_PHOTO="$OUT/sample.jpg" RT_WIDTHS="$OUT/widths.json" RT_OUT="$OUT" ../../../tools/mamba/py27/bin/python2 preview.py
python3 render.py "$OUT/screens.json" "$OUT"
