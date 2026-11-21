#!/bin/sh
# Builds a Symbian (S60 3rd Edition) cross toolchain on Linux, no Docker:
#   GCC 14.2 + binutils 2.29.1 for arm-none-symbianelf, GnuPoc tools
#   (elf2e32, makesis, ...), the S60 3rd Edition FP1 SDK and the PyS60 1.4.5
#   SDK (Python headers and import library).
# Recipe from github.com/RuhanSA079/SymbianApps (env/build-gcce.sh) and
# github.com/mstorsjo/gnupoc-package. Everything goes to $TOP (default
# ../../symbian next to the repo). Steps are skipped when already done.
set -e
TOP=${TOP:-$(cd "$(dirname "$0")/../.." && pwd)/symbian}
JOBS=${JOBS:-$(nproc)}
GNU=${GNU_MIRROR:-https://mirrors.kernel.org/gnu}
TARGET=arm-none-symbianelf
mkdir -p "$TOP/dl" "$TOP/build"
cd "$TOP"

fetch() {
  [ -s "dl/$2" ] && return 0
  n=0
  # resume when the server allows it; archive.org files inside zips don't,
  # then start over
  until curl -sSfL --http1.1 --retry 5 -C - -o "dl/$2.tmp" "$1" ||
        { rm -f "dl/$2.tmp"; curl -sSfL --http1.1 --retry 5 -o "dl/$2.tmp" "$1"; }; do
    n=$((n + 1)); [ $n -ge 12 ] && { echo "download failed: $1"; exit 1; }
    rm -f "dl/$2.tmp"
    sleep 10
  done
  mv "dl/$2.tmp" "dl/$2"
}
echo "== downloads"
fetch "$GNU/binutils/binutils-2.29.1.tar.xz" binutils-2.29.1.tar.xz
fetch "$GNU/gcc/gcc-14.2.0/gcc-14.2.0.tar.xz" gcc-14.2.0.tar.xz
if [ "$SDKS" = 1 ]; then
  fetch "https://downloads.sourceforge.net/project/pys60/pys60/1.4.5/PythonForS60_1_4_5_SDK_3rdEd.zip" PythonForS60_1_4_5_SDK_3rdEd.zip
  fetch "https://archive.org/download/symbian_dev/SDK_S60.zip/SDK_S60%2Fs60v3.1_SDK.zip" s60v3.1_SDK.zip
  ls -la dl
  exit 0
fi
ls -la dl

PREFIX="$TOP/gcc"
if [ ! -x "$PREFIX/bin/$TARGET-gcc" ]; then
 if [ ! -x "$PREFIX/bin/$TARGET-as" ]; then
  echo "== binutils"
  cd "$TOP/build"
  [ -d binutils-2.29.1 ] || tar xJf ../dl/binutils-2.29.1.tar.xz
  mkdir -p b-binutils && cd b-binutils
  ../binutils-2.29.1/configure --target=$TARGET --prefix="$PREFIX" \
    --disable-nls --disable-shared --disable-werror --disable-gdb >configure.log 2>&1
  make -j"$JOBS" MAKEINFO=true >make.log 2>&1
  make install-strip MAKEINFO=true >install.log 2>&1
 fi
  echo "== gcc"
  cd "$TOP/build"
  [ -d gcc-14.2.0 ] || tar xJf ../dl/gcc-14.2.0.tar.xz
  (cd gcc-14.2.0 && [ -d gmp ] || ./contrib/download_prerequisites >/dev/null)
  # the symbianelf target lacks the stdint type macros
  grep -q 'arm/symbian.h newlib-stdint.h' gcc-14.2.0/gcc/config.gcc ||
    sed -i 's|tm_file="${tm_file} arm/symbian.h"|tm_file="${tm_file} arm/symbian.h newlib-stdint.h"|' \
      gcc-14.2.0/gcc/config.gcc
  grep -n 'arm/symbian.h' gcc-14.2.0/gcc/config.gcc
  mkdir -p "$PREFIX/$TARGET/sys-include"
  printf '#ifndef _STDIO_H\n#define _STDIO_H\n#endif\n' > "$PREFIX/$TARGET/sys-include/stdio.h"
  cp gcc-14.2.0/gcc/ginclude/stdint-gcc.h "$PREFIX/$TARGET/sys-include/stdint.h"
  rm -rf b-gcc && mkdir -p b-gcc && cd b-gcc
  # today's host compilers default to newer C/C++ dialects than GCC 14 expects
  CC="gcc -std=gnu17" CXX="g++ -std=gnu++17" \
  PATH="$PREFIX/bin:$PATH" ../gcc-14.2.0/configure --target=$TARGET --prefix="$PREFIX" \
    --enable-languages=c,c++ --without-headers --with-newlib \
    --disable-hosted-libstdcxx --disable-libstdcxx-pch --disable-nls --disable-shared \
    --disable-multilib --disable-threads --disable-libssp --disable-libgomp \
    --disable-libquadmath --disable-libatomic \
    --with-arch=armv5t --with-float=soft --with-pkgversion="RetroTele GCCE" >configure.log 2>&1
  PATH="$PREFIX/bin:$PATH" make -j"$JOBS" all-gcc all-target-libgcc MAKEINFO=true >make.log 2>&1
  PATH="$PREFIX/bin:$PATH" make install-strip-gcc install-strip-target-libgcc MAKEINFO=true >install.log 2>&1
fi
"$PREFIX/bin/$TARGET-gcc" --version | head -1

echo "== gnupoc"
cd "$TOP"
if [ ! -d gnupoc-package ]; then
  git clone -q https://github.com/mstorsjo/gnupoc-package.git
  (cd gnupoc-package && git checkout -q d3ddaf58c734ad3ab34dc60a012f9d4768a9ed3e)
fi
echo "== done (tools and SDK install are the next steps)"
