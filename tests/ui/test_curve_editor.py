import numpy as np
import pytest

pytest.importorskip("PySide6")
from nocturne.ui.curve_editor import CurveEditor  # noqa: E402


def test_starts_at_identity(qtbot):
    w = CurveEditor()
    qtbot.addWidget(w)
    assert w.points() == [(0.0, 0.0), (1.0, 1.0)]


def test_set_points_round_trip_and_corner_enforcement(qtbot):
    w = CurveEditor()
    qtbot.addWidget(w)
    w.set_points([(0.0, 0.0), (0.5, 0.7), (1.0, 1.0)])
    assert w.points() == [(0.0, 0.0), (0.5, 0.7), (1.0, 1.0)]


def test_add_point_sorts_and_clamps(qtbot):
    w = CurveEditor()
    qtbot.addWidget(w)
    w.add_point(0.6, 0.4)
    w.add_point(0.3, 0.2)
    xs = [p[0] for p in w.points()]
    assert xs == sorted(xs)
    assert w.points()[0] == (0.0, 0.0) and w.points()[-1] == (1.0, 1.0)


def test_min_gap_drops_too_close_interior(qtbot):
    w = CurveEditor()
    qtbot.addWidget(w)
    w.set_points([(0.0, 0.0), (0.5, 0.5), (0.505, 0.6), (1.0, 1.0)])
    xs = [p[0] for p in w.points()]
    assert len(xs) == 3            # the 0.505 point was too close to 0.5 -> dropped


def test_remove_interior_but_not_corner(qtbot):
    w = CurveEditor()
    qtbot.addWidget(w)
    w.set_points([(0.0, 0.0), (0.5, 0.7), (1.0, 1.0)])
    w.remove_point(0)              # corner -> refused
    assert len(w.points()) == 3
    w.remove_point(1)              # interior -> removed
    assert w.points() == [(0.0, 0.0), (1.0, 1.0)]


def test_reset_restores_identity(qtbot):
    w = CurveEditor()
    qtbot.addWidget(w)
    w.set_points([(0.0, 0.0), (0.4, 0.6), (1.0, 1.0)])
    w.reset()
    assert w.points() == [(0.0, 0.0), (1.0, 1.0)]


def test_curve_changed_emits(qtbot):
    w = CurveEditor()
    qtbot.addWidget(w)
    with qtbot.waitSignal(w.curveChanged, timeout=500):
        w.add_point(0.5, 0.6)


def test_set_histogram_accepts_mono_and_rgb(qtbot):
    w = CurveEditor()
    qtbot.addWidget(w)
    w.set_histogram(np.random.default_rng(0).random((16, 16)).astype(np.float32))
    w.set_histogram(np.random.default_rng(1).random((16, 16, 3)).astype(np.float32))
    w.grab()   # force a paint with histogram present -> must not raise


def test_paint_without_histogram(qtbot):
    w = CurveEditor()
    qtbot.addWidget(w)
    w.resize(240, 240)
    w.grab()   # paint with no histogram set -> must not raise


# --- draggable endpoints (2026-08-17) ---------------------------------------

def _drag(ed, frm, to):
    """Press on `frm` and move to `to`, both in normalized curve coords."""
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication

    def px(p):
        return ed._to_px(*p)

    for typ, pos, btn, held in (
        (QEvent.Type.MouseButtonPress, frm, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton),
        (QEvent.Type.MouseMove, to, Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton),
        (QEvent.Type.MouseButtonRelease, to, Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton),
    ):
        QApplication.sendEvent(ed, QMouseEvent(typ, px(pos), QPointF(0, 0), btn, held,
                                               Qt.KeyboardModifier.NoModifier))


def test_the_low_endpoint_can_be_dragged_to_set_a_black_point(qtbot):
    """Reported 2026-08-17: setting a black or white point was impossible. The
    editor refused to move index 0 or the last index, and sanitize_points put
    them back at the corners anyway. This is the commonest curves move there is."""
    ed = CurveEditor()
    qtbot.addWidget(ed)
    ed.resize(300, 300)
    _drag(ed, (0.0, 0.0), (0.25, 0.0))
    x, y = ed.points()[0]
    assert x == pytest.approx(0.25, abs=0.02), f"low endpoint stayed at {x}"
    assert y == pytest.approx(0.0, abs=0.02)


def test_the_high_endpoint_can_be_dragged_to_set_a_white_point(qtbot):
    ed = CurveEditor()
    qtbot.addWidget(ed)
    ed.resize(300, 300)
    _drag(ed, (1.0, 1.0), (0.8, 1.0))
    x, _y = ed.points()[-1]
    assert x == pytest.approx(0.8, abs=0.02), f"high endpoint stayed at {x}"


def test_an_endpoint_cannot_be_dragged_past_its_neighbour(qtbot):
    """Ordering is what build_lut relies on; a crossed pair would give a
    non-monotonic LUT or a divide by zero."""
    ed = CurveEditor()
    qtbot.addWidget(ed)
    ed.resize(300, 300)
    ed.set_points([(0.0, 0.0), (0.5, 0.5), (1.0, 1.0)])
    _drag(ed, (0.0, 0.0), (0.9, 0.2))       # try to shove it past the mid point
    xs = [x for x, _ in ed.points()]
    assert xs == sorted(xs), f"points crossed: {xs}"
    assert xs[0] < xs[1], "the endpoint overtook its neighbour"


