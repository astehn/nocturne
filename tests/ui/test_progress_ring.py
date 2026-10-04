"""The finishing tools' circular progress ring (spec 2026-10-04-progress-ring)."""
import pytest
from PySide6.QtGui import QColor, QImage, QPainter

from nocturne.ui import theme
from nocturne.ui.progress_ring import ProgressRing, WaitingBlock


def _render(ring) -> QImage:
    ring.resize(ring.sizeHint())
    img = QImage(ring.size(), QImage.Format.Format_ARGB32)
    img.fill(QColor(theme.BG_1))
    ring.render(img)
    return img


def _is_accent(c: QColor) -> bool:
    a = QColor(theme.ACCENT)
    return abs(c.red() - a.red()) < 40 and abs(c.green() - a.green()) < 40 and abs(c.blue() - a.blue()) < 40


def _at(img, ring, angle_deg_clockwise_from_12):
    """The pixel on the stroke's centre line at a clock angle."""
    import math
    d = ring.diameter()
    r = d / 2 - ring.stroke() / 2 - 1
    cx = cy = ring.sizeHint().width() / 2
    a = math.radians(angle_deg_clockwise_from_12)
    return img.pixelColor(int(cx + r * math.sin(a)), int(cy - r * math.cos(a)))


def test_sizes_match_the_approved_mockup(qtbot):
    big, small = ProgressRing(size="large"), ProgressRing(size="small")
    qtbot.addWidget(big); qtbot.addWidget(small)
    assert (big.diameter(), big.stroke()) == (68, 6)
    assert (small.diameter(), small.stroke()) == (18, 2.5)


def test_determinate_fills_clockwise_from_twelve(qtbot):
    ring = ProgressRing(); qtbot.addWidget(ring)
    ring.set_progress(46, 100)
    img = _render(ring)
    assert _is_accent(_at(img, ring, 10)), "just past 12 o'clock is filled at 46%"
    assert _is_accent(_at(img, ring, 150)), "150° < 46% of 360° = 165.6°"
    assert not _is_accent(_at(img, ring, 200)), "past the fill is track, not accent"
    assert not _is_accent(_at(img, ring, 350)), "counter-clockwise of 12 is NOT filled"


def test_the_number_is_in_the_centre_only_on_a_large_determinate_ring(qtbot):
    big = ProgressRing(); qtbot.addWidget(big)
    big.set_progress(46, 100)
    assert big.centre_text() == "46%"
    big.set_indeterminate()
    assert big.centre_text() == ""
    small = ProgressRing(size="small"); qtbot.addWidget(small)
    small.set_progress(46, 100)
    assert small.centre_text() == ""


@pytest.mark.parametrize("done,total,expected", [(0, 0, None), (5, -1, None),
                                                  (150, 100, 1.0), (-3, 100, 0.0),
                                                  (1, 3, 1 / 3)])
def test_odd_totals_are_safe(qtbot, done, total, expected):
    ring = ProgressRing(); qtbot.addWidget(ring)
    ring.set_progress(done, total)
    assert ring.fraction() == (pytest.approx(expected) if expected is not None else None)


def test_the_spinner_runs_only_while_visible(qtbot):
    host = WaitingBlock(); qtbot.addWidget(host)
    ring = host.ring
    ring.set_indeterminate()
    assert not ring.is_spinning(), "hidden: no timer"
    host.show(); qtbot.waitExposed(host)
    assert ring.is_spinning()
    host.hide()
    assert not ring.is_spinning(), "a hidden ring must not keep a timer ticking"


def test_a_determinate_ring_does_not_spin(qtbot):
    host = WaitingBlock(); qtbot.addWidget(host)
    host.show(); qtbot.waitExposed(host)
    host.set_progress(30, 100)
    assert not host.ring.is_spinning()


def test_progress_set_while_hidden_is_painted_when_shown(qtbot):
    ring = ProgressRing(); qtbot.addWidget(ring)
    ring.set_progress(80, 100)           # before any show
    ring.show(); qtbot.waitExposed(ring)
    assert ring.fraction() == pytest.approx(0.8)
    assert _is_accent(_at(_render(ring), ring, 270))


def test_waiting_block_puts_the_ring_above_the_text(qtbot):
    block = WaitingBlock(); qtbot.addWidget(block)
    block.set_text("Separating stars…\n(one-time, then tweak live)")
    block.resize(600, 400); block.show(); qtbot.waitExposed(block)
    assert block.text().startswith("Separating stars")
    assert block.ring.geometry().bottom() < block.label.geometry().top()
    assert abs(block.ring.geometry().center().x() - block.label.geometry().center().x()) <= 2


def test_the_waiting_text_has_no_box_behind_it(qtbot):
    """Under the real stylesheet the global `QWidget { background: BG_1 }` rule
    painted the label's rect, so the text sat in a dark box over the preview.
    Sampled at a corner of the label away from the glyphs: it must be the
    parent's ground, not BG_1."""
    from PySide6.QtGui import QColor
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QWidget
    from nocturne.ui import theme
    from nocturne.ui.progress_ring import WaitingBlock

    app = QApplication.instance()
    old = app.styleSheet()
    app.setStyleSheet(theme.build_stylesheet())
    try:
        host = QWidget()
        host.setObjectName("host")
        host.setStyleSheet("QWidget#host { background: #6a2fb0; }")
        host.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        qtbot.addWidget(host)
        host.resize(500, 400)
        block = WaitingBlock(host)
        block.set_text("Separating stars…\n(one-time, then tweak live)")
        block.setGeometry(host.rect())
        host.show()
        qtbot.waitExposed(host)
        img = host.grab().toImage()
        lab = block.label.geometry().translated(block.pos())
        assert lab.width() > 20 and lab.height() > 20, lab
        px = QColor(img.pixel(lab.left() + 2, lab.top() + 2))
        assert px.name() == "#6a2fb0", \
            f"label paints {px.name()} (BG_1 is {theme.BG_1}) over the parent's ground"
    finally:
        app.setStyleSheet(old)
