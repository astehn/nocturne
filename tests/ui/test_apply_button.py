import pytest
from PySide6.QtWidgets import QWidget, QVBoxLayout

from nocturne.ui.apply_button import STATES, ApplyButton


def _btn(qtbot, label="Apply Levels", look="A", width=380):
    host = QWidget(); lay = QVBoxLayout(host)
    b = ApplyButton(label, look=look)
    lay.addWidget(b)
    qtbot.addWidget(host)
    host.resize(width, 200); host.show(); qtbot.waitExposed(host)
    # qtbot.addWidget() only keeps a weakref (for teardown), and `host` has no
    # C++ parent of its own, so Python owns it — without another strong
    # reference, host is garbage-collected the moment this helper returns,
    # which deletes its child `b` at the C++ level too ("libshiboken: Internal
    # C++ object already deleted" on the very next call). Tie host's lifetime
    # to the button we actually return.
    b._host = host
    return b


@pytest.mark.parametrize("look", ["A", "B"])
def test_the_height_never_changes_with_state(qtbot, look):
    b = _btn(qtbot, look=look)
    heights = set()
    for s in STATES:
        b.set_state(s); qtbot.wait(5)
        heights.add(b.height())
    assert len(heights) == 1


def test_look_a_is_taller_than_look_b(qtbot):
    assert _btn(qtbot, look="A").height() > _btn(qtbot, look="B").height()


@pytest.mark.parametrize("state,green,enabled,words", [
    ("pending", True, True, "not applied"),
    ("not_run", True, True, "not run"),
    ("applied", False, True, "applied"),
    ("no_change", False, False, "no changes"),
    ("busy", False, False, ""),
])
@pytest.mark.parametrize("look", ["A", "B"])
def test_each_state_reads_and_colours_as_ruled(qtbot, look, state, green, enabled, words):
    b = _btn(qtbot, look=look)
    b.set_state(state)
    assert b.state() == state
    assert b.property("pending") == ("true" if green else "false")
    assert b.isEnabled() is enabled
    assert words in b.status_text()
    assert b.label_text() == "Apply Levels"


@pytest.mark.parametrize("label", ["Apply Deconvolution", "Apply De-green Stars", "Apply Linear Denoise"])
def test_long_names_fit_with_the_chip(qtbot, label):
    """Review Focus 4: look B must not clip the step name against the chip."""
    b = _btn(qtbot, label=label, look="B", width=380)
    b.set_state("pending")
    assert b.label_fits(), f"{label!r} is clipped next to the chip at 380 px"


def test_unknown_state_is_refused(qtbot):
    with pytest.raises(ValueError):
        _btn(qtbot).set_state("maybe")
