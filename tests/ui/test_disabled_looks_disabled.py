"""A control locked while work runs must LOOK locked.

The busy gate disabled every input, but under the app stylesheet a disabled
slider, checkbox, curve editor, range handles and the stepper rendered
pixel-identical to enabled ones (measured 2026-10-05: 0 changed pixels), and a
dropdown changed only its text. His request was that the controls are DIMMED,
visibly — a lock you cannot see reads as a frozen app.

Each case renders a widget enabled and disabled under the real stylesheet and
asserts a meaningful share of its pixels changed, not merely that one did.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QLineEdit,
                               QRadioButton, QSlider, QSpinBox)

from nocturne.ui.curve_editor import CurveEditor
from nocturne.ui.range_handles import RangeHandles
from nocturne.ui.stepper import Stepper
from nocturne.ui.theme import build_stylesheet


@pytest.fixture
def styled(qtbot):
    app = QApplication.instance()
    old = app.styleSheet()
    app.setStyleSheet(build_stylesheet())
    yield
    app.setStyleSheet(old)


def _changed_share(qtbot, w, size) -> float:
    qtbot.addWidget(w)
    w.resize(*size)
    w.show()
    qtbot.waitExposed(w)
    a = w.grab().toImage()
    w.setEnabled(False)
    QApplication.processEvents()
    b = w.grab().toImage()
    assert (a.width(), a.height()) == (b.width(), b.height())
    total = changed = 0
    for x in range(0, a.width(), 2):
        for y in range(0, a.height(), 2):
            total += 1
            changed += a.pixel(x, y) != b.pixel(x, y)
    return changed / total


def _slider():
    s = QSlider(Qt.Orientation.Horizontal)
    s.setRange(0, 100)
    s.setValue(60)
    return s


def _check():
    c = QCheckBox("Show stars")
    c.setChecked(True)
    return c


def _radio():
    r = QRadioButton("Strong")
    r.setChecked(True)
    return r


def _combo():
    c = QComboBox()
    c.addItems(["Default", "Strong"])
    return c


def _spin():
    s = QSpinBox()
    s.setValue(42)
    return s


def _curve():
    c = CurveEditor()
    c.set_points([(0.0, 0.0), (0.4, 0.6), (1.0, 1.0)])
    return c


def _stepper():
    st = Stepper()
    st.set_stages([SimpleNamespace(id=f"s{i}", label=f"Step {i}", enabled=True,
                                   reason="") for i in range(5)])
    st.set_current(1)
    st.mark_done({"s0"})
    return st


# (factory, size, minimum share of sampled pixels that must change). The
# floors sit under the measured post-fix shares (slider 0.29, checkbox 0.24,
# radio 0.18, combo/line edit/spin box 1.0, curve 0.86, range handles 0.64,
# stepper 0.19) and far above the pre-fix ones (0.0 for every case).
CASES = {
    "slider": (_slider, (160, 24), 0.15),
    "checkbox": (_check, (130, 24), 0.08),
    "radio": (_radio, (130, 24), 0.08),
    "combo": (_combo, (150, 34), 0.5),
    "lineedit": (lambda: QLineEdit("M 42"), (150, 34), 0.5),
    "spinbox": (_spin, (90, 30), 0.5),
    "curve": (_curve, (240, 240), 0.25),
    "range_handles": (RangeHandles, (240, 110), 0.25),
    "stepper": (_stepper, (200, 180), 0.1),
}


@pytest.mark.parametrize("name", list(CASES))
def test_a_disabled_control_visibly_dims(qtbot, styled, name):
    factory, size, floor = CASES[name]
    share = _changed_share(qtbot, factory(), size)
    assert share >= floor, f"{name}: only {share:.1%} of pixels change when disabled"
