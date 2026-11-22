# tgopus: Opus 1.3.1 for Nokia N79 (Symbian S60 3rd FP2, GCCE 3.4.3)

Opus (c) Xiph.Org, Skype Limited, Octasic, Jean-Marc Valin, Timothy B. Terriberry,
CSIRO, Microsoft, Broadcom, Mozilla: BSD 3-clause license, see src/COPYING.

Layout: src/ = pristine opus-1.3.1 (untouched, no patches needed), config/config.h,
group/{bld.inf,opus.mmp}, bench/tgopus_bench.{c,h}, sources.txt (source list used by
host_test.sh), build_opus.sh (Symbian build), host_test.sh (x86 test).

Config: FIXED_POINT, DISABLE_FLOAT_API, OPUS_BUILD, HAVE_CONFIG_H, VAR_ARRAYS (GCC 3.4
supports C99 VLAs in default gnu89 mode; no global stack arena => thread safe, no
writable globals). Do NOT pass -std=gnu99: it makes opus_types.h pick <stdint.h>,
which estlib lacks; default mode hits the __SYMBIAN32__ typedef branch.
No assembly, no RTCD, no SIMD. Output: epoc32/release/armv5/urel/tgopus.lib
