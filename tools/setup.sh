#!/bin/sh
# Downloads everything needed to build and test RetroTele into ./tools
# (nothing is installed system-wide). Needs: curl, git, python3, openssl.
set -e
cd "$(dirname "$0")"
echo "== Private Python 2.7 (for Ensymble and the PC tests)"
if [ ! -x mamba/py27/bin/python2 ]; then
  mkdir -p mamba
  curl -sSfL -o mamba/micromamba.tar.bz2 https://micro.mamba.pm/api/micromamba/linux-64/latest
  (cd mamba && tar -xjf micromamba.tar.bz2 bin/micromamba)
  MAMBA_ROOT_PREFIX="$PWD/mamba/root" mamba/bin/micromamba create -y -q \
    -p "$PWD/mamba/py27" -c conda-forge python=2.7
fi

echo "== Ensymble (SIS packager), patched for current OpenSSL on Linux"
if [ ! -d ensymble/src ]; then
  mkdir -p ensymble
  git clone -q --depth 1 https://github.com/essaic/ensymble.git ensymble/src
  (cd ensymble/src && git apply ../../ensymble-retrosend.patch)
fi

echo "== Python for S60 1.4.5 runtime (Nokia-signed, from SourceForge)"
mkdir -p ../phone-installs
for f in PythonForS60_1_4_5_3rdEd.sis PythonScriptShell_1_4_5_3rdEd.SIS; do
  [ -f "../phone-installs/$f" ] || curl -sSfL -o "../phone-installs/$f" \
    "https://downloads.sourceforge.net/project/pys60/pys60/1.4.5/$f"
done
echo "== done"
