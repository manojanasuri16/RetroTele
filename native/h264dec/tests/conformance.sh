#!/bin/sh
# PC conformance test for h264dec: x264 streams shaped like a WebRTC / Android MediaCodec sender
# (High profile, no B-frames, low bitrate, 15 fps, SPS/PPS before every IDR), decoded by
# h264dec and by the system ffmpeg; the YUV output must be identical byte for byte.
# Needs ffmpeg and x264 on the PATH. Work files go to $OUT (default $TMPDIR/h264dec_conf).
#   sh tests/conformance.sh            all cases
#   ASAN=1 sh tests/conformance.sh     also build with AddressSanitizer for the fuzz cases
set -e
H=$(cd "$(dirname "$0")/.." && pwd)
W=${OUT:-${TMPDIR:-/tmp}/h264dec_conf}; mkdir -p "$W"
OUT="$W/host" sh "$H/host_build.sh" >/dev/null
T="$W/host/h264dec_test"
if [ "$ASAN" = 1 ]; then
  OUT="$W/asan" sh "$H/host_build.sh" -g -O1 -fsanitize=address,undefined -fno-sanitize=alignment,shift,signed-integer-overflow >/dev/null
  TF="$W/asan/h264dec_test"
else
  TF="$T"
fi
PASS=0; FAIL=0

# enc NAME SIZE SECONDS SOURCE X264-OPTIONS...
enc() {
  n=$1; s=$2; t=$3; src=$4; shift 4
  case $src in
    noise) f="testsrc2=s=$s:rate=15,noise=alls=12:allf=t" ;;
    zoom)  f="mandelbrot=s=$s:rate=15" ;;
    pan)   f="testsrc2=s=1280x1280:rate=15,crop=$(echo $s | tr x :):'(iw-ow)/2+200*sin(t)':'(ih-oh)/2+150*cos(t*0.7)',noise=alls=6:allf=t" ;;
  esac
  ffmpeg -v error -f lavfi -i "$f" -t "$t" -pix_fmt yuv420p -f yuv4mpegpipe - |
    x264 --quiet --demuxer y4m --fps 15 --bframes 0 "$@" -o "$W/$n.264" - 2>/dev/null
}

check() {   # NAME [h264dec options]
  n=$1; shift
  ffmpeg -v error -i "$W/$n.264" -f rawvideo -pix_fmt yuv420p -y "$W/$n.ref.yuv"
  if "$T" "$W/$n.264" "$W/$n.yuv" "$@" 2>"$W/$n.log" && cmp -s "$W/$n.yuv" "$W/$n.ref.yuv"; then
    PASS=$((PASS+1)); echo "PASS $n ($(tail -1 "$W/$n.log"))"
  else
    FAIL=$((FAIL+1)); echo "FAIL $n"; tail -3 "$W/$n.log"
  fi
}

HP="--profile high --8x8dct"
enc hp_cabac_176x320      176x320 4 noise $HP --level 3.1 --bitrate 150 --keyint 45 --ref 1
enc hp_cabac_ref3_352x640 352x640 4 pan   $HP --level 3.1 --bitrate 300 --keyint 60 --ref 3
enc hp_cavlc_240x480      240x480 4 noise $HP --level 2.2 --bitrate 200 --keyint 30 --ref 2 --no-cabac
enc hp_cavlc_176x320      176x320 3 pan   $HP --level 1.3 --bitrate 100 --keyint 30 --ref 1 --no-cabac
enc hp_slices4_176x320    176x320 3 noise $HP --level 1.3 --bitrate 150 --keyint 30 --slices 4
enc hp_slicemax_352x640   352x640 3 pan   $HP --level 3.1 --bitrate 300 --keyint 45 --slice-max-size 1000
enc hp_intrarefresh       176x320 4 pan   $HP --level 3.1 --bitrate 150 --keyint 30 --intra-refresh
enc hp_zerolatency_240x480 240x480 4 pan  $HP --level 3.1 --bitrate 200 --keyint 60 --tune zerolatency --ref 2
enc hp_528x960            528x960 2 pan   $HP --level 3.1 --bitrate 300 --keyint 30 --ref 2
enc hp_cqm_176x320        176x320 3 noise $HP --level 3.1 --bitrate 200 --keyint 30 --cqm jvt
enc hp_zoom_176x320       176x320 3 zoom  $HP --level 3.1 --bitrate 150 --keyint 30 --ref 3 --weightp 2
enc hp_lowqp_176x320      176x320 2 noise $HP --level 3.1 --qp 12 --keyint 15
enc main_cabac_176x320    176x320 3 pan   --profile main --level 3.1 --bitrate 150 --keyint 30
enc baseline_176x144      176x144 3 pan   --profile baseline --level 1.3 --bitrate 100 --keyint 30
enc hp_bframes_176x320    176x320 3 pan   $HP --level 3.1 --bitrate 150 --keyint 30 --bframes 2 --b-pyramid none
enc hp_gop_noscenecut     176x320 4 noise $HP --level 3.1 --bitrate 150 --keyint 30 --min-keyint 30 --no-scenecut
for n in hp_cabac_176x320 hp_cabac_ref3_352x640 hp_cavlc_240x480 hp_cavlc_176x320 hp_slices4_176x320 \
         hp_slicemax_352x640 hp_intrarefresh hp_zerolatency_240x480 hp_cqm_176x320 \
         hp_zoom_176x320 hp_lowqp_176x320 main_cabac_176x320 baseline_176x144; do
  check $n
