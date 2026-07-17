import numpy as np
import pytest

pytest.importorskip("PySide6")
from PySide6.QtGui import QImage  # noqa: E402
from nocturne.ui.frame_preview import FramePreview  # noqa: E402


def _qimage(w=32, h=24):
    arr = np.zeros((h, w, 3), dtype=np.uint8)
    return QImage(arr.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()


def test_starts_with_placeholder(qtbot):
    fp = FramePreview()
    qtbot.addWidget(fp)
    assert not fp.has_image()
    assert "Select a frame" in fp.overlay.text()
    assert fp.overlay.isVisibleTo(fp)


def test_show_image_hides_overlay(qtbot):
    fp = FramePreview()
    qtbot.addWidget(fp)
    fp.show_image(_qimage())
    assert fp.has_image()
    assert not fp.overlay.isVisibleTo(fp)


def test_show_message_over_image_then_clear(qtbot):
    fp = FramePreview()
    qtbot.addWidget(fp)
    fp.show_image(_qimage())
    fp.show_message("Preview failed:\ncould not read frame")
    assert "Preview failed" in fp.overlay.text()
    assert fp.overlay.isVisibleTo(fp)
    fp.clear()
    assert not fp.has_image()
    assert "Select a frame" in fp.overlay.text()
