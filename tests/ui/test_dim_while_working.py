"""While a step works, none of its controls can be touched; afterwards each is
exactly as it was (spec B1/B2, audit 2026-10-05).

The old gate swept push buttons only: sliders, dropdowns, checkboxes and the
curve editor of the running step stayed live, a panel rebuilt mid-run was never
swept, and a star split landing switched its slider and Apply on while another
split still ran — an Apply that then silently did nothing.

Every run is held on the worker (`Holder`) so "during" is inspectable.
"""
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import (QAbstractButton, QAbstractSlider, QAbstractSpinBox,
                               QApplication, QCheckBox, QComboBox, QLineEdit, QWidget)

import nocturne.ui.main_window as mw
from nocturne.core import tasks
from nocturne.core.image import AstroImage
from nocturne.ui.curve_editor import CurveEditor
from tests.ui.test_busy_correctness import _idle, _make as _make_held, _press_apply

# The spec's list (B1), spelled out here rather than imported from the gate, so
# a type dropped from the gate fails this file instead of shrinking it.
_INPUTS = (QAbstractSlider, QAbstractButton, QComboBox, QAbstractSpinBox, QLineEdit,
           CurveEditor)
_KEEP_LIVE = "busyGateKeepLive"


def _make(qtbot, tmp_path, monkeypatch, **k):
    """`_make`, plus: a failed assertion must not leave a held job to land on a
    deleted window later. pytest-qt closes widgets BEFORE fixture teardown, so
    the drain rides on the window's own close."""
    box = {}
    real_add = qtbot.addWidget

    def add(widget, **kw):
        def drain(w):
            h = box.get("h")
            if h is not None:
                h.release()
            try:
                qtbot.waitUntil(lambda: not w._busy, timeout=5000)
            except Exception:
                pass
        real_add(widget, before_close_func=drain)
    monkeypatch.setattr(qtbot, "addWidget", add)
    win, h = _make_held(qtbot, tmp_path, monkeypatch, **k)
    monkeypatch.setattr(qtbot, "addWidget", real_add)
    box["h"] = h
    return win, h


def _controls(win):
    out = []
    for root in (win._panel, win._side.action_slot):
        for w in [root] + root.findChildren(QWidget):
            if isinstance(w, _INPUTS) and not w.property(_KEEP_LIVE) and w not in out:
                out.append(w)
    return out


def _live(win):
    return [f"{type(w).__name__}:{getattr(w, 'text', lambda: '')()}"
            for w in _controls(win) if w.isEnabled()]


def _decoys(win):
    """One control on and one legitimately off: the off one must stay off."""
    on, off = QCheckBox("decoy on", win._panel), QCheckBox("decoy off", win._panel)
    off.setEnabled(False)
    return on, off


def _derived(win):
    """Controls the step re-derives from its state after a commit — a landed
    Apply legitimately changes these (Apply goes off, Reset step on, the
    Background "Show what was removed" box becomes available)."""
    return {id(getattr(win._panel, n, None))
            for n in ("apply_btn", "primary_action", "reset_step_btn", "visual_btn",
                      "show_model_check")}


def _fake_layers(base):
    return (AstroImage(base.data * 0.9, is_linear=False, metadata={}),
            AstroImage(base.data * 0.1, is_linear=False, metadata={}), "StarNet2")


def _work(mode, result):
    """The held job's body for a run that succeeds, raises, or is cancelled."""
    if mode == "fail":
        raise RuntimeError("boom")
    if mode == "cancel":
        tasks.current().check()          # cancelled before release: raises
    return result


class _FakeStep:
    def __init__(self, real, mode):
        self._real, self._mode = real, mode

    def apply(self, base, option):
        return _work(self._mode, base.copy())

    def __getattr__(self, name):
        return getattr(self._real, name)


def _patch_step(win, monkeypatch, mode):
    real = win._step_for
    monkeypatch.setattr(win, "_step_for", lambda sid: _FakeStep(real(sid), mode))


def _patch_split(win, monkeypatch, mode):
    monkeypatch.setattr(mw.MainWindow, "_split_tagged",
                        lambda self, base: _work(mode, _fake_layers(base)))


