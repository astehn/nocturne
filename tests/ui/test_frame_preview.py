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
    assert fp.has_image()  # error overlay does not clear the image (deliberate contract)
    fp.clear()
    assert not fp.has_image()
    assert "Select a frame" in fp.overlay.text()


def test_show_waiting_puts_a_ring_above_the_text(qtbot):
    fp = FramePreview(); qtbot.addWidget(fp)
    fp.resize(500, 400); fp.show(); qtbot.waitExposed(fp)
    fp.show_waiting("Separating stars…", 46, 100)
    block = fp.waiting_block()
    assert fp.is_waiting() and block.isVisible()
    assert not fp.overlay.isVisible(), "never the ring AND the old text"
    assert block.ring.fraction() == pytest.approx(0.46)
    assert fp.message_text() == "Separating stars…"


def test_show_message_after_waiting_shows_plain_text_again(qtbot):
    fp = FramePreview(); qtbot.addWidget(fp)
    fp.show(); qtbot.waitExposed(fp)
    fp.show_waiting("Separating stars…")
    fp.show_message("Star separation failed.")
    assert not fp.is_waiting() and not fp.waiting_block().isVisible()
    assert fp.overlay.isVisible() and fp.message_text() == "Star separation failed."


def test_an_image_ends_the_wait(qtbot):
    fp = FramePreview(); qtbot.addWidget(fp)
    fp.show(); qtbot.waitExposed(fp)
    fp.show_waiting("Finding stars…")
    img = QImage(8, 8, QImage.Format.Format_RGB32); img.fill(0)
    fp.show_image(img)
    assert not fp.is_waiting() and not fp.waiting_block().ring.is_spinning()


def test_show_message_alone_is_unchanged(qtbot):
    """Opt-in: the other surfaces that only ever call show_message must see
    exactly today's behaviour — no waiting block is even created."""
    fp = FramePreview(); qtbot.addWidget(fp)
    fp.show_message("Select a frame")
    assert fp.waiting_block() is None
    assert fp.overlay.text() == "Select a frame"
