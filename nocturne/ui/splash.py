"""The launch splash: the logo, the version, and long enough to read them.

An earlier attempt at this failed for a reason worth recording, because it is
not the obvious one. Nocturne starts fast, so the splash was created, shown and
replaced by the main window inside a few hundred milliseconds — it was working
perfectly and nobody ever saw it.

The fix is a MINIMUM VISIBLE TIME, not a delay bolted onto startup. Startup
work runs while the splash is up, and only the unused remainder is waited out
(:func:`remaining_hold`), so a slow launch costs nothing extra and a fast one
still shows the thing.

How that wait is spent matters as much as its length. `time.sleep` blocks the
event loop, so the splash never gets to paint: macOS shows an empty white
rectangle and then a spinning beachball, which is strictly worse than no splash
at all. The caller runs a real QEventLoop instead — see `__main__.main`.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QPixmap
from PySide6.QtWidgets import QSplashScreen

import nocturne

# Long enough to register as an image rather than a flicker. Andreas' report was
# "the application loaded so fast that the user never saw the splash", so this is
# the whole feature -- a tidy-up that lowers it re-creates the original bug.
MIN_SPLASH_SECONDS = 2.0

# The art is square and 1254 px; shown at source size it is a wall on a laptop.
# This is the LOGICAL width -- the pixmap is rendered at devicePixelRatio above
# it, so a retina screen still gets every pixel of the original.
_LOGICAL_WIDTH = 420

_CAPTION_MARGIN = 18


def splash_caption(version: str) -> str:
    """The version line, derived from the running version and never copied."""
    return f"v{version}"


def splash_heading() -> str:
    """"BETA" while the release stage says so, and nothing once it does not.

    Read from `nocturne.RELEASE_STAGE` at CALL time, never captured at import:
    a module-level copy could not be cleared for a stable release, which is
    exactly the drift this is meant to prevent.
    """
    return nocturne.RELEASE_STAGE.upper() if nocturne.RELEASE_STAGE else ""


def remaining_hold(elapsed: float, minimum: float = MIN_SPLASH_SECONDS) -> float:
    """How much longer the splash must stay up, given time already spent.

    Clamped at zero: a startup slower than the minimum has already shown the
    splash for long enough and must not be asked to wait backwards.
    """
    return max(0.0, float(minimum) - float(elapsed))


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

    def __init__(self, pixmap: QPixmap, caption: str,
                 heading: str = "", notice: str = "") -> None:
        super().__init__(pixmap)
        self.caption = caption
        self.heading = heading
        self.notice = notice

    def mousePressEvent(self, event) -> None:  # noqa: N802  (Qt's spelling)
        self.dismissed.emit()
        super().mousePressEvent(event)

    def drawContents(self, painter) -> None:  # noqa: N802  (Qt's spelling)
        """Beta first, centred and large; the version is the footnote.

        The ordering is the requirement: the whole reason this splash exists is
        that nothing on the user's machine said the software was beta. A version
        string tucked in a corner is something you read if you go looking, which
        is the opposite of what was asked for.
        """
        super().drawContents(painter)
        rect = self.pixmap().rect().adjusted(
            _CAPTION_MARGIN, _CAPTION_MARGIN, -_CAPTION_MARGIN, -_CAPTION_MARGIN)
        base = QFont(painter.font())
        bottom = int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom)

        if self.caption:
            f = QFont(base)
            f.setPointSizeF(max(10.0, base.pointSizeF() - 1))
            painter.setFont(f)
            painter.setPen(QColor(150, 152, 162))
            painter.drawText(rect, bottom, self.caption)
            rect = rect.adjusted(0, 0, 0, -(painter.fontMetrics().height() + 4))

        if self.notice:
            f = QFont(base)
            f.setPointSizeF(max(11.0, base.pointSizeF()))
            painter.setFont(f)
            painter.setPen(QColor(216, 218, 226))
            painter.drawText(rect, bottom, self.notice)
            rect = rect.adjusted(0, 0, 0, -(painter.fontMetrics().height() + 6))

        if self.heading:
            f = QFont(base)
            f.setBold(True)
            f.setPointSizeF(max(22.0, base.pointSizeF() * 2.0))
            f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 3.0)
            painter.setFont(f)
            painter.setPen(QColor(255, 176, 84))
            painter.drawText(rect, bottom, self.heading)


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

    return NocturneSplash(src, splash_caption(version),
                          heading=splash_heading(), notice=nocturne.BETA_NOTICE)
