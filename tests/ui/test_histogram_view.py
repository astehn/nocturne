import numpy as np
import pytest

pytest.importorskip("PySide6")
from seestar_processor.core.image import AstroImage  # noqa: E402
from seestar_processor.ui.histogram_view import HistogramView, _polygon_points  # noqa: E402


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