done
check hp_528x960 -max 528 960
# B-frames are not expected from WebRTC; h264dec runs in low-delay mode, so only check that
# it decodes without errors
"$T" "$W/hp_bframes_176x320.264" "$W/hp_bframes.yuv" 2>"$W/hp_bframes.log" &&
  { PASS=$((PASS+1)); echo "PASS hp_bframes (decodes; low-delay output order not compared)"; } ||
  { FAIL=$((FAIL+1)); echo "FAIL hp_bframes"; }

# size changes mid-stream (new SPS + IDR each time), like the sender stepping down its quality
cat "$W/hp_cabac_ref3_352x640.264" "$W/hp_cavlc_240x480.264" "$W/hp_cabac_176x320.264" \
    "$W/hp_528x960.264" "$W/hp_slices4_176x320.264" > "$W/sizechange.264"
cat "$W/hp_cabac_ref3_352x640.ref.yuv" "$W/hp_cavlc_240x480.ref.yuv" "$W/hp_cabac_176x320.ref.yuv" \
    "$W/hp_528x960.ref.yuv" "$W/hp_slices4_176x320.ref.yuv" > "$W/sizechange.ref.yuv"
if "$T" "$W/sizechange.264" "$W/sizechange.yuv" -max 528 960 2>"$W/sizechange.log" &&
   cmp -s "$W/sizechange.yuv" "$W/sizechange.ref.yuv"; then
  PASS=$((PASS+1)); echo "PASS sizechange 352x640 -> 240x480 -> 176x320 -> 528x960 -> 176x320"
else
  FAIL=$((FAIL+1)); echo "FAIL sizechange"; tail -3 "$W/sizechange.log"
fi

# size limit: 528x960 refused with max 352x640 (error, no crash), smaller sizes still decode
"$T" "$W/sizechange.264" "$W/limit.yuv" -max 352 640 2>"$W/limit.log" || true
if grep -q "error -2" "$W/limit.log" && grep -q "176x320" "$W/limit.log"; then
  PASS=$((PASS+1)); echo "PASS size limit ($(grep -c 'error -2' "$W/limit.log") access units refused above 352x640)"
else
  FAIL=$((FAIL+1)); echo "FAIL size limit"; tail -3 "$W/limit.log"
fi

# joining late: the first 10 access units (P-frames, no SPS/PPS) are missing; the picture
# must start at the next IDR (frame 30) and match from there on
F=$((176*320*3/2))
ffmpeg -v error -i "$W/hp_gop_noscenecut.264" -f rawvideo -pix_fmt yuv420p -y "$W/late.full.yuv"
tail -c +$((30*F+1)) "$W/late.full.yuv" > "$W/late.ref.yuv"
if "$T" "$W/hp_gop_noscenecut.264" "$W/late.yuv" -start 10 2>"$W/late.log" &&
   cmp -s "$W/late.yuv" "$W/late.ref.yuv"; then
  PASS=$((PASS+1)); echo "PASS late join (P-frames before the first IDR ignored, then exact)"
else
  FAIL=$((FAIL+1)); echo "FAIL late join"; tail -3 "$W/late.log"
fi

# packet loss and corrupt data: must not crash and must keep producing pictures
for c in "-drop 5" "-drop 2" "-fuzz 1 2" "-fuzz 2 10" "-fuzz 3 50" "-fuzz 4 200"; do
  ok=1
  for n in hp_cabac_176x320 hp_cavlc_240x480 hp_slices4_176x320 sizechange; do
    if ! "$TF" "$W/$n.264" "$W/fz.yuv" -max 528 960 $c 2>"$W/fz.log"; then
      ok=0; echo "FAIL $n $c"; tail -3 "$W/fz.log"
    fi
  done
  if [ $ok = 1 ]; then PASS=$((PASS+1)); echo "PASS robustness $c ($(tail -1 "$W/fz.log"))"
  else FAIL=$((FAIL+1)); fi
done
echo "conformance: $PASS passed, $FAIL failed"
[ "$FAIL" = 0 ]
