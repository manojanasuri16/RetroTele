# Installing on the memory card

A Python for S60 1.4.5 app on a **different drive from Python itself** closes at
once, before any of its Python code runs: PyS60's app framework loads
`\resource\apps\appuifwmodule.rsc` from the **app's** drive, and Python for S60
installs that file only on its own drive.

So RetroTele's package ships a copy (`appuifwmodule.rsc` here, Python for S60
1.4.5's own file, Apache 2.0) in `\resource\retrotele\`, plus
`retrotele_rscfix.exe` (`native/rscfix/rscfix.cpp`), which the installer runs
once (`tools/py2sis_rscfix.py`) to copy it to `\resource\apps\` on the drive
RetroTele went to, if it's missing there.

Writing into `\resource` needs an unlocked phone (e.g. the Open4All patch). On a
phone that isn't unlocked, install RetroTele on the same drive as Python, or
copy `appuifwmodule.rsc` into `resource\apps\` on the app's drive by hand (USB
Mass storage). A `.sis` can't install it there: the phone says "Update error".

The fix comes from [RetroTorch](https://github.com/manojanasuri16/RetroTorch),
where it was found and tested on a Nokia N79.
