"""What the shipped app is allowed to carry.

Measured on the 0.23.0 build, 2026-09-02: 491 MB, of which 231 MB could never
be used — 153 MB of a dropped super-resolution model (onnxruntime is excluded,
so it cannot load) and 78 MB of the colour-science project's own HTML test
coverage report, which ships inside the installed package.
"""
import os
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
SPEC = ROOT / "packaging" / "nocturne.spec"
ASSETS = ROOT / "nocturne" / "assets"


def _spec_ns():
    """Run the spec's helpers without running PyInstaller."""
    src = SPEC.read_text(encoding="utf-8")
    body = src[src.index("def _prune"):src.index("datas = _assets()")]
    ns = {"os": os, "ASSETS": str(ASSETS)}
    exec(body, ns)  # noqa: S102 — our own file, and the point is to test it
    return ns


def test_the_assets_are_named_not_swept():
    """A directory entry is expanded by PyInstaller at build time, so anything
    sitting in assets/ on the build machine ships whether the app can use it or
    not. Naming the files also makes a NEW asset a deliberate addition — the
    safer failure, since a missing one breaks loudly at startup while an
    unnoticed 150 MB one only makes the download slower."""
    src = SPEC.read_text(encoding="utf-8")
    # Match the ASSIGNMENT, not the prose. The first version of this assertion
    # searched the whole file and tripped on the docstring explaining the very
    # sweep it was guarding against.
    assert re.search(r"^datas = _assets\(\)", src, re.M), "datas is not built by _assets()"
    assert not re.search(r"^datas = \[\(ASSETS", src, re.M), "the whole assets dir is swept again"


def test_the_dropped_model_cannot_ship():
    entries = _spec_ns()["_assets"]()
    names = [os.path.basename(a) for a, _ in entries]
    assert not any("edsr" in n.lower() for n in names), \
        "the dropped EDSR model is in the bundle again"


def test_the_things_the_app_actually_needs_still_ship():
    """The prune must never be a size target that eats a required asset. A
    missing one is the update.svg bug: every local test passes because the file
    is on this machine, and a fresh install cannot start."""
    entries = _spec_ns()["_assets"]()
    names = [os.path.basename(a) for a, _ in entries]
    # A denoise model was asserted here until 2026-09-18, when the one that
    # existed was removed from the repo. It was never required: its step was
    # never in the pipeline (and was removed outright on 2026-10-05) and the
    # spec excludes onnxruntime, so the bundle could not have run it. See
    # tests/test_no_model_ships.py, which asserts the opposite.
    assert not any(n.endswith(".onnx") for n in names), \
        "a model is being packaged; the app has no onnxruntime to run it"
    assert sum(1 for n in names if n.endswith(".ttf")) == 5, "the bundled fonts went"
    assert sum(1 for n in names if n.startswith("OFL-")) == 5, "the font licences went"
    assert any(n.endswith(".svg") for n in names), "the icons went"
    assert any(n == "contributors.json" for n in names), "About's data went"


def test_a_collected_package_does_not_bring_its_coverage_report():
    prune = _spec_ns()["_prune"]
    sample = [("colour/htmlcov/index.html", "/x/colour/htmlcov/index.html", "DATA"),
              ("colour/models/rgb.py", "/x/colour/models/rgb.py", "DATA")]
    kept = [e[0] for e in prune(sample)]
    assert kept == ["colour/models/rgb.py"]


def test_collected_packages_are_pruned_too():
    """Not only the assets — colour's 78 MB rides in via collect_all."""
    src = SPEC.read_text(encoding="utf-8")
    assert re.search(r"datas \+= _prune\(d\)", src), \
        "collect_all output is unpruned; colour/htmlcov ships again"


def test_onnxruntime_stays_excluded():
    """Nothing in the app imports it since the pre-stretch denoiser went
    (2026-10-05). The exclude stays so a stray import cannot put 64 MB back
    into every download without anyone choosing to."""
    src = SPEC.read_text(encoding="utf-8")
    excludes = src[src.index("excludes=["):]
    excludes = excludes[:excludes.index("]")]
    assert '"onnxruntime"' in excludes


