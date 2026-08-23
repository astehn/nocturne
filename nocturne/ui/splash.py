"""The launch splash: the logo, the version, and long enough to read them.

An earlier attempt at this failed for a reason worth recording, because it is
not the obvious one. Nocturne starts fast, so the splash was created, shown and
replaced by the main window inside a few hundred milliseconds — it was working
perfectly and nobody ever saw it.

The fix is a minimum visible time measured from AFTER loading finishes. The
obvious version — start the clock when the splash is shown and wait out the
remainder — does not work, and failed twice: building the main window blocks the
event loop for about half of startup, so the splash is on screen but frozen and
never repainted. "It was up for two seconds" and "the user saw it for two
seconds" are different claims, and only the second one matters.

How that wait is spent matters as much as its length. `time.sleep` blocks the
event loop, so the splash never gets to paint: macOS shows an empty white
rectangle and then a spinning beachball, which is strictly worse than no splash
at all. The caller runs a real QEventLoop instead — see `__main__.main`.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPixmap
from PySide6.QtWidgets import QSplashScreen


# Long enough to register as an image rather than a flicker. Andreas' report was
# "the application loaded so fast that the user never saw the splash", so this is
# the whole feature -- a tidy-up that lowers it re-creates the original bug.
MIN_SPLASH_SECONDS = 2.0

# The art is 2000x1254; shown at source size it is a wall on a laptop. This is
# the LOGICAL width -- the pixmap is rendered at devicePixelRatio above it, so a
# retina screen still gets every pixel of the original.
_LOGICAL_WIDTH = 560

_CAPTION_MARGIN = 22


def splash_caption(version: str) -> str:
    """The version line, derived from the running version and never copied."""
    return f"v{version}"


class NocturneSplash(QSplashScreen):
    """A splash that paints its own version line and closes on a click.

    Click-to-dismiss is not decoration: the person who launches this app most
    often is the one developing it, and a splash you cannot skip becomes a tax
    on every run.

    `dismissed` exists because QSplashScreen's own click handling only HIDES the
    widget — it never destroys it, so a caller waiting on `destroyed` waits out
    the full timer with nothing on screen and the click does nothing at all.
    """

    dismissed = Signal()

    def __init__(self, pixmap: QPixmap, caption: str) -> None:
        super().__init__(pixmap)
        self.caption = caption

    def mousePressEvent(self, event) -> None:  # noqa: N802  (Qt's spelling)
        self.dismissed.emit()
        super().mousePressEvent(event)

    def drawContents(self, painter) -> None:  # noqa: N802  (Qt's spelling)
        """Draw the version and NOTHING else.

        The artwork already sets "Nocturne" and "Beta" in its own type, so the
        app's only job is the number that changes between releases. An earlier
        version of this painted its own BETA heading and a notice line over the
        picture, which duplicated the wording that was already there and ran
        across the tripod legs.

        deviceIndependentSize(), NOT pixmap().rect(): the pixmap is stored at
        devicePixelRatio while the painter works in LOGICAL points, so the
        device rect puts the text at double its intended position -- off the
        bottom of the splash, invisible. Headless tests run at dpr 1.0 where the
        two are identical, so only rendering it on a real screen showed this.
        """
        super().drawContents(painter)
        if not self.caption:
            return
        size = self.pixmap().deviceIndependentSize()
        rect = QRectF(0.0, 0.0, size.width(), size.height()).toRect().adjusted(
            _CAPTION_MARGIN, _CAPTION_MARGIN, -_CAPTION_MARGIN, -_CAPTION_MARGIN)
        font = QFont(painter.font())
        font.setPointSizeF(max(11.0, font.pointSizeF()))
        painter.setFont(font)
        painter.setPen(QColor(168, 172, 188))
        painter.drawText(
            rect,
            int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom),
            self.caption,
        )


def splash_path() -> Path:
    return Path(__file__).resolve().parent.parent / "assets" / "splash.png"


def make_splash(version: str, *, logical_width: int = _LOGICAL_WIDTH) -> NocturneSplash:
    """Build the splash at a sane on-screen size, sharp on any display."""
    from PySide6.QtWidgets import QApplication

    src = QPixmap(str(splash_path()))
    ratio = 1.0
    app = QApplication.instance()
    if app is not None:
        screen = app.primaryScreen()
        if screen is not None:
            ratio = float(screen.devicePixelRatio()) or 1.0

    if not src.isNull():
        target = int(logical_width * ratio)
        src = src.scaled(
            target, target,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        src.setDevicePixelRatio(ratio)

    return NocturneSplash(src, splash_caption(version))
