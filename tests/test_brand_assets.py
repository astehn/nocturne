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
    assert p.exists()
    assert not QPixmap(str(p)).isNull()
