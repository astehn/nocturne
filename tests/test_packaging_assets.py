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
    src = SPEC.read_text()
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
    src = SPEC.read_text()
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
    assert any(n.startswith("denoise_") and n.endswith(".onnx") for n in names), \
        "our own denoise model was pruned"
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
    src = SPEC.read_text()
    assert re.search(r"datas \+= _prune\(d\)", src), \
        "collect_all output is unpruned; colour/htmlcov ships again"
