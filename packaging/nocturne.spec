# -*- mode: python ; coding: utf-8 -*-
# Build:  .venv/bin/pyinstaller packaging/nocturne.spec --noconfirm
# NOTE: matplotlib must be pip-installed at BUILD time (astropy's PyInstaller hook
#       imports astropy.visualization.wcsaxes, which importorskip's matplotlib).
#       It is excluded from the bundle below — the app only uses astropy.io.fits.
import os
from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = os.path.dirname(SPECPATH)                 # repo root (SPECPATH = packaging/)
SCRIPT = os.path.join(SPECPATH, "nocturne_app.py")
ASSETS = os.path.join(ROOT, "nocturne", "assets")
ICON = os.path.join(SPECPATH, "nocturne.icns")

datas = [(ASSETS, "nocturne/assets")]            # bundle icons/svg/splash/contributors
binaries = []
hiddenimports = ["PySide6.QtSvg"]                # SVG icon rendering

for pkg in ("skimage", "colour", "colour_demosaicing"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h
hiddenimports += collect_submodules("astroalign")
hiddenimports += collect_submodules("astropy.wcs") + collect_submodules("astropy.coordinates")
datas += [(os.path.join(ROOT, "nocturne", "data", "openngc.csv"), "nocturne/data")]
datas += [(os.path.join(ROOT, "nocturne", "data", "named_stars.csv"), "nocturne/data")]

a = Analysis(
    [SCRIPT],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["matplotlib", "tkinter", "PyQt5", "PyQt6"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Nocturne",
          console=False, argv_emulation=True)
coll = COLLECT(exe, a.binaries, a.datas, name="Nocturne")
app = BUNDLE(
    coll,
    name="Nocturne.app",
    icon=ICON,
    bundle_identifier="com.nocturne.app",
    info_plist={
        "CFBundleName": "Nocturne",
        "CFBundleDisplayName": "Nocturne",
        "CFBundleShortVersionString": "0.2.0",
        "CFBundleVersion": "0.2.0",
        "NSHighResolutionCapable": True,
    },
)