# ------------------------------------------------- how each stage's work starts
# Not here, and why: Import has no Apply and no entry work; Crop's Apply,
# Rotate and Flip and De-green Sky's Apply run synchronously on the UI thread
# (nothing to hold — the crop box gets its own test below).
_PREP = {
    "levels": lambda win: win._panel.white_slider.setValue(80),
    "curves": lambda win: win._panel.curve_editor.set_points(
        [(0.0, 0.0), (0.5, 0.6), (1.0, 1.0)]),
    "local_contrast": lambda win: win._panel.lc_slider.setValue(40),
    "recover_core": lambda win: win._panel.recover_slider.setValue(40),
}
_APPLY_STAGES = ["background", "color", "deconvolution", "stretch", "recover_core",
                 "levels", "curves", "noise_sharpen", "local_contrast"]
_SPLIT_STAGES = ["green_fringe", "star_reduction", "saturation"]
_OTHER_STAGES = ["enhancements", "export"]


def _arrive(qtbot, win, h, monkeypatch, sid):
    """Go to the stage and let any entry work land, so the panel is at rest."""
    win._go_to_id(sid, user_initiated=False)
    h.release()
    _idle(qtbot, win)
    if sid in _PREP:
        _PREP[sid](win)
        qtbot.wait(150)


def _start(qtbot, win, monkeypatch, tmp_path, sid, mode):
    if sid in _APPLY_STAGES:
        _patch_step(win, monkeypatch, mode)
        _press_apply(win)
    elif sid == "green_fringe":
        _patch_split(win, monkeypatch, mode)
        win._splits.clear()
        win._fringe_layers = None
        win._setup_green_fringe()
    elif sid == "star_reduction":
        _patch_split(win, monkeypatch, mode)
        win._splits.clear()
        win._sr_layers = None
        win._setup_star_reduction()
    elif sid == "saturation":
        _patch_split(win, monkeypatch, mode)
        win._splits.clear()
        win._panel.neb_slider.setValue(30)
    elif sid == "enhancements":
        monkeypatch.setattr(win, "_remove_stars",
                            lambda base: _work(mode, _fake_layers(base)[:2]))
        win._enhance("Star Colour")
    elif sid == "export":
        out = str(tmp_path / "out.tiff")
        monkeypatch.setattr(mw.file_dialogs, "save_file", lambda *a, **k: (out, ""))
        real_save = mw.save_tiff
        monkeypatch.setattr(mw, "save_tiff",
                            lambda *a, **k: _work(mode, None) or real_save(*a, **k))
        win.export_final("TIFF")
    qtbot.wait(30)


@pytest.mark.parametrize("mode", ["ok", "fail", "cancel"])
@pytest.mark.parametrize("sid", _APPLY_STAGES + _SPLIT_STAGES + _OTHER_STAGES)
def test_every_control_of_a_working_step_is_off_and_comes_back_as_it_was(
        qtbot, tmp_path, monkeypatch, sid, mode):
    if sid == "background":
        monkeypatch.setattr(mw, "graxpert_valid", lambda s: True)
    win, h = _make(qtbot, tmp_path, monkeypatch)
    _arrive(qtbot, win, h, monkeypatch, sid)
    assert win.current_stage_id() == sid and not win._busy
    decoy_on, decoy_off = _decoys(win)
    widgets = _controls(win)
    before = [w.isEnabled() for w in widgets]
    real_on = sum(b for w, b in zip(widgets, before)
                  if w is not decoy_on and w is not decoy_off)
    # Star Reduction at rest has ONE real input on — its slider; Apply and
    # Reset step wait for an edit, and an edit made here is undone when _start
    # re-enters the step to begin the split, so it cannot be staged.
    floor = 1 if sid == "star_reduction" else 2
    assert real_on >= floor, f"fixture: too few controls on to prove anything ({sid})"
    panel = win._panel
    held = len(h.events)

    _start(qtbot, win, monkeypatch, tmp_path, sid, mode)
    assert win._busy and len(h.events) == held + 1, f"{sid}: no held run started"
    assert win._panel is panel
    assert _live(win) == []
    if mode == "cancel":
        win._cancel_active()

    h.release(); _idle(qtbot, win)
    assert win._panel is panel
    after = [w.isEnabled() for w in widgets]
    assert decoy_on.isEnabled() is True
    assert decoy_off.isEnabled() is False, "the gate restored a control it never took"
    derived = _derived(win)
    readiness = {id(getattr(panel, n, None)) for n in ("fringe_slider", "sr_slider")}
    for w, b, a in zip(widgets, before, after):
        if (mode == "ok" or sid == "saturation") and id(w) in derived:
            # (Saturation: the nebula move that starts its split is itself an
            # edit, so Apply and Reset step read pending however it ends.)
            continue
        if mode != "ok" and sid in ("green_fringe", "star_reduction") and (
                id(w) in readiness or w is panel.apply_btn):
            # A failed or cancelled split leaves nothing to preview or commit.
            assert a is False, f"{sid}: {type(w).__name__} on with no split"
            continue
        assert a == b, f"{sid}/{mode}: {type(w).__name__} {w.text() if hasattr(w, 'text') else ''} {b} -> {a}"
    # What the gate gave back agrees with the step's own reading of itself.
    win._sync_step_controls()
    assert [w.isEnabled() for w in widgets] == after