def test_every_data_file_ships():
    """nocturne/data/ is listed file by file, not swept, so a new data file has
    to be added by hand — and common_names.csv never was: every build since it
    appeared (v0.10.0) shipped without the Heart, the Soul, the Horsehead or any
    other curated name, while every local test passed off the working tree."""
    src = SPEC.read_text(encoding="utf-8")
    listed = set(re.findall(r'"nocturne", "data", "([^"]+)"', src))
    present = {p.name for p in (ROOT / "nocturne" / "data").iterdir()
               if p.is_file() and not p.name.startswith(".")}
    assert present - listed == set(), f"data files the bundle leaves out: {present - listed}"


# --- Nocturne NR -------------------------------------------------------------

def _nr_tree(tmp_path):
    """A build machine after deploy has copied the engine and a model in."""
    (tmp_path / "icons").mkdir()
    (tmp_path / "icons" / "x.svg").write_text("<svg/>")
    (tmp_path / "NR-MODEL-LICENCE.txt").write_text("licence")
    eng = tmp_path / "engine"
    eng.mkdir()
    (eng / "libnrengine.dylib").write_bytes(b"\0")
    (eng / "libonnxruntime.1.29.0.dylib").write_bytes(b"\0")
    nr = tmp_path / "models" / "nr"
    nr.mkdir(parents=True)
    (nr / "v23.0.nnr").write_bytes(b"NNR1")
    (nr / "notes.json").write_text("{}")
    (nr / "old").mkdir()
    (nr / "old" / "v22.0.onnx").write_bytes(b"plain")   # nested: the subfolder hole
    (nr / "old" / "v22.0.json").write_text("{}")
    (tmp_path / "stray").mkdir()
    (tmp_path / "stray" / "edge.ONNX").write_bytes(b"plain")
    return tmp_path


def _spec_ns_at(assets):
    ns = _spec_ns()
    ns["ASSETS"] = str(assets)
    return ns


def test_the_nr_engine_is_not_shipped_as_data(tmp_path):
    """As data it lands in Resources, where neither the frozen ENGINE_DIR nor
    the engine's own inside-the-bundle check would find it."""
    entries = _spec_ns_at(_nr_tree(tmp_path))["_assets"]()
    assert not any("engine" in dest or "libnrengine" in src for src, dest in entries)


def test_the_nr_engine_ships_as_binaries_side_by_side(tmp_path):
    """The engine dlopens onnxruntime from its own folder by exact name."""
    entries = _spec_ns_at(_nr_tree(tmp_path))["_nr_engine"]()
    assert sorted((os.path.basename(s), d) for s, d in entries) == [
        ("libnrengine.dylib", "nrengine"), ("libonnxruntime.1.29.0.dylib", "nrengine")]


def test_only_encrypted_models_and_the_licence_ship(tmp_path):
    entries = _spec_ns_at(_nr_tree(tmp_path))["_assets"]()
    got = {(os.path.basename(s), d) for s, d in entries}
    assert ("v23.0.nnr", "nocturne/assets/models/nr") in got
    assert ("NR-MODEL-LICENCE.txt", "nocturne/assets") in got
    assert not any(n == "notes.json" for n, _ in got)


def test_no_plain_model_ships_from_anywhere_in_assets(tmp_path):
    """A plain .onnx is exactly what the encryption exists to keep out of the
    public download — in models/nr, a subfolder of it, or anywhere else."""
    entries = _spec_ns_at(_nr_tree(tmp_path))["_assets"]()
    names = [os.path.basename(s) for s, _ in entries]
    assert not any(n.lower().endswith(".onnx") for n in names), names
    assert "v22.0.json" not in names


def test_a_source_build_without_nr_still_builds(tmp_path):
    (tmp_path / "icons").mkdir()
    (tmp_path / "icons" / "x.svg").write_text("<svg/>")
    ns = _spec_ns_at(tmp_path)
    assert ns["_nr_engine"]() == []
    assert [os.path.basename(s) for s, _ in ns["_assets"]()] == ["x.svg"]


