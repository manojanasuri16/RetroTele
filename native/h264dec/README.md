# h264dec: software H.264 decoder for the N79 (peer video in calls)

The official Telegram apps send H.264 **High** profile (CABAC, 8x8 transform) at 528x960 down
to 176x320; the N79's decoders only take Baseline. h264dec is FFmpeg 0.6.7's H.264 decoder
(C only, LGPL 2.1, see `../third_party/ffmpeg-0.6.7/NOTICE`) behind a small C API, built as a
static library for GCCE 3.4.3 and for the PC.

API (`h264dec.h`): `h264dec_create(max_w, max_h)`, `h264dec_decode(d, annexb_au, len, &frame)`
(returns `H264DEC_FRAME` with Y/U/V planes, strides, visible size, key/errors/profile/level),
`h264dec_reset`, `h264dec_stats`, `h264dec_destroy`, optional `h264dec_set_log`. One decoder
per thread; per-decoder state lives in the context. Pictures larger than max_w x max_h (by
area and longer side) are refused with `H264DEC_ERR_TOOBIG` before anything is allocated.
Low-delay output (no reordering wait). Symbian caps user thread stacks at 80 KB (a bigger
request fails with KErrTooBig, -40): start the decode thread with `symbian/h264dec_thread.h`
(`H264DecCreateThread`: 80, 64, then 32 KB, shared heap), as tgh264bench.exe does.

Process-wide state: FFmpeg's read-only-after-init tables (VLC tables, clip table; about 47 KB
of bss) filled by the first `h264dec_create()`. Fine in an EXE (tgvideo.exe, the bench); a DLL
would need EPOCALLOWDLLDATA.

Layout: `h264dec.h`, `src/h264dec.c` (API), `src/h264dec_compat.c` (vsnprintf/snprintf/tempnam
that estlib lacks), `config/config.h` (FFmpeg config: H.264 decoder only, no asm),
`config/symbian/{stdint,inttypes}.h` (estlib has none), `sources.txt` (compiled FFmpeg files),
`group/` (h264dec.lib + tgh264bench.exe), `bench/h264bench.cpp`, `tests/`.

Build: `sh build_h264dec.sh` (also run by `../build_native.sh`): GCCE `-O2 -mcpu=arm1136j-s`.
PC: `sh host_build.sh` builds `h264dec_test`; `sh tests/conformance.sh` encodes x264 streams
like a WebRTC sender and compares the output with the system ffmpeg byte for byte
(`ASAN=1` for an AddressSanitizer build of the robustness cases).

Benchmark: `tests/make_bench_clips.sh` generates `bench/gen/h264bench_clips.h` (x264 clips +
the PC's per-picture checksums; git-ignored), `tgh264bench.exe` (UID 0xE7A3D5EC) in
`RetroTele-h264bench.sis` (wrapper app 0xE7A3D5ED, built by `pys60/build_sis.sh`) decodes them on
the phone and writes `E:\retrotele_h264bench.txt`.
