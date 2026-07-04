from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from .theme import TEXT

_ICON_DIR = Path(__file__).resolve().parent.parent / "assets" / "icons"

ICON_NAMES = (
    "open", "settings", "save-recipe", "batch", "stack", "haoiii", "palette",
    "undo", "redo", "before-after", "log", "fit", "actual-size", "about",
)


@lru_cache(maxsize=None)
def load_icon(name: str, color: str = TEXT) -> QIcon:
    """Render an SVG icon tinted to `color` (source-in composite). Cached."""
    path = _ICON_DIR / f"{name}.svg"
    if not path.exists():
        raise FileNotFoundError(f"icon not found: {name}")
    renderer = QSvgRenderer(str(path))
    if not renderer.isValid():
        return QIcon()
    size = QSize(48, 48)
    pm = QPixmap(size)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    renderer.render(painter, QRectF(0, 0, size.width(), size.height()))
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(pm.rect(), QColor(color))
    painter.end()
    return QIcon(pm)