# ------------------------------------------------- star splits: readiness, not setEnabled
@pytest.mark.parametrize("sid, slider", [("green_fringe", "fringe_slider"),
                                         ("star_reduction", "sr_slider")])
def test_a_panel_rebuilt_mid_split_stays_off_until_the_last_split_lands(
        qtbot, tmp_path, monkeypatch, sid, slider):
    """Audit C/E: the FIRST split landing switched slider + Apply on while the
    second still ran; Apply then did nothing (it returns on busy)."""
    win, h = _make(qtbot, tmp_path, monkeypatch)
    win._go_to_id(sid, user_initiated=False); qtbot.wait(30)
    assert win._busy and len(h.events) == 1
    win._rebuild_panel(); qtbot.wait(30)        # Settings OK / a solve landing did this
    assert _live(win) == [], "the panel built mid-run is live"

    h.release(0)
    qtbot.waitUntil(lambda: getattr(win, "_fringe_ready" if sid == "green_fringe"
                                    else "_sr_ready"), timeout=5000)
    qtbot.wait(30)
    assert win._busy
    assert getattr(win._panel, slider).isEnabled() is False
    assert win._panel.apply_btn.isEnabled() is False
    assert _live(win) == []

    h.release(); _idle(qtbot, win)
    s = getattr(win._panel, slider)
    assert s.isEnabled() is True
    s.setValue(40); qtbot.wait(150)      # and the step can now be used
    assert win._panel.apply_btn.isEnabled() is True


def test_saturation_sliders_dim_during_its_star_separation(qtbot, tmp_path, monkeypatch):
    """His call (2026-10-05): one rule, no exceptions."""
    win, h = _make(qtbot, tmp_path, monkeypatch)
    win._go_to_id("saturation", user_initiated=False); qtbot.wait(30)
    assert not win._busy
    win._panel.neb_slider.setValue(30); qtbot.wait(30)
    assert win._busy
    assert win._panel.sat_slider.isEnabled() is False
    assert win._panel.neb_slider.isEnabled() is False
    h.release(); _idle(qtbot, win)
    assert win._panel.sat_slider.isEnabled() is True
    assert win._panel.neb_slider.isEnabled() is True


# ------------------------------------------------- a panel rebuilt by a landing job
def test_a_solve_landing_mid_run_rebuilds_a_dimmed_panel(qtbot, tmp_path, monkeypatch):
    """Review Focus 2: plate solve lands on Levels and rebuilds the panel while
    another job still runs — the new panel is off until busy ends."""
    win, h = _make(qtbot, tmp_path, monkeypatch)
    win._go_to_id("levels", user_initiated=False); qtbot.wait(30)
    shape = [(type(w).__name__, w.isEnabled()) for w in _controls(win)]
    monkeypatch.setattr(win, "_solve_current",
                        lambda img: (SimpleNamespace(solved=True, message=""), []))
    monkeypatch.setattr(win, "_show_annotations", lambda *a: None)
    monkeypatch.setattr(win, "_update_solve_result_card", lambda *a, **k: None)
    old = win._panel
    win._start_solve(win._solve_sig())
    win._run_busy(lambda: 1, lambda r: None, "job 2", "Failed")   # still running after
    h.release(0)
    qtbot.waitUntil(lambda: win._panel is not old, timeout=5000)
    qtbot.wait(30)
    assert win._busy
    assert _live(win) == []
    h.release(); _idle(qtbot, win)
    assert [(type(w).__name__, w.isEnabled()) for w in _controls(win)] == shape


