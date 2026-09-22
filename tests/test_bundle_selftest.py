"""The checks the BUILT app runs on itself.

Two bugs of the same shape have now shipped: a certificate path baked in at
build time (v0.18.0-v0.20.0, HTTPS dead for every user) and imagecodecs'
dynamically imported codecs (v0.35.0-v0.39.0, star separation dead for every
user without RC-Astro). Both were correct from source, broken only in the
bundle, and invisible on the machine that built them. The only instrument that
can see either is the artifact being asked about itself, which is what
`--check-network` and `--check-codecs` are.
"""
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent


def _run(*args):
    return subprocess.run([sys.executable, "-m", "nocturne", *args],
                          capture_output=True, text=True, cwd=ROOT, timeout=180)


def test_the_codec_check_passes_from_source():
    r = _run("--check-codecs")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "codecs        : OK" in r.stdout


def test_the_codec_check_fails_when_the_codec_module_is_missing(tmp_path):
    """Teeth. A bundle hides `imagecodecs._imcd` while leaving the package
    importable, so this reproduces that exact shape rather than removing the
    dependency — which any check would notice."""
    probe = tmp_path / "hide_imcd.py"
    probe.write_text(
        "import sys, importlib.abc\n"
        "class B(importlib.abc.MetaPathFinder):\n"
        "    def find_spec(self, name, path=None, target=None):\n"
        "        if name == 'imagecodecs._imcd':\n"
        "            raise ImportError('hidden for the teeth check')\n"
        "sys.meta_path.insert(0, B())\n"
        f"sys.path.insert(0, {str(ROOT)!r})\n"
        "sys.argv = ['nocturne', '--check-codecs']\n"
        "import runpy; runpy.run_module('nocturne', run_name='__main__')\n")
    r = subprocess.run([sys.executable, str(probe)], capture_output=True,
                       text=True, timeout=180)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "lzw" in r.stdout and "FAILED" in r.stdout


def test_the_check_returns_before_a_window_is_created():
    """It has to work headless on a build machine and in CI. Anything dispatched
    below `QApplication(sys.argv)` would try to open a display."""
    src = (ROOT / "nocturne" / "__main__.py").read_text()
    body = src.split("def main()")[1]
    assert body.index('"--check-codecs" in sys.argv') < body.index("QApplication(sys.argv)")


@pytest.mark.parametrize("codec", ["lzw", "deflate", "packbits"])
def test_every_compression_the_app_can_meet_is_checked(codec):
    """LZW is what StarNet2 writes; deflate and packbits are what a user's own
    TIFF arrives in. Dropping one from the list is how a codec goes back to
    being discovered by a user."""
    from nocturne.__main__ import _TIFF_CODECS
    assert codec in dict(_TIFF_CODECS)


def test_the_lzw_check_uses_the_predictor_starnet2_actually_writes():
    """A real StarNet2 output read on 2026-09-22 is LZW WITH predictor=2, and
    tifffile undoes that through a separate imagecodecs entry point. Plain LZW
    would pass on a build that still could not open the file the tool writes —
    the same blind spot that let this ship."""
    from nocturne.__main__ import _TIFF_CODECS
    assert dict(_TIFF_CODECS)["lzw"] is True


def test_the_probe_image_is_not_uniform():
    """A constant array survives a codec that silently falls back to raw bytes,
    so it cannot tell a working decoder from an absent one."""
    src = (ROOT / "nocturne" / "__main__.py").read_text()
    body = src.split("def _check_codecs")[1].split("def ")[0]
    assert "np.arange" in body, "the probe image must vary across pixels"


# --- how a NEW dependency avoids repeating this (2026-09-22) ----------------

def _third_party_imports():
    """Every non-stdlib top-level package the app imports anywhere."""
    import ast
    import sys
    names = set()
    for f in (ROOT / "nocturne").rglob("*.py"):
        tree = ast.parse(f.read_text())
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                names |= {a.name.split(".")[0] for a in n.names}
            elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
                names.add(n.module.split(".")[0])
    return {n for n in names
            if n not in sys.stdlib_module_names and n != "nocturne"}


def _risky(name):
    """Whether a package can ship half-present without anyone noticing.

    Two properties make it possible, and imagecodecs has both: code loaded
    through importlib, which static analysis cannot follow, and many compiled
    extension modules, so the package imports while the piece you need is
    absent. A single-module package like `sep` is resolved statically and either
    ships or does not; `tifffile` is one .py file with neither property.
    """
    import importlib.util
    import re as _re
    try:
        spec = importlib.util.find_spec(name)
    except (ImportError, ValueError):               # pragma: no cover
        return False
    if spec is None or not spec.submodule_search_locations:
        return False                              # a lone module, not a package
    d = Path(list(spec.submodule_search_locations)[0])
    dyn = exts = 0
    for f in d.rglob("*"):
        if f.suffix == ".py":
            dyn += len(_re.findall(r"importlib\.import_module\(|__import__\(",
                                   f.read_text(errors="ignore")))
        elif f.suffix in (".so", ".pyd", ".dylib"):
            exts += 1
    return dyn > 0 and exts > 1


def test_every_dependency_that_can_ship_half_present_is_hooked_or_collected():
    """The structural guard, not the one-codec fix.

    imagecodecs was the ONE such dependency PyInstaller had no hook for and the
    spec did not collect — so it shipped with one of its sixty extension
    modules and four releases had a broken star separation. Surveyed
    2026-09-22: PIL, numpy, scipy and astropy import dynamically too and are
    each covered by a PyInstaller hook; skimage and colour are collected here.
    A new dependency of the same shape that is neither is the next imagecodecs,
    and it will look perfectly healthy from source.

    Failing this is not a bug in the test. Add the package to the spec's
    collect_all list, or establish that a hook covers it.
    """
    import PyInstaller.hooks as _builtin
    hook_dirs = [Path(_builtin.__file__).parent]
    try:
        import _pyinstaller_hooks_contrib.stdhooks as _contrib
        hook_dirs.append(Path(_contrib.__file__).parent)
    except ImportError:                             # pragma: no cover
        pass
    hooked = {p.name[len("hook-"):-len(".py")].split(".")[0]
              for d in hook_dirs for p in d.glob("hook-*.py")}

    spec = (ROOT / "packaging" / "nocturne.spec").read_text()
    named = set(re.findall(r'"([A-Za-z_][\w.]*)"', spec))

    unguarded = sorted(n for n in _third_party_imports()
                       if _risky(n) and n not in hooked and n not in named)
    assert not unguarded, (
        "these load code dynamically AND carry several extension modules, but "
        "are neither hooked by PyInstaller nor named in the spec: "
        f"{unguarded}. Each can ship half-present and fail only on a user's "
        "machine, after the work is already done — see imagecodecs.")


def test_the_dependency_guard_would_have_caught_imagecodecs():
    """Teeth. The survey above is only worth running if it recognises the
    package that actually shipped broken."""
    assert _risky("imagecodecs"), \
        "the guard no longer sees imagecodecs as capable of shipping half-present"
