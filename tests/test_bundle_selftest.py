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
        "import runpy; runpy.run_module('nocturne', run_name='__main__')\n", encoding="utf-8")
    r = subprocess.run([sys.executable, str(probe)], capture_output=True,
                       text=True, timeout=180)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "lzw" in r.stdout and "FAILED" in r.stdout


def test_the_check_returns_before_a_window_is_created():
    """It has to work headless on a build machine and in CI. Anything dispatched
    below `QApplication(sys.argv)` would try to open a display."""
    src = (ROOT / "nocturne" / "__main__.py").read_text(encoding="utf-8")
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
    src = (ROOT / "nocturne" / "__main__.py").read_text(encoding="utf-8")
    body = src.split("def _check_codecs")[1].split("def ")[0]
    assert "np.arange" in body, "the probe image must vary across pixels"


# --- how a NEW dependency avoids repeating this (2026-09-22) ----------------

def _third_party_imports():
    """Every non-stdlib top-level package the app imports anywhere."""
    import ast
    import sys
    names = set()
    for f in (ROOT / "nocturne").rglob("*.py"):
        tree = ast.parse(f.read_text(encoding="utf-8"))
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
                                   f.read_text(errors="ignore", encoding="utf-8")))
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

    spec = (ROOT / "packaging" / "nocturne.spec").read_text(encoding="utf-8")
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


# --- --check-tools ---------------------------------------------------------

def _tools_check(monkeypatch, capsys, found, remove_stars=None):
    import nocturne.__main__ as entry
    import nocturne.settings as settings_mod
    from nocturne.tools import starnet

    monkeypatch.setattr(settings_mod, "detect_tool_paths", lambda s, *a, **k: dict(found))
    if remove_stars is not None:
        monkeypatch.setattr(starnet.StarNet, "remove_stars",
                            lambda self, img: remove_stars(img))
    code = entry._check_tools()
    return code, capsys.readouterr().out


def test_the_tools_check_passes_a_starnet_that_removes_the_stars(monkeypatch, capsys):
    import nocturne.__main__ as entry
    from nocturne.core.image import AstroImage

    def split(img):
        _, stars = entry._starnet_probe_image()
        return AstroImage(img.data - stars[..., None], False), img
    code, out = _tools_check(monkeypatch, capsys, {"starnet_path": "/x/starnet2"}, split)
    assert code == 0, out
    assert "starnet split : OK" in out


def test_the_tools_check_fails_a_starnet_that_leaves_the_stars(monkeypatch, capsys):
    """Teeth: an output that comes back is not an output that worked."""
    code, out = _tools_check(monkeypatch, capsys, {"starnet_path": "/x/starnet2"},
                             lambda img: (img, img))
    assert code == 2, out
    assert "STARS NOT REMOVED" in out


def test_the_tools_check_fails_a_starnet_that_raises(monkeypatch, capsys):
    def boom(img):
        raise ImportError("could not import name 'lzw_decode' from 'imagecodecs'")
    code, out = _tools_check(monkeypatch, capsys, {"starnet_path": "/x/starnet2"}, boom)
    assert code == 2
    assert "lzw_decode" in out


def test_a_tool_that_is_not_installed_is_not_a_failure(monkeypatch, capsys):
    code, out = _tools_check(monkeypatch, capsys, {})
    assert "starnet_path  : (not found)" in out
    if sys.platform != "win32":
        assert code == 0, out


def test_the_tools_check_returns_before_a_window_is_created():
    src = (ROOT / "nocturne" / "__main__.py").read_text(encoding="utf-8")
    body = src.split("def main()")[1]
    assert body.index('"--check-tools" in sys.argv') < body.index("QApplication(sys.argv)")


# --- --check-nr ------------------------------------------------------------

def _nnr_file(folder, mid="v23.0", name="Gullveig"):
    import json
    import struct
    raw = json.dumps({"contract": 1, "space": "stretched", "inputs": 3, "tile": 256,
                      "id": mid, "name": name}).encode("utf-8")
    path = folder / f"{mid}.nnr"
    path.write_bytes(b"NNR1" + struct.pack("<HHI", 1, 1, len(raw)) + raw + b"\0" * 32)
    return path


