"""Bundled type. The whole point is that an export does not depend on what the
user has installed — the WYSIWYG principle applied to fonts — and the planned
Windows build has none of macOS's faces."""
import subprocess
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
from nocturne.ui.fonts import FONT_DIR, PLATE_FAMILIES, load_bundled_fonts  # noqa: E402

ROOT = Path(__file__).parents[2]


def test_every_advertised_family_actually_registers(qtbot):
    from PySide6.QtGui import QFontDatabase
    loaded = load_bundled_fonts()
    available = set(QFontDatabase.families())
    for _label, family in PLATE_FAMILIES:
        assert family in available, f"{family} is offered but did not load"
        assert family in loaded


def test_the_font_files_are_tracked_in_git():
    """A required asset can be untracked while every local test passes, because
    the file is sitting on this machine. update.svg was missing from git for
    four days while load_icon() raised on it, so a fresh clone could not
    construct MainWindow at all."""
    tracked = subprocess.run(["git", "ls-files", "nocturne/assets/fonts"],
                             cwd=ROOT, capture_output=True, text=True).stdout.split()
    for f in FONT_DIR.glob("*.ttf"):
        rel = f"nocturne/assets/fonts/{f.name}"
        assert rel in tracked, f"{rel} exists here but is NOT in git"
    assert len([t for t in tracked if t.endswith(".ttf")]) == len(PLATE_FAMILIES)


def test_the_licences_travel_with_the_fonts():
    """The SIL OFL requires it. Shipping the binaries without the licence is a
    licence violation, not an oversight."""
    licences = list(FONT_DIR.glob("OFL-*.txt"))
    assert len(licences) == len(PLATE_FAMILIES)
    for lic in licences:
        assert "SIL OPEN FONT LICENSE" in lic.read_text().upper()


def test_the_packaging_spec_carries_the_assets_directory():
    spec = (ROOT / "packaging" / "nocturne.spec").read_text()
    assert 'ASSETS, "nocturne/assets"' in spec, \
        "fonts live under assets/; if that sweep goes, name the font dir explicitly"


def test_startup_loads_the_fonts_before_a_window_exists():
    """A plate rendered before the families register silently substitutes."""
    src = (ROOT / "nocturne" / "__main__.py").read_text()
    assert "load_bundled_fonts()" in src
    body = src.split("def main()")[1]
    assert body.index("QApplication(sys.argv)") < body.index("load_bundled_fonts()"), \
        "addApplicationFont needs a QApplication to exist first"


def test_the_loader_uses_an_absolute_path(qtbot):
    """Qt's addApplicationFont returns -1 for a RELATIVE path — measured
    2026-09-02: the same five files load from an absolute path and every one of
    them fails from `nocturne/assets/fonts/...`. Nothing reports the failure but
    a silently substituted system face, so pin the resolution here."""
    assert FONT_DIR.is_absolute()


def test_a_missing_font_directory_is_survivable(monkeypatch, tmp_path):
    """Never take the app down over type. Startup calls this."""
    import nocturne.ui.fonts as f
    monkeypatch.setattr(f, "_loaded", None)   # the cache outlives one test
    monkeypatch.setattr(f, "FONT_DIR", tmp_path / "nope")
    assert f.load_bundled_fonts() == []