def test_dragging_an_endpoint_survives_being_committed(qtbot):
    """set_points runs sanitize_points; the drag must still be there afterwards.
    This is the half that made the old behaviour invisible in the editor's own
    state but restored on the next edit."""
    ed = CurveEditor()
    qtbot.addWidget(ed)
    ed.set_points([(0.3, 0.0), (1.0, 1.0)])
    assert ed.points()[0][0] == pytest.approx(0.3)
    ed.add_point(0.6, 0.7)                   # any later edit re-sanitizes
    assert ed.points()[0][0] == pytest.approx(0.3), "the black point was reset"


def test_reset_returns_the_identity_curve(qtbot):
    ed = CurveEditor()
    qtbot.addWidget(ed)
    ed.set_points([(0.3, 0.1), (0.8, 0.9)])
    ed.reset()
    assert ed.points() == [(0.0, 0.0), (1.0, 1.0)]


# --- precision: keyboard nudge and a numeric readout (2026-08-17) ------------

def test_arrow_keys_nudge_the_selected_point(qtbot):
    """Mouse-only in a 240 px widget means one pixel is about 0.004, so fine
    work was guesswork. A nudge is one 8-bit level — the smallest step the
    output can actually represent."""
    from PySide6.QtCore import Qt
    ed = CurveEditor()
    qtbot.addWidget(ed)
    ed.resize(300, 300)
    ed.set_points([(0.0, 0.0), (0.5, 0.5), (1.0, 1.0)])
    ed.select_point(1)
    before = ed.points()[1]
    qtbot.keyClick(ed, Qt.Key.Key_Up)
    after = ed.points()[1]
    assert after[1] > before[1], "Up did not raise the output"
    assert after[1] - before[1] == pytest.approx(1 / 255, abs=1e-6)
    assert after[0] == pytest.approx(before[0]), "Up moved it sideways"


def test_shift_arrow_takes_a_coarser_step(qtbot):
    from PySide6.QtCore import Qt
    ed = CurveEditor()
    qtbot.addWidget(ed)
    ed.set_points([(0.0, 0.0), (0.5, 0.5), (1.0, 1.0)])
    ed.select_point(1)
    qtbot.keyClick(ed, Qt.Key.Key_Right, Qt.KeyboardModifier.ShiftModifier)
    assert ed.points()[1][0] - 0.5 == pytest.approx(10 / 255, abs=1e-6)


def test_nudging_an_endpoint_sets_a_black_point_without_crossing(qtbot):
    """The endpoint is nudgeable like any point, and still cannot overtake its
    neighbour."""
    from PySide6.QtCore import Qt
    ed = CurveEditor()
    qtbot.addWidget(ed)
    ed.set_points([(0.0, 0.0), (0.02, 0.5), (1.0, 1.0)])
    ed.select_point(0)
    for _ in range(60):                       # push hard at the neighbour
        qtbot.keyClick(ed, Qt.Key.Key_Right)
    xs = [x for x, _ in ed.points()]
    assert xs == sorted(xs) and xs[0] < xs[1], f"crossed: {xs}"


def test_the_readout_reports_the_selected_point(qtbot):
    """Photoshop shows input/output for the point you are holding; without it
    there is no way to know what value you actually set."""
    ed = CurveEditor()
    qtbot.addWidget(ed)
    ed.set_points([(0.0, 0.0), (0.25, 0.6), (1.0, 1.0)])
    ed.select_point(1)
    text = ed.readout_text()
    assert "0.25" in text and "0.60" in text, text


def test_the_readout_is_empty_with_nothing_selected(qtbot):
    ed = CurveEditor()
    qtbot.addWidget(ed)
    assert ed.readout_text() == ""


def test_the_plot_area_is_square_whatever_shape_the_widget_is(qtbot):
    """A tone curve maps [0,1] to [0,1] — it must be drawn square.

    Measured in Andreas' configuration the inline editor is 336 x 240 and the
    plot filled it, so the identity line was not at 45 degrees and a horizontal
    drag moved 1.4x further per pixel than a vertical one. Hand and curve
    disagreed, which is a large part of "difficult to see and control what you
    are actually doing".
    """
    from nocturne.ui.curve_editor import CurveEditor
    ed = CurveEditor()
    qtbot.addWidget(ed)
    for w, h in ((336, 240), (240, 336), (700, 700), (900, 300)):
        ed.resize(w, h)
        _ox, _oy, pw, ph = ed._plot_rect()
        assert pw == ph, f"plot {pw}x{ph} in a {w}x{h} widget is not square"


def test_the_square_plot_is_centred_in_the_widget(qtbot):
    """Otherwise it sits against one edge and the panel looks broken."""
    from nocturne.ui.curve_editor import CurveEditor
    ed = CurveEditor()
    qtbot.addWidget(ed)
    ed.resize(400, 240)
    ox, oy, pw, ph = ed._plot_rect()
    assert abs((400 - pw) / 2 - ox) <= 1, (ox, pw)
    assert abs((240 - ph) / 2 - oy) <= 1, (oy, ph)


def test_a_click_still_lands_where_the_user_aimed_after_the_change(qtbot):
    """The hit-testing and the drawing must use the SAME rectangle. If the plot
    is centred but clicks are still mapped from the widget corner, every point
    lands offset — which would be worse than the stretch it replaced."""
    from nocturne.ui.curve_editor import CurveEditor
    ed = CurveEditor()
    qtbot.addWidget(ed)
    ed.resize(400, 240)
    ox, oy, pw, ph = ed._plot_rect()
    # the centre of the plot must map to (0.5, 0.5) in curve coordinates
    x, y = ed._to_norm(ox + pw / 2, oy + ph / 2)
    assert abs(x - 0.5) < 0.01 and abs(y - 0.5) < 0.01, (x, y)
    # and back again
    pt = ed._to_px(0.5, 0.5)
    assert abs(pt.x() - (ox + pw / 2)) < 1.0 and abs(pt.y() - (oy + ph / 2)) < 1.0
