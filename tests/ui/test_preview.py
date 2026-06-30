import numpy as np
import pytest
from seestar_processor.core.image import AstroImage

pytest.importorskip("PySide6")
from seestar_processor.ui.preview import to_qimage  # noqa: E402


def test_to_qimage_dimensions(qapp):
    img = AstroImage(np.random.rand(6, 10, 3).astype(np.float32))
    qimg = to_qimage(img)
    assert qimg.width() == 10
    assert qimg.height() == 6


def test_to_qimage_mono(qapp):
    img = AstroImage(np.random.rand(6, 10).astype(np.float32))
    qimg = to_qimage(img)
    assert qimg.width() == 10
