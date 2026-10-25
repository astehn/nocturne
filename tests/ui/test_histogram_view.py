import numpy as np
import pytest

pytest.importorskip("PySide6")
from nocturne.core.image import AstroImage  # noqa: E402
from nocturne.ui.histogram_view import HistogramView, _polygon_points  # noqa: E402


def test_polygon_points_span_and_bounds():
    pts = _polygon_points([0, 5, 10, 5, 0], w=100, h=50, peak=10)
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    assert min(xs) >= 0 and max(xs) <= 100
    assert min(ys) >= 0 and max(ys) <= 50
    # closes along the baseline (first and last points sit on the bottom edge)
    assert pts[0][1] == 50 and pts[-1][1] == 50


def test_set_image_populates_and_paints(qtbot):
    view = HistogramView()
    qtbot.addWidget(view)
    view.resize(200, 120)
    img = AstroImage((np.random.rand(20, 20, 3)).astype(np.float32), is_linear=False)
    view.set_image(img)
    assert view._hist is not None
    from PySide6.QtGui import QPixmap
    view.render(QPixmap(view.size()))   # paintEvent runs without error


def _render(view):
    from PySide6.QtGui import QImage
    out = QImage(view.size(), QImage.Format.Format_RGB32)
    view.render(out)
    return out


def test_a_peak_all_three_channels_share_is_drawn_neutral_not_blue(qtbot):
    """Blue was drawn last over red and green, so a spike every channel shares
    (the black-point spike in bin 0) always looked like a blue one (2026-10-25)."""
    view = HistogramView()
    qtbot.addWidget(view)
    view.resize(256, 120)
    counts = np.full(256, 10, dtype=np.int64)
    counts[:40] = 1000                       # the same tall block in every channel
    view._hist = {"r": counts.copy(), "g": counts.copy(), "b": counts.copy()}
    c = _render(view).pixelColor(15, 100)    # inside the shared fill, off the grid lines
    spread = max(c.red(), c.green(), c.blue()) - min(c.red(), c.green(), c.blue())
    assert spread <= 12, (c.red(), c.green(), c.blue())


def test_a_peak_one_channel_has_alone_keeps_its_colour(qtbot):
    view = HistogramView()
    qtbot.addWidget(view)
    view.resize(256, 120)
    low = np.full(256, 10, dtype=np.int64)
    red = low.copy()
    red[:40] = 1000
    view._hist = {"r": red, "g": low.copy(), "b": low.copy()}
    c = _render(view).pixelColor(15, 60)
    assert c.red() > c.green() + 30 and c.red() > c.blue() + 30, (c.red(), c.green(), c.blue())
