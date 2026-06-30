import numpy as np
import pytest

pytest.importorskip("PySide6")
from seestar_processor.core.image import AstroImage  # noqa: E402
from seestar_processor.ui.histogram_view import HistogramView  # noqa: E402


def test_histogram_view_accepts_image(qtbot):
    v = HistogramView()
    qtbot.addWidget(v)
    v.set_image(AstroImage(np.random.rand(16, 16, 3).astype(np.float32)))
    assert v._hist is not None
    assert set(v._hist) == {"r", "g", "b"}
