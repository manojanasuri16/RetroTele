# sisinfo.py: lists what a SIS (Symbian 9) package contains: the package and every embedded
# package (UID, name, vendor, version, dependencies, number of files, signatures).
# Python 2 (uses Ensymble's SIS parser):  tools/mamba/py27/bin/python2 tools/sisinfo.py X.sis
import sys
import os
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "ensymble", "src", "ensymble"))
from utils import sisfield


def text(s):
    try:
        return s.String.encode("utf-8")
    except Exception:
        return "?"


def ver(v):
    return "%d.%d.%d" % (v.Major, v.Minor, v.Build)


def show(c, depth):
    pad = "  " * depth
    info = c.Info
    names = [text(n) for n in info.Names]
    print "%spackage 0x%08x %s by %s, version %s, %d file(s), %d signature(s)" % (
        pad, info.UID.UID1, " / ".join(names), text(info.VendorUniqueName), ver(info.Version),
        len(c.InstallBlock.Files), len(c.getsignatures()))
    for d in c.Prerequisites.Dependencies:
        vr = getattr(d, "VersionRange", None)
        rng = ""
        if vr is not None:
            rng = " from %s" % ver(vr.FromVersion)
        print "%s  depends on 0x%08x%s (%s)" % (pad, d.UID.UID1, rng,
                                              ", ".join([text(n) for n in d.DependencyNames]))
    for e in c.InstallBlock.EmbeddedSISFiles:
        show(e, depth + 1)


def main(path):
    data = open(path, "rb").read()
    sf, n = sisfield.SISField(data[16:], False)
    print "%s: %d bytes, %d data unit(s)" % (path, len(data), len(sf.Data.DataUnits))
    show(sf.Controller.Data, 1)


if __name__ == "__main__":
    for p in sys.argv[1:]:
        main(p)
