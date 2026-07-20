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
