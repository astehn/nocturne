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

def _prune(entries):
    """Drop what the app can never use from a collected package.

    Measured on the 0.23.0 build, 2026-09-02: a 491 MB app carrying 231 MB of
    dead weight.

      * `colour/htmlcov` — 609 HTML pages, 78 MB, of the colour-science
        project's own TEST COVERAGE REPORT. It ships inside the installed
        package and collect_all() takes everything.
      * `edsr_x2.onnx` — 153 MB, the super-resolution model dropped on
        2026-09-01. onnxruntime is excluded below, so nothing in the app can
        load it; it rides along only because the assets sweep is a whole
        directory and the file happens to sit on the build machine.

    Anything matched here must be genuinely unreachable — this list is a
    guarantee about the app, not a size target.
    """
    drop = ("/htmlcov/", "/edsr_", "/tests/", "/.pytest_cache/")
    kept = []
    for entry in entries:
        dest = str(entry[0]).replace("\\", "/")
        src = str(entry[1]).replace("\\", "/")
        if any(d in f"/{dest}/" or d in src for d in drop):
            continue
        kept.append(entry)
    return kept


def _assets():
    """Every asset file, named individually rather than sweeping the directory.

    `[(ASSETS, "nocturne/assets")]` handed PyInstaller a DIRECTORY, which it
    expands at build time — so anything sitting in assets/ on the build machine
    shipped, whether the app could use it or not. That is how 153 MB of
    edsr_x2.onnx reached a 491 MB bundle: the model was dropped on 2026-09-01
    and onnxruntime excluded, so nothing in the app can load it.

    Naming the files also means a NEW asset has to be added here deliberately,
    which is the safer failure: a missing asset breaks loudly at startup,
    while an unnoticed 150 MB one just makes the download slower.
    """
    out = []
    for root, _dirs, files in os.walk(ASSETS):
        for name in files:
            if name.startswith("."):
                continue
            full = os.path.join(root, name)
            rel = os.path.relpath(root, ASSETS)
            dest = "nocturne/assets" if rel == "." else f"nocturne/assets/{rel}"
            out.append((full, dest))
    return _prune(out)


datas = _assets()                                # icons/svg/splash/fonts/our model
binaries = []
hiddenimports = ["PySide6.QtSvg"]                # SVG icon rendering

# certifi's cacert.pem must travel with the app. Without it the bundle falls
# back to the BUILD machine's compiled-in OpenSSL path
# (/opt/homebrew/etc/openssl@3/cert.pem), which is absent on a Mac with no
# Homebrew — every HTTPS call then fails CERTIFICATE_VERIFY_FAILED, silently,
# because the update check and the Gaia lookup both catch and return None.
for pkg in ("certifi", "drizzle", "skimage", "colour", "colour_demosaicing"):
    d, b, h = collect_all(pkg)
    datas += _prune(d)
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
    # onnxruntime is 64 MB and is NOT a runtime dependency — pyproject lists it
    # only under the `train` extra. PyInstaller bundles it because it statically
    # sees `import onnxruntime` inside a function in core/denoise_model.py, and
    # AI Denoise is deliberately not shipped (see ui/pipeline.py). Every user
    # was downloading, and every launch loading, an inference runtime for a step
    # they cannot open. REMOVE THIS EXCLUDE the day AI Denoise ships.
    excludes=["tkinter", "PyQt5", "PyQt6", "onnxruntime",
              "onnx", "torch"],   # matplotlib intentionally NOT excluded (see top-of-file note)
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