# ------------------------------------------------- keyboard (Review Focus 5)
def _key(widget, key):
    QApplication.sendEvent(widget, QKeyEvent(QEvent.Type.KeyPress, key,
                                             Qt.KeyboardModifier.NoModifier))


def test_keys_cannot_move_a_dimmed_slider_and_the_app_keys_still_work(
        qtbot, tmp_path, monkeypatch):
    win, h = _make(qtbot, tmp_path, monkeypatch)
    win._go_to_id("local_contrast", user_initiated=False); qtbot.wait(30)
    s = win._panel.lc_slider
    s.setValue(40); qtbot.wait(150)
    s.setFocus()
    fulls = []
    monkeypatch.setattr(win, "_toggle_fullscreen", lambda: fulls.append(1))

    # Idle: what each key does, so the busy run is compared with it.
    _key(s, Qt.Key.Key_Right)
    assert s.value() == 41
    peek = win._peek_active
    _key(s, Qt.Key.Key_Space)
    assert win._peek_active is not peek
    _key(s, Qt.Key.Key_Space)
    _key(s, Qt.Key.Key_F)
    assert fulls == [1]

    _press_apply(win); qtbot.wait(30)
    assert win._busy
    _key(s, Qt.Key.Key_Right)
    assert s.value() == 41, "an arrow key moved a slider while its step ran"
    peek = win._peek_active
    _key(s, Qt.Key.Key_Space)
    assert win._peek_active is not peek, "Space stopped peeking while busy"
    _key(s, Qt.Key.Key_F)
    assert fulls == [1, 1], "F stopped toggling full screen while busy"
    h.release(); _idle(qtbot, win)


# ------------------------------------------------- the crop box
def _drag(view, start, delta):
    vp = view.viewport()
    end = start + delta
    for kind, pos, button, held in (
            (QEvent.Type.MouseButtonPress, start, Qt.MouseButton.LeftButton,
             Qt.MouseButton.LeftButton),
            (QEvent.Type.MouseMove, end, Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton),
            (QEvent.Type.MouseButtonRelease, end, Qt.MouseButton.LeftButton,
             Qt.MouseButton.NoButton)):
        QApplication.sendEvent(vp, QMouseEvent(kind, QPointF(pos), QPointF(vp.mapToGlobal(pos)),
                                               button, held, Qt.KeyboardModifier.NoModifier))


def test_the_crop_box_cannot_be_changed_while_a_job_runs(qtbot, tmp_path, monkeypatch):
    """Crop's own Apply is synchronous, but a job started on the Crop step (a
    plate solve, Save Project) left the box draggable, dismissable and
    showable under a running job."""
    win, h = _make(qtbot, tmp_path, monkeypatch)
    win._go_to_id("crop", user_initiated=False); qtbot.wait(30)
    view = win.image_view
    view.show_crop_box()
    view._set_bounds((16, 48, 16, 48)); qtbot.wait(20)   # smaller than the frame
    t, b, l, r = view.crop_bounds()
    centre = view.mapFromScene(QPointF((l + r) / 2, (t + b) / 2))

    _drag(view, centre, QPoint(6, 0)); qtbot.wait(20)     # idle: it moves
    moved = view.crop_bounds()
    assert moved != (t, b, l, r), "fixture: an idle drag did not move the box"

    win._run_busy(lambda: 1, lambda r: None, "Plate-solving…", "Failed")
    assert win._busy
    _drag(view, centre, QPoint(-12, 0)); qtbot.wait(20)
    assert view.crop_bounds() == moved, "the box moved while a job ran"
    dismissed = []
    view.cropDismissRequested.connect(lambda: dismissed.append(1))
    _key(view, Qt.Key.Key_Escape)
    corner = view.mapFromScene(QPointF(1, 1))
    _drag(view, corner, QPoint(0, 0))                   # a click on the dimmed area
    assert dismissed == []
    assert view.crop_box_visible()

    h.release(); _idle(qtbot, win)
    _drag(view, centre, QPoint(-12, 0)); qtbot.wait(20)
    assert view.crop_bounds() != moved, "the box stayed locked after the job"
