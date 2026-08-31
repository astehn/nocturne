# -*- mode: python ; coding: utf-8 -*-
# Build:  .venv/bin/pyinstaller packaging/nocturne.spec --noconfirm
# NOTE: matplotlib must be BUNDLED (not excluded). astropy's WCS path (used by
#       plate-solve) lazily imports it via astropy.visualization; excluding it
#       left a half-present stub that raised "matplotlib.__spec__ is not set" at
#       solve time in the packaged app (worked from source where matplotlib is
#       installed). Keep it bundled so the import resolves cleanly.
import os
from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = os.path.dirname(SPECPATH)                 # repo root (SPECPATH = packaging/)
SCRIPT = os.path.join(SPECPATH, "nocturne_app.py")
ASSETS = os.path.join(ROOT, "nocturne", "assets")
ICON = os.path.join(SPECPATH, "nocturne.icns")

import re as _re
_init_src = open(os.path.join(ROOT, "nocturne", "__init__.py")).read()
_vm = _re.search(r'^__version__ = "([^"]+)"', _init_src, _re.M)
APP_VERSION = _vm.group(1) if _vm else "0.0.0"

datas = [(ASSETS, "nocturne/assets")]            # bundle icons/svg/splash/contributors
binaries = []
hiddenimports = ["PySide6.QtSvg"]                # SVG icon rendering

# certifi's cacert.pem must travel with the app. Without it the bundle falls
# back to the BUILD machine's compiled-in OpenSSL path
# (/opt/homebrew/etc/openssl@3/cert.pem), which is absent on a Mac with no
# Homebrew — every HTTPS call then fails CERTIFICATE_VERIFY_FAILED, silently,
# because the update check and the Gaia lookup both catch and return None.
for pkg in ("certifi", "skimage", "colour", "colour_demosaicing"):
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
    excludes=["tkinter", "PyQt5", "PyQt6"],   # matplotlib intentionally NOT excluded (see top-of-file note)
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
        "CFBundleShortVersionString": APP_VERSION,
        "CFBundleVersion": APP_VERSION,
        "NSHighResolutionCapable": True,
    },
)
