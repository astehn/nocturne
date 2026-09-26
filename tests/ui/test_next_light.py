"""D2 (Andreas, 2026-09-26): Next lights up when the step is done. ONE lit
button at a time — the next thing to press: Apply while it is green, Next once
the step's Apply says applied / no changes, or the step has none. Next is never
gated by it: unlit, it is plain like Back and still clickable.

The colour is asserted from painted pixels under the real stylesheet, not only
from the `lit` property: a property no rule reads would pass on its own."""
import pytest
from PySide6.QtGui import QColor

from nocturne.ui.theme import ACCENT, BG_3
from tests.ui.test_consistent_panels import (
    _applied_recover_core, _land, _open, _stretched, _with_stub_nr)

_DISABLED_BG = "#2a2c30"     # theme.py's QPushButton#nav:disabled background


@pytest.fixture(autouse=True)
def _styled():
    from PySide6.QtWidgets import QApplication
    from nocturne.ui.theme import build_stylesheet
    app = QApplication.instance()
    before = app.styleSheet()
    app.setStyleSheet(build_stylesheet())
    yield
    app.setStyleSheet(before)


def _painted(win, qtbot) -> str:
    """Which of lit / plain / disabled Next's body is PAINTED in: the pixel
    left of the centred label, matched to the nearest of the three fills."""
    qtbot.wait(10)
    img = win._next_btn.grab().toImage()
    px = img.pixelColor(10, img.height() // 2)
    fills = {"lit": QColor(ACCENT), "plain": QColor(BG_3), "disabled": QColor(_DISABLED_BG)}

    def dist(c):
        return sum((a - b) ** 2 for a, b in zip(px.getRgb()[:3], c.getRgb()[:3]))
    best = min(fills, key=lambda k: dist(fills[k]))
    assert dist(fills[best]) < 30, f"Next painted {px.name()}, none of the three fills"
    return best


def _case(qtbot, tmp_path, case):
    if case == "import":
        win = _open(qtbot, tmp_path)
        assert win.current_stage_id() == "load"
    elif case == "enhancements":
        win = _open(qtbot, tmp_path)
        win._go_to_id("enhancements", user_initiated=False); qtbot.wait(20)
    elif case == "pending":
        win = _stretched(qtbot, tmp_path)
        win._go_to_id("recover_core", user_initiated=False); qtbot.wait(20)
        win._panel.recover_slider.setValue(30); qtbot.wait(20)
    elif case == "not_run":
        win = _stretched(qtbot, tmp_path)
        win._go_to_id("green_fringe", user_initiated=False); qtbot.wait(20)
    elif case == "no_change":
        win = _stretched(qtbot, tmp_path)
        win._go_to_id("recover_core", user_initiated=False); qtbot.wait(20)
    elif case == "applied":
        win = _applied_recover_core(qtbot, tmp_path)
        assert not win._panel.apply_btn.isEnabled(), "precondition: verified unchanged"
    elif case == "applied_live":
        # Ruling R13: a commit is held but the controls could not be verified
        # as it (revisited at 0 over 0.30), so Apply is live and plain.
        win = _applied_recover_core(qtbot, tmp_path)
        win._go_to_id("levels", user_initiated=False); qtbot.wait(20)
        win._go_to_id("recover_core", user_initiated=False); qtbot.wait(20)
        btn = win._panel.apply_btn
        assert btn.state() == "applied" and btn.isEnabled(), "precondition"
    elif case == "unavailable":
        # Apply cannot be pressed (Crop before a box is placed): lighting
        # Next is the only way anything is both lit and pressable here.
        win = _open(qtbot, tmp_path)
        win._go_to_id("crop", user_initiated=False); qtbot.wait(20)
        assert not win._panel.apply_btn.isEnabled(), "precondition: no box yet"
    elif case == "export":
        win = _open(qtbot, tmp_path)
        win._go_to_id("export", user_initiated=False); qtbot.wait(20)
    elif case == "busy":
        win = _applied_recover_core(qtbot, tmp_path)
        win._set_busy(True, "probe")
    else:
        raise ValueError(case)
    return win


@pytest.mark.parametrize("case,lit,painted,enabled", [
    ("pending", False, "plain", True),
    ("not_run", False, "plain", True),
    ("applied", True, "lit", True),
    ("applied_live", True, "lit", True),
    ("no_change", True, "lit", True),
    ("import", True, "lit", True),
    ("enhancements", True, "lit", True),
    ("unavailable", True, "lit", True),
    ("export", False, "disabled", False),
    ("busy", False, "disabled", False),
])
def test_next_is_lit_only_when_the_step_is_done(qtbot, tmp_path, case, lit, painted, enabled):
    win = _case(qtbot, tmp_path, case)
    assert win._next_btn.property("lit") == ("true" if lit else "false")
    assert win._next_btn.isEnabled() is enabled
    assert win._next_btn.isVisible()
    assert _painted(win, qtbot) == painted
    apply_btn = getattr(win._panel, "apply_btn", None)
    if case in ("pending", "not_run"):
        # The other half of "one lit button": Apply is the green one.
        assert apply_btn.property("pending") == "true" and apply_btn.isEnabled()


def test_an_unlit_next_is_still_clickable_and_still_asks(qtbot, tmp_path):
    win = _case(qtbot, tmp_path, "pending")
    assert win._next_btn.property("lit") == "false" and win._next_btn.isEnabled()
    asked = []
    win._ask_pending = lambda label: asked.append(label) or "cancel"
    win._next_btn.click()
    assert asked, "the unapplied-changes prompt no longer guards Next"
    assert win.current_stage_id() == "recover_core"
    win._ask_pending = lambda label: "discard"
    win._next_btn.click()
    assert win.current_stage_id() != "recover_core", "an unlit Next did not navigate"


def test_not_run_next_moves_on_without_asking(qtbot, tmp_path):
    """His call: an untouched optional step keeps Apply green and Next plain —
    and skipping it is one click, no prompt."""
    win = _case(qtbot, tmp_path, "not_run")
    asked = []
    win._ask_pending = lambda label: asked.append(label) or "cancel"
    win._next_btn.click()
    assert not asked and win.current_stage_id() != "green_fringe"


def test_the_light_never_moves_next(qtbot, tmp_path):
    win = _case(qtbot, tmp_path, "pending")
    btn = win._next_btn
    plain = (btn.mapTo(win, btn.rect().topLeft()), btn.size())
    win._panel.apply_btn.click(); qtbot.wait(20)
    assert btn.property("lit") == "true", "precondition"
    assert (btn.mapTo(win, btn.rect().topLeft()), btn.size()) == plain


def test_busy_ends_with_the_light_restored(qtbot, tmp_path):
    win = _case(qtbot, tmp_path, "busy")
    assert win._next_btn.property("lit") == "false"
    win._set_busy(False)
    assert win._next_btn.property("lit") == "true"
    assert _painted(win, qtbot) == "lit"


@pytest.mark.parametrize("async_", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("sid", ["recover_core", "noise_sharpen"])
def test_pressing_apply_moves_the_light_from_apply_to_next(
        qtbot, tmp_path, monkeypatch, sid, async_):
    win = _stretched(qtbot, tmp_path)
    _with_stub_nr(win, monkeypatch)     # external tools fail loudly
    win._async_enabled = async_
    win._go_to_id(sid, user_initiated=False); qtbot.wait(20)
    if sid == "recover_core":
        win._panel.recover_slider.setValue(30); qtbot.wait(20)
    apply_btn = win._panel.apply_btn
    assert apply_btn.state() in ("pending", "not_run"), apply_btn.state()
    assert apply_btn.property("pending") == "true"
    assert win._next_btn.property("lit") == "false" and _painted(win, qtbot) == "plain"
    n = len(win.project.entries())
    apply_btn.click()
    _land(qtbot, win)
    qtbot.waitUntil(lambda: win._next_btn.property("lit") == "true", timeout=10000)
    assert len(win.project.entries()) == n + 1, "fixture: Apply did not commit"
    assert apply_btn.state() == "applied" and apply_btn.property("pending") == "false"
    assert _painted(win, qtbot) == "lit"


def test_moving_a_slider_on_an_applied_step_takes_the_light_back(qtbot, tmp_path):
    win = _case(qtbot, tmp_path, "applied")
    assert win._next_btn.property("lit") == "true", "precondition"
    win._panel.recover_slider.setValue(50); qtbot.wait(20)
    assert win._panel.apply_btn.property("pending") == "true"
    assert win._next_btn.property("lit") == "false"
    assert _painted(win, qtbot) == "plain"
    assert win._next_btn.isEnabled()
