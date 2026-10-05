"""BusyGate on its own: what it takes, and that it gives back exactly that."""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QLabel, QLineEdit,
                               QPushButton, QRadioButton, QSlider, QSpinBox, QVBoxLayout,
                               QWidget)

from nocturne.ui.busy_gate import KEEP_LIVE, BusyGate, keep_live
from nocturne.ui.curve_editor import CurveEditor


def _panel(qtbot, *widgets):
    root = QWidget()
    lay = QVBoxLayout(root)
    inner = QWidget()                       # nested, as step panels are
    inner_lay = QVBoxLayout(inner)
    for i, w in enumerate(widgets):
        (lay if i % 2 else inner_lay).addWidget(w)
    lay.addWidget(inner)
    qtbot.addWidget(root)
    return root


_KINDS = [
    lambda: QSlider(Qt.Orientation.Horizontal),
    lambda: QPushButton("Apply"),
    lambda: QCheckBox("x"),
    lambda: QRadioButton("r"),
    lambda: QComboBox(),
    lambda: QSpinBox(),
    lambda: QDoubleSpinBox(),
    lambda: QLineEdit(),
    lambda: CurveEditor(),
]


_IDS = ["slider", "push", "check", "radio", "combo", "spin", "dspin", "line", "curve"]


@pytest.mark.parametrize("make", _KINDS, ids=_IDS)
def test_every_input_type_is_swept_and_given_back(qtbot, make):
    w = make()
    root = _panel(qtbot, w)
    gate = BusyGate()
    gate.close(root)
    assert gate.is_closed and w.isEnabled() is False
    gate.open()
    assert not gate.is_closed and w.isEnabled() is True


def test_a_root_that_is_itself_an_input_is_swept(qtbot):
    btn = QPushButton("Apply")
    qtbot.addWidget(btn)
    gate = BusyGate()
    gate.close(btn)
    assert btn.isEnabled() is False
    gate.open()
    assert btn.isEnabled() is True


def test_a_label_is_not_an_input(qtbot):
    label = QLabel("<a href='#'>Help</a>")
    root = _panel(qtbot, label)
    BusyGate().close(root)
    assert label.isEnabled() is True


def test_a_widget_already_off_stays_off(qtbot):
    off, on = QPushButton("off"), QSlider()
    off.setEnabled(False)
    root = _panel(qtbot, off, on)
    gate = BusyGate()
    gate.close(root)
    gate.open()
    assert off.isEnabled() is False
    assert on.isEnabled() is True


def test_keep_live_is_untouched(qtbot):
    cancel = keep_live(QPushButton("Cancel"))
    other = QPushButton("Apply")
    root = _panel(qtbot, cancel, other)
    assert cancel.property(KEEP_LIVE) is True
    gate = BusyGate()
    gate.close(root)
    assert cancel.isEnabled() is True and other.isEnabled() is False
    cancel.setEnabled(False)              # its owner turns it off meanwhile
    gate.open()
    assert cancel.isEnabled() is False, "open() restored a widget it never took"


def test_nested_close_adds_rather_than_replaces(qtbot):
    first = QSlider()
    root_a = _panel(qtbot, first)
    gate = BusyGate()
    gate.close(root_a)
    second = QComboBox()
    root_b = _panel(qtbot, second)        # a panel built while closed
    gate.close(root_b)
    assert first.isEnabled() is False and second.isEnabled() is False
    gate.open()
    assert first.isEnabled() is True and second.isEnabled() is True


def test_closing_again_sweeps_a_widget_switched_on_meanwhile(qtbot):
    btn = QPushButton("Reset step")
    btn.setEnabled(False)
    root = _panel(qtbot, btn)
    gate = BusyGate()
    gate.close(root)
    btn.setEnabled(True)                  # some sync turned it on mid-run
    gate.close(root)
    assert btn.isEnabled() is False
    gate.open()
    assert btn.isEnabled() is True


def test_a_deleted_widget_is_skipped_on_open(qtbot):
    import shiboken6
    doomed, kept = QPushButton("old"), QSlider()
    root = _panel(qtbot, doomed, kept)
    gate = BusyGate()
    gate.close(root)
    shiboken6.delete(doomed)              # the panel was rebuilt meanwhile
    gate.open()                           # must not raise
    assert kept.isEnabled() is True


def test_open_with_nothing_closed_is_a_no_op(qtbot):
    off, on = QPushButton("off"), QPushButton("on")
    off.setEnabled(False)
    root = _panel(qtbot, off, on)
    gate = BusyGate()
    gate.open()
    assert not gate.is_closed
    assert off.isEnabled() is False and on.isEnabled() is True


def test_open_twice_gives_back_once(qtbot):
    btn = QPushButton("Apply")
    root = _panel(qtbot, btn)
    gate = BusyGate()
    gate.close(root)
    gate.open()
    btn.setEnabled(False)                 # legitimately off after the run
    gate.open()
    assert btn.isEnabled() is False


def test_a_widget_detached_from_its_window_is_skipped_on_open(qtbot):
    """A rebuilt panel: the old one is taken out of the window at once and
    deleted only later."""
    old, kept = QPushButton("old Apply"), QSlider()
    holder = QWidget()
    lay = QVBoxLayout(holder)
    lay.addWidget(old)
    root = _panel(qtbot, holder, kept)
    gate = BusyGate()
    gate.close(root)
    holder.setParent(None)                # set_panel: detached, deleteLater pending
    qtbot.addWidget(holder)
    gate.open()
    assert old.isEnabled() is False
    assert kept.isEnabled() is True