def test_upx_stays_off():
    """The engine hashes onnxruntime before loading it — the whole file on Linux
    and Windows, so strip would break it as surely as UPX."""
    src = SPEC.read_text(encoding="utf-8")
    coll = src[src.index("coll = COLLECT("):src.index("app = ")]
    assert "upx=False" in coll and "strip=False" in coll
    assert "upx_exclude=[os.path.basename(src) for src, _ in _nr_engine()]" in coll
    assert "upx=True" not in src and "strip=True" not in src


# --- the VC++ runtime beside a Windows NR build (2026-10-28) -----------------

def _vc_dirs(tmp_path, names_a, names_b=()):
    a, b = tmp_path / "PySide6", tmp_path / "System32"
    a.mkdir()
    b.mkdir()
    for n in names_a:
        (a / n).write_bytes(b"pyside")
    for n in names_b:
        (b / n).write_bytes(b"system")
    return [str(a), str(b)]


def test_a_windows_nr_build_carries_msvcp140_at_the_top_level(tmp_path):
    """onnxruntime.dll needs MSVCP140 and MSVCP140_1. PyInstaller resolves them
    from PySide6's DLL directory and so collects them only into _internal\\PySide6
    (the v0.56.0 build had no top-level msvcp140*.dll at all). The build VM has
    the runtime system-wide, so --check-nr there cannot tell; the spec places
    them in _internal itself."""
    ns = _spec_ns()
    dirs = _vc_dirs(tmp_path, ["msvcp140.dll", "msvcp140_1.dll"], ["msvcp140_1.dll"])
    got = ns["_vc_runtime"]([("x/nrengine.dll", "nrengine")], True, dirs)
    assert got == [(os.path.join(dirs[0], "msvcp140.dll"), "."),
                   (os.path.join(dirs[0], "msvcp140_1.dll"), ".")]


def test_the_vc_runtime_falls_back_to_the_next_directory(tmp_path):
    ns = _spec_ns()
    dirs = _vc_dirs(tmp_path, ["msvcp140.dll"], ["msvcp140_1.dll"])
    got = ns["_vc_runtime"]([("x/nrengine.dll", "nrengine")], True, dirs)
    assert got == [(os.path.join(dirs[0], "msvcp140.dll"), "."),
                   (os.path.join(dirs[1], "msvcp140_1.dll"), ".")]


def test_the_vc_runtime_is_only_added_for_a_windows_nr_build(tmp_path):
    ns = _spec_ns()
    dirs = _vc_dirs(tmp_path, ["msvcp140.dll", "msvcp140_1.dll"])
    assert ns["_vc_runtime"]([], True, dirs) == []
    assert ns["_vc_runtime"]([("x/libnrengine.so", "nrengine")], False, dirs) == []


def test_the_spec_feeds_the_vc_runtime_into_the_binaries():
    src = SPEC.read_text(encoding="utf-8")
    assert "binaries += _vc_runtime(binaries, _WIN_BUILD," in src


def test_the_windows_build_refuses_an_nr_build_without_the_vc_runtime():
    """The gate that holds the line: only the four runtime DLLs at the top of
    _internal prove a machine without the VC++ redistributable can load NR."""
    ps1 = (ROOT / "packaging" / "build_windows.ps1").read_text(encoding="utf-8")
    block = ps1[ps1.index('if ($env:NOCTURNE_REQUIRE_NR -eq "1")'):ps1.index("# The installer, only after")]
    for dll in ("msvcp140.dll", "msvcp140_1.dll", "vcruntime140.dll", "vcruntime140_1.dll"):
        assert f'"{dll}"' in block, dll
    assert "dist\\Nocturne\\_internal" in block
    # the cheap file check first, so a missing DLL names itself
    assert block.index("foreach ($dll in") < block.index('Invoke-Selftest $Exe "--check-nr"')
