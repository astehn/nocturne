import numpy as np
import pytest

pytest.importorskip("PySide6")
from nocturne.ui.range_handles import RangeHandles  # noqa: E402


def _drag(w, frm_x, to_x):
    """Press at normalized x `frm_x` and drag to `to_x`, mid-height.

    Events are built and sent directly rather than driven with qtbot.mouseMove,
    which is unreliable here — two tests in test_image_view.py pass only in
    full-suite ordering because of it.
    """
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication
    for typ, x, btn, held in (
        (QEvent.Type.MouseButtonPress, frm_x, Qt.MouseButton.LeftButton,
         Qt.MouseButton.LeftButton),
        (QEvent.Type.MouseMove, to_x, Qt.MouseButton.NoButton,
         Qt.MouseButton.LeftButton),
        (QEvent.Type.MouseButtonRelease, to_x, Qt.MouseButton.LeftButton,
         Qt.MouseButton.NoButton),
    ):
        pos = QPointF(w._x_to_px(x), w.height() / 2)
        QApplication.sendEvent(w, QMouseEvent(typ, pos, QPointF(0, 0), btn, held,
                                              Qt.KeyboardModifier.NoModifier))


def test_starts_at_the_whole_range(qtbot):
    w = RangeHandles()
    qtbot.addWidget(w)
    assert w.range() == (0.0, 1.0)


def test_dragging_the_low_handle_moves_only_the_low_bound(qtbot):
    w = RangeHandles()
    qtbot.addWidget(w)
    w.resize(400, 120)
    _drag(w, 0.0, 0.3)
    lo, hi = w.range()
    assert lo == pytest.approx(0.3, abs=0.03)
    assert hi == pytest.approx(1.0, abs=0.001), "the high bound moved too"


def test_dragging_the_high_handle_moves_only_the_high_bound(qtbot):
    w = RangeHandles()
    qtbot.addWidget(w)
    w.resize(400, 120)
    _drag(w, 1.0, 0.7)
    lo, hi = w.range()
    assert hi == pytest.approx(0.7, abs=0.03)
    assert lo == pytest.approx(0.0, abs=0.001), "the low bound moved too"


def test_the_handles_cannot_cross(qtbot):
    """A crossed pair would give an empty band and range_mask would return zeros
    — the tool would silently do nothing, with no control explaining why."""
    w = RangeHandles()
    qtbot.addWidget(w)
    w.resize(400, 120)
    w.set_range(0.4, 0.6)
    _drag(w, 0.4, 0.9)              # shove the LOW handle past the high one
    lo, hi = w.range()
    assert lo < hi, f"handles crossed: {lo} {hi}"


def test_set_range_clamps_into_zero_one(qtbot):
    w = RangeHandles()
    qtbot.addWidget(w)
    w.set_range(-0.5, 1.5)
    assert w.range() == (0.0, 1.0)


def test_set_range_orders_its_arguments(qtbot):
    """A preset computed from image statistics could hand them over backwards;
    swallowing that is better than producing an inverted band."""
    w = RangeHandles()
    qtbot.addWidget(w)
    w.set_range(0.8, 0.2)
    assert w.range() == (pytest.approx(0.2), pytest.approx(0.8))


def test_moving_a_handle_emits_the_new_range(qtbot):
    w = RangeHandles()
    qtbot.addWidget(w)
    w.resize(400, 120)
    seen = []
    w.rangeChanged.connect(lambda lo, hi: seen.append((lo, hi)))
    _drag(w, 0.0, 0.25)
    assert seen, "no signal"
    assert seen[-1][0] == pytest.approx(0.25, abs=0.03)


def test_set_range_does_not_emit(qtbot):
    """Programmatic changes must stay silent, or the preset combo and the
    handles drive each other in a loop."""
    w = RangeHandles()
    qtbot.addWidget(w)
    seen = []
    w.rangeChanged.connect(lambda lo, hi: seen.append((lo, hi)))
    w.set_range(0.2, 0.8)
    assert seen == []


def test_a_histogram_can_be_shown_without_changing_the_range(qtbot):
    w = RangeHandles()
    qtbot.addWidget(w)
    w.set_range(0.2, 0.8)
    w.set_histogram(np.random.default_rng(0).random((32, 32, 3)).astype(np.float32))
    assert w.range() == (pytest.approx(0.2), pytest.approx(0.8))


def test_a_mono_histogram_is_accepted(qtbot):
    """set_histogram is handed whatever the dialog is showing; a 2-D array must
    not crash it."""
    w = RangeHandles()
    qtbot.addWidget(w)
    w.set_histogram(np.random.default_rng(1).random((16, 16)).astype(np.float32))
    assert w.range() == (0.0, 1.0)


def test_painting_works_with_and_without_a_histogram(qtbot):
    """paintEvent runs on a real widget — a crash here would only show at
    runtime, since nothing else exercises the drawing code."""
    from PySide6.QtGui import QPixmap
    w = RangeHandles()
    qtbot.addWidget(w)
    w.resize(300, 100)
    w.render(QPixmap(w.size()))                       # no histogram yet
    w.set_histogram(np.random.default_rng(2).random((16, 16, 3)).astype(np.float32))
    w.set_range(0.3, 0.7)
    w.render(QPixmap(w.size()))