class _FakeModel:
    def __init__(self, out):
        self._out = out
        self.closed = False

    def run(self, tile):
        assert tile.shape == (1, 3, 256, 256) and tile.dtype.name == "float32"
        return self._out(tile)

    def close(self):
        self.closed = True


class _FakeEngine:
    def __init__(self, variant="release", out=lambda t: t * 0.1, open_error=None):
        self._variant, self._out, self._open_error = variant, out, open_error
        self.opened = []

    def version(self):
        return {"variant": self._variant, "engine": "1.0.0"}

    def open(self, path):
        if self._open_error:
            from nocturne.core.nr_engine import EngineError
            raise EngineError(self._open_error)
        self.opened.append(path)
        return _FakeModel(self._out)


def _nr_check(monkeypatch, capsys, tmp_path, engine, models=("v23.0",)):
    import nocturne.__main__ as entry
    from nocturne.core import nr_engine, nr_models
    for mid in models:
        _nnr_file(tmp_path, mid)
    monkeypatch.setattr(nr_models, "SHIPPED_DIR", str(tmp_path))
    monkeypatch.setattr(nr_engine, "load", lambda: engine)
    code = entry._check_nr()
    return code, capsys.readouterr().out


def test_check_nr_missing_engine_is_3(monkeypatch, capsys, tmp_path):
    code, out = _nr_check(monkeypatch, capsys, tmp_path, None)
    assert code == 3, out


def test_check_nr_dev_engine_is_4(monkeypatch, capsys, tmp_path):
    """A dev engine opens models from any process. Shipping one would hand out the
    models to anyone who copies the folder, so it fails the build outright."""
    code, out = _nr_check(monkeypatch, capsys, tmp_path, _FakeEngine(variant="dev"))
    assert code == 4, out


def test_check_nr_ok_is_0(monkeypatch, capsys, tmp_path):
    engine = _FakeEngine()
    code, out = _nr_check(monkeypatch, capsys, tmp_path, engine)
    assert code == 0, out
    assert "NR ok  v23.0 Gullveig" in out
    assert engine.opened == [str(tmp_path / "v23.0.nnr")]


def test_check_nr_a_model_the_engine_refuses_is_5(monkeypatch, capsys, tmp_path):
    engine = _FakeEngine(open_error="Nocturne NR runs only inside Nocturne.")
    code, out = _nr_check(monkeypatch, capsys, tmp_path, engine)
    assert code == 5, out
    assert "runs only inside Nocturne" in out


@pytest.mark.parametrize("bad", [
    lambda t: t * float("nan"),                       # not finite
    lambda t: t * 0.0,                                # all zero: nothing ran
    lambda t: t[:, :, :128],                          # wrong shape
])
def test_check_nr_a_tile_that_comes_back_wrong_is_5(monkeypatch, capsys, tmp_path, bad):
    """Teeth: an output that comes back is not an output that worked."""
    code, out = _nr_check(monkeypatch, capsys, tmp_path, _FakeEngine(out=bad))
    assert code == 5, out


def test_check_nr_every_bundled_model_is_run(monkeypatch, capsys, tmp_path):
    engine = _FakeEngine()
    code, out = _nr_check(monkeypatch, capsys, tmp_path, engine, models=("v23.0", "v24.0"))
    assert code == 0, out
    assert len(engine.opened) == 2


def test_check_nr_an_engine_with_no_models_is_5(monkeypatch, capsys, tmp_path):
    """A build that requires NR and carries the engine but no model offers nothing."""
    code, out = _nr_check(monkeypatch, capsys, tmp_path, _FakeEngine(), models=())
    assert code == 5, out


def test_the_nr_check_returns_before_a_window_is_created():
    src = (ROOT / "nocturne" / "__main__.py").read_text(encoding="utf-8")
    body = src.split("def main()")[1]
    assert body.index('"--check-nr" in sys.argv') < body.index("QApplication(sys.argv)")
