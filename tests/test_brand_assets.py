import pytest

pytest.importorskip("PySide6")
from pathlib import Path
import nocturne

_ASSETS = Path(nocturne.__file__).resolve().parent / "assets"


def test_icon_svg_exists_and_renders(qtbot):
    from PySide6.QtSvg import QSvgRenderer
    p = _ASSETS / "nocturne_icon.svg"
    assert p.exists()
    assert QSvgRenderer(str(p)).isValid()


def test_splash_png_exists_and_loads(qtbot):
    from PySide6.QtGui import QPixmap
    p = _ASSETS / "splash.png"
    assert p.exists(), "the splash art is missing from nocturne/assets"
    assert not QPixmap(str(p)).isNull(), "splash.png is not a readable image"


def test_splash_png_is_tracked_by_git():
    """A required asset can be untracked and every local test still passes,
    because the file exists on THIS machine. update.svg was missing from git for
    four days while icons.py listed it and load_icon() raises on a missing SVG,
    so a fresh clone could not construct MainWindow at all. The splash art
    arrived as a loose file in the repo root, which is exactly how that starts.
    """
    import subprocess

    p = _ASSETS / "splash.png"
    try:
        r = subprocess.run(
            ["git", "ls-files", "--error-unmatch", str(p)],
            cwd=str(p.parent), capture_output=True, text=True, timeout=20,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pytest.skip("git unavailable; tracking cannot be checked here")
    assert r.returncode == 0, (
        f"{p.name} is NOT tracked by git — it works here and nowhere else. "
        f"git said: {r.stderr.strip() or r.stdout.strip()}"
    )
