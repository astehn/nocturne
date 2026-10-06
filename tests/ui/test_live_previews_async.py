"""Live previews off the UI thread (spec F1/F2, 2026-10-06), in the window.

A Recover Core tick froze the window for 7 s on a 33 MP drizzle; now the effect
runs on the pool and only the paint comes back. What must not change: the
picture that lands is exactly what Apply commits, no stale value or stale base
ever reaches the canvas, and a preview never locks or dims anything — it is not
"the step working"."""
import threading

import numpy as np
import pytest
from PySide6.QtCore import QTimer

import nocturne.ui.main_window as mw
from nocturne.core.image import AstroImage
from nocturne.steps.recover_core import RecoverCoreStep
from tests.ui.test_main_window import _window
from tests.ui.test_preview_cache import _bright_fits


def _layers(base):
    rng = np.random.default_rng(1)
    stars = (rng.random(base.data.shape) * 0.05).astype(np.float32)
    return (AstroImage(np.clip(base.data * 0.9, 0, 1).astype(np.float32), is_linear=False, metadata={}),
            AstroImage(stars, is_linear=False, metadata={}), "StarNet2")


def _open(qtbot, tmp_path, monkeypatch, *, stretch=True):
    monkeypatch.setattr(mw, "preferred_splitter", lambda s: "starnet")
    monkeypatch.setattr(mw.MainWindow, "_split_tagged", lambda self, base: _layers(base))
    win = _window(qtbot, tmp_path)
    win.open_fits(_bright_fits(tmp_path))
    monkeypatch.setattr(win, "_ask_pending", lambda *a, **k: "discard")
    if stretch:
        win._go_to_id("stretch")
        win.apply_current({"amount": 0.6, "linked": True})
    return win


def _settle(qtbot, win):
    """Past the debounce, and every preview landed."""
    qtbot.wait(120)
    qtbot.waitUntil(lambda: not win._previews.busy and win._previews._running is None,
                    timeout=10000)


class Hold:
    """Wraps a main_window effect so each call blocks until released."""

    def __init__(self, monkeypatch, name):
        self.calls = []
        self.gate = threading.Event()
        self.gates = [self.gate]
        real = getattr(mw, name)

        def held(*args, **kwargs):
            self.calls.append(args)
            gate = self.gate
            assert gate.wait(10), "never released"
            return real(*args, **kwargs)
        monkeypatch.setattr(mw, name, held)

    def release(self):
        self.gate.set()
        self.gate = threading.Event()
        self.gates.append(self.gate)

    def open_all(self):
        for g in self.gates:
            g.set()


@pytest.fixture
def hold(monkeypatch):
    made = []

    def make(name):
        h = Hold(monkeypatch, name)
        made.append(h)
        return h
    yield make
    for h in made:
        h.open_all()


# --- WYSIWYG: every live-preview step lands exactly what Apply commits ---

_SPECS = {
    # id: (stage, before-stretch?, move the controls, render)
    "levels": ("levels", False, lambda p: p.gamma_slider.setValue(160), "_render_levels_preview"),
    "stretch": ("stretch", True, lambda p: p.stretch_slider.setValue(35), "_render_stretch_preview"),
    "curves": ("curves", False, lambda p: p.curve_editor.set_points([(0.0, 0.0), (0.35, 0.6), (1.0, 1.0)]),
               "_render_curve_preview"),
    "saturation": ("saturation", False, lambda p: (p.sat_slider.setValue(80), p.neb_slider.setValue(60)),
                   "_render_saturation_preview"),
    "local_contrast": ("local_contrast", False, lambda p: p.lc_slider.setValue(60), "_render_lc_preview"),
    "recover_core": ("recover_core", False, lambda p: p.recover_slider.setValue(70), "_render_recover_preview"),
    "tint": ("color", True, lambda p: p.tint_slider.setValue(40), "_render_tint_preview"),
    "remove_green": ("remove_green", False, lambda p: p.rg_slider.setValue(70), "_render_removegreen_preview"),
    "green_fringe": ("green_fringe", False, lambda p: p.fringe_slider.setValue(60), "_render_fringe_preview"),
    "star_reduction": ("star_reduction", False, lambda p: p.sr_slider.setValue(50), "_render_sr_preview"),
}


@pytest.mark.parametrize("sid", list(_SPECS))
def test_the_landed_preview_is_what_apply_commits(qtbot, tmp_path, monkeypatch, sid):
    stage, linear, move, render = _SPECS[sid]
    win = _open(qtbot, tmp_path, monkeypatch, stretch=not linear)
    win._go_to_id(stage)
    if sid == "tint":
        win._apply_colour_step()     # the calibration first: tint previews on top of it
    before = win._displayed.data.copy()
    win._async_enabled = True
    move(win._panel)
    getattr(win, render)()
    _settle(qtbot, win)
    landed = win._displayed.data.copy()
    assert not np.array_equal(landed, before), "fixture: the move changes the picture"
    win._async_enabled = False
    n = len(win.project.entries())
    win._apply_current_step()
    assert len(win.project.entries()) == n + 1, "Apply committed"
    assert np.array_equal(landed, win.project.current().data), sid


# --- Review focus 2: latest position wins ---

def _at_levels(qtbot, tmp_path, monkeypatch, hold):
    win = _open(qtbot, tmp_path, monkeypatch)
    win._go_to_id("levels")
    h = hold("apply_levels")
    win._async_enabled = True
    return win, h


def _gamma(win, value):
    win._panel.gamma_slider.setValue(value)
    win._render_levels_preview()


def test_a_drag_while_one_computes_runs_only_the_last_and_never_paints_an_old_value(
        qtbot, tmp_path, monkeypatch, hold):
    win, h = _at_levels(qtbot, tmp_path, monkeypatch, hold)
    painted = []
    real = win._show_preview
    monkeypatch.setattr(win, "_show_preview",
                        lambda out, **kw: (painted.append(out.copy()), real(out, **kw)))
    base = win._preview_base("levels")
    _gamma(win, 120)
    qtbot.waitUntil(lambda: len(h.calls) == 1)
    _gamma(win, 150)
    _gamma(win, 180)
    _gamma(win, 210)
    h.release()                    # 1.20 lands: stale, dropped; 2.10 starts
    qtbot.waitUntil(lambda: len(h.calls) == 2)
    assert painted == [], "1.20 reached the canvas after the slider had left it"
    h.release()
    _settle(qtbot, win)
    assert [c[2] for c in h.calls] == [1.2, 2.1], "1.50 and 1.80 were never wanted"
    assert len(painted) == 1
    from nocturne.core.levels import apply_levels
    assert np.array_equal(painted[0], np.clip(apply_levels(base, 0.0, 2.1, 1.0).data, 0, 1)
                          .astype(np.float32))


# --- Review focus 5: a preview locks nothing, and the window keeps running ---

def test_a_preview_is_not_the_step_working(qtbot, tmp_path, monkeypatch, hold):
    win, h = _at_levels(qtbot, tmp_path, monkeypatch, hold)
    next_on = win._next_btn.isEnabled()
    _gamma(win, 140)
    qtbot.waitUntil(lambda: len(h.calls) == 1)
    assert win._previews.busy
    assert win._running == set() and not win._busy
    assert win.stepper.isEnabled() and win._panel.isEnabled()
    assert win._next_btn.isEnabled() == next_on
    assert win._open_image_act.isEnabled()
    fired = []
    QTimer.singleShot(5, lambda: fired.append(True))
    qtbot.waitUntil(lambda: fired == [True], timeout=2000)
    assert len(h.calls) == 1 and h.calls, "the effect is still held: the UI thread ran meanwhile"
    win._panel.gamma_slider.setValue(170)          # the slider still moves
    assert win._levels_pending[1] == 1.7
    h.release()
    h.release()
    _settle(qtbot, win)


def test_the_ring_shows_while_a_preview_computes(qtbot, tmp_path, monkeypatch, hold):
    win, h = _at_levels(qtbot, tmp_path, monkeypatch, hold)
    ring = win._preview_ring
    assert ring.isHidden()
    _gamma(win, 140)
    qtbot.waitUntil(lambda: len(h.calls) == 1)
    assert not ring.isHidden()
    h.release()
    _settle(qtbot, win)
    assert ring.isHidden()


# --- Review focus 1 and 4: nothing stale lands after the picture moved on ---

def _held_tick(qtbot, win, h, value=140):
    _gamma(win, value)
    qtbot.waitUntil(lambda: len(h.calls) == 1)
    win._async_enabled = False       # the action below runs inline, as in every test


def _assert_dropped(qtbot, win, h):
    shown = win._displayed.data.copy()
    canvas = win._canvas_rgb8().copy()
    h.release()
    qtbot.waitUntil(lambda: win._previews._running is None)
    qtbot.wait(30)
    assert np.array_equal(win._displayed.data, shown)
    assert np.array_equal(win._canvas_rgb8(), canvas), "a stale preview reached the canvas"


def test_apply_mid_preview_commits_the_controls_and_drops_the_preview(
        qtbot, tmp_path, monkeypatch, hold):
    win, h = _at_levels(qtbot, tmp_path, monkeypatch, hold)
    base = win._preview_base("levels")
    _gamma(win, 140)                       # computing 1.40
    qtbot.waitUntil(lambda: len(h.calls) == 1)
    win._panel.gamma_slider.setValue(220)  # the controls now say 2.20; no render yet
    win._async_enabled = False
    win._apply_current_step()
    from nocturne.steps.levels import LevelsStep
    name, option = win.project.entries()[-1]
    assert name == "Levels" and tuple(option)[1] == pytest.approx(2.2)
    assert np.array_equal(win.project.current().data,
                          LevelsStep().apply(base, option).data)
    _assert_dropped(qtbot, win, h)
    assert np.array_equal(win._displayed.data, win.project.current().data)


def test_leaving_the_step_drops_the_preview(qtbot, tmp_path, monkeypatch, hold):
    win, h = _at_levels(qtbot, tmp_path, monkeypatch, hold)
    _held_tick(qtbot, win, h)
    win._go_to_id("curves")
    _assert_dropped(qtbot, win, h)
    assert win.current_stage_id() == "curves"


def test_a_new_image_drops_the_preview(qtbot, tmp_path, monkeypatch, hold):
    win, h = _at_levels(qtbot, tmp_path, monkeypatch, hold)
    _held_tick(qtbot, win, h)
    win.open_image(AstroImage(np.full((32, 32, 3), 0.3, np.float32),
                              is_linear=False, metadata={}), "next")
    _assert_dropped(qtbot, win, h)
    assert np.array_equal(win._displayed.data, np.full((32, 32, 3), 0.3, np.float32))


def test_undo_drops_the_preview(qtbot, tmp_path, monkeypatch, hold):
    win, h = _at_levels(qtbot, tmp_path, monkeypatch, hold)
    _held_tick(qtbot, win, h)
    win._undo()                          # the stretch goes; Stretch shows its own preview
    _assert_dropped(qtbot, win, h)


# --- Review focus 3: a base that changes under the step ---

def _at_recover(qtbot, tmp_path, monkeypatch, hold):
    win = _open(qtbot, tmp_path, monkeypatch)
    win._go_to_id("recover_core")
    h = hold("recover_prepare")
    win._async_enabled = True
    return win, h


def _recover(win, value):
    win._panel.recover_slider.setValue(value)
    win._render_recover_preview()


def test_the_first_tick_prepares_in_the_background_and_a_drag_meanwhile_reuses_it(
        qtbot, tmp_path, monkeypatch, hold):
    """The 7 s blur on a new base runs on the pool; values asked for while it
    runs use it rather than preparing it again."""
    win, h = _at_recover(qtbot, tmp_path, monkeypatch, hold)
    base = win._preview_base("recover_core")
    _recover(win, 30)
    qtbot.waitUntil(lambda: len(h.calls) == 1)
    _recover(win, 60)
    _recover(win, 90)
    h.release()
    _settle(qtbot, win)
    assert len(h.calls) == 1, "prepared twice for one base"
    assert win._recover_prep[0] == win._sr_sig(base)
    assert np.array_equal(win._displayed.data, RecoverCoreStep().apply(base, 0.9).data)


def test_a_trim_mid_prepare_drops_it_and_the_next_tick_uses_the_new_base(
        qtbot, tmp_path, monkeypatch, hold):
    win, h = _at_recover(qtbot, tmp_path, monkeypatch, hold)
    old = win._preview_base("recover_core")
    _recover(win, 50)
    qtbot.waitUntil(lambda: len(h.calls) == 1)
    win._async_enabled = False

    class Trim:
        def __init__(self, *a, **k): pass
        def exec(self): return True
        def bounds(self): return (2, 30, 3, 40)
    monkeypatch.setattr(mw, "TrimDialog", Trim)
    win._trim()
    win._go_to_id("recover_core")
    shown = win._canvas_rgb8().copy()
    h.release()
    qtbot.waitUntil(lambda: win._previews._running is None)
    qtbot.wait(30)
    assert np.array_equal(win._canvas_rgb8(), shown), "the old base's preview landed"
    held = win._recover_prep
    assert held is None or held[0] != win._sr_sig(old), "the old base's blur was kept"
    new = win._preview_base("recover_core")
    assert new.data.shape != old.data.shape, "fixture: the base changed"
    win._async_enabled = True
    _recover(win, 50)
    qtbot.waitUntil(lambda: len(h.calls) == 2)
    assert h.calls[1][0].data.shape == new.data.shape
    h.release()
    _settle(qtbot, win)
    assert win._recover_prep[0] == win._sr_sig(new)
    assert np.array_equal(win._displayed.data, RecoverCoreStep().apply(new, 0.5).data)


def test_a_prepare_landing_after_a_new_picture_is_not_kept(qtbot, tmp_path, monkeypatch, hold):
    """The generation guard on the cache write, on its own: even with the
    runner's cancel taken out, the old picture's blur does not become the new
    picture's."""
    win, h = _at_recover(qtbot, tmp_path, monkeypatch, hold)
    _recover(win, 50)
    qtbot.waitUntil(lambda: len(h.calls) == 1)
    monkeypatch.setattr(win._previews, "cancel", lambda: None)
    win._async_enabled = False
    win.open_image(AstroImage(np.full((32, 32, 3), 0.3, np.float32),
                              is_linear=False, metadata={}), "next")
    h.release()
    qtbot.waitUntil(lambda: win._previews._running is None)
    qtbot.wait(30)
    assert win._recover_prep is None


# --- Apply reuses the prepared blur, and commits exactly the plain function ---

@pytest.mark.parametrize("stage,slider,prep,attr,step", [
    ("recover_core", "recover_slider", "recover_prepare", "_recover_prep", RecoverCoreStep),
    ("local_contrast", "lc_slider", "lc_prepare", "_lc_prep", None),
])
def test_apply_reuses_the_prepared_array_and_equals_the_plain_step(
        qtbot, tmp_path, monkeypatch, stage, slider, prep, attr, step):
    from nocturne.steps.local_contrast import LocalContrastStep
    step = step or LocalContrastStep
    win = _open(qtbot, tmp_path, monkeypatch)
    win._go_to_id(stage)
    base = win._preview_base(stage)
    getattr(win._panel, slider).setValue(40)
    getattr(win, {"recover_core": "_render_recover_preview",
                  "local_contrast": "_render_lc_preview"}[stage])()
    assert getattr(win, attr) is not None
    calls = []
    real = getattr(mw, prep)
    monkeypatch.setattr(mw, prep, lambda img: (calls.append(1), real(img))[1])
    import nocturne.core.hdr as hdr
    import nocturne.core.local_contrast as lc
    monkeypatch.setattr(hdr, "prepare", lambda img: (calls.append(1), real(img))[1])
    monkeypatch.setattr(lc, "prepare", lambda img: (calls.append(1), real(img))[1])
    win._apply_current_step()
    assert calls == [], "Apply prepared again what the preview already holds"
    name, option = win.project.entries()[-1]
    assert option == pytest.approx(0.4)
    assert np.array_equal(win.project.current().data, step().apply(base, 0.4).data)


def test_apply_after_the_base_changed_does_not_use_the_old_prepared_array(
        qtbot, tmp_path, monkeypatch):
    """Same shape, new pixels (an earlier step re-applied): only the signature
    tells the held blur is someone else's."""
    win = _open(qtbot, tmp_path, monkeypatch)
    win._go_to_id("recover_core")
    win._panel.recover_slider.setValue(40)
    win._render_recover_preview()
    held = win._recover_prep
    assert held is not None
    win._go_to_id("stretch")
    win.apply_current({"amount": 0.3, "linked": True})
    win._go_to_id("recover_core")
    base = win._preview_base("recover_core")
    assert win._sr_sig(base) != held[0] and win._recover_prep is held, \
        "fixture: a stale array is held when Apply is pressed"
    win._panel.recover_slider.setValue(40)    # no tick lands: the timer never runs
    win._apply_current_step()
    assert win.project.entries()[-1][0] == "Recover Core"
    assert np.array_equal(win.project.current().data,
                          RecoverCoreStep().apply(base, 0.4).data)


# --- review fix round 1 ---

def test_an_async_apply_quiets_the_previews(qtbot, tmp_path, monkeypatch, hold):
    """Apply while a preview prepares, with a debounce timer still pending: the
    old preview never paints under the commit and no second prepare starts."""
    win, h = _at_recover(qtbot, tmp_path, monkeypatch, hold)
    base = win._preview_base("recover_core")
    _recover(win, 30)                          # preparing, held
    qtbot.waitUntil(lambda: len(h.calls) == 1)
    win._panel.recover_slider.setValue(60)     # debounce timer now pending
    gate = threading.Event()
    real = win._step_for

    class HeldStep:
        def __init__(self, step):
            self._step = step

        def apply(self, b, option):
            assert gate.wait(10)
            return self._step.apply(b, option)

        def __getattr__(self, name):
            return getattr(self._step, name)
    monkeypatch.setattr(win, "_step_for", lambda sid: HeldStep(real(sid)))
    win._apply_current_step()                  # async, held
    assert win._busy
    canvas = win._canvas_rgb8().copy()
    qtbot.wait(200)                            # past the debounce
    h.release()                                # the old preview lands now
    qtbot.waitUntil(lambda: win._previews._running is None)
    qtbot.wait(150)
    assert len(h.calls) == 1, "a second prepare started beside the Apply"
    assert np.array_equal(win._canvas_rgb8(), canvas), "a preview painted under the commit"
    gate.set()
    qtbot.waitUntil(lambda: not win._busy)
    assert win.project.entries()[-1] == ("Recover Core", pytest.approx(0.6))
    assert np.array_equal(win.project.current().data, RecoverCoreStep().apply(base, 0.6).data)
    assert np.array_equal(win._displayed.data, win.project.current().data)


def test_a_preview_asked_again_while_peeking_shows_the_after(qtbot, tmp_path, monkeypatch):
    win = _open(qtbot, tmp_path, monkeypatch)
    win._go_to_id("levels")
    win._async_enabled = True
    _gamma(win, 150)
    _settle(qtbot, win)
    after = win._canvas_rgb8().copy()
    win._toggle_peek()
    assert win._peek_active and not np.array_equal(win._canvas_rgb8(), after)
    win._render_levels_preview()               # same value, asked again
    _settle(qtbot, win)
    assert not win._peek_active
    assert np.array_equal(win._canvas_rgb8(), after)


def test_apply_needs_the_exact_base_the_array_was_kept_for(qtbot, tmp_path, monkeypatch):
    """Same signature is not enough: the slot also carries the base token."""
    win = _open(qtbot, tmp_path, monkeypatch)
    win._go_to_id("recover_core")
    win._panel.recover_slider.setValue(40)
    win._render_recover_preview()
    slot = win._prep_slots["_recover_prep"]
    assert slot.token == win._base_token("recover_core")
    slot.token = ("not", "this", "base")
    calls = []
    import nocturne.core.hdr as hdr
    real = hdr.prepare
    monkeypatch.setattr(hdr, "prepare", lambda img: (calls.append(1), real(img))[1])
    win._apply_current_step()
    assert calls == [1], "Apply trusted an array kept for another base"


def test_the_saturation_key_changes_when_the_mask_arrives(qtbot, tmp_path, monkeypatch):
    win = _open(qtbot, tmp_path, monkeypatch)
    win._go_to_id("saturation")
    keys = []
    real = win._previews.request
    monkeypatch.setattr(win._previews, "request",
                        lambda key, *a, **k: (keys.append(key), real(key, *a, **k)))
    win._panel.neb_slider.setValue(50)
    win._render_saturation_preview()
    sig, mask = win._sat_mask
    win._sat_mask = None
    win._render_saturation_preview()
    assert keys[-1] != keys[-2], "with and without the mask are different pictures"


def test_the_ring_follows_the_histogram_corner(qtbot, tmp_path, monkeypatch, hold):
    """Placed when a preview starts, and again whenever the histogram is
    resized (a Resize event reaching it re-places the ring)."""
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QResizeEvent
    from PySide6.QtWidgets import QApplication
    win, h = _at_levels(qtbot, tmp_path, monkeypatch, hold)
    ring, hist = win._preview_ring, win.histogram_view
    _gamma(win, 140)
    qtbot.waitUntil(lambda: len(h.calls) == 1)
    assert ring.x() + ring.width() + 4 == hist.width()
    ring.move(0, 0)                          # stand-in for a stale placement
    QApplication.sendEvent(hist, QResizeEvent(hist.size(), QSize(10, 10)))
    assert ring.x() + ring.width() + 4 == hist.width()
    h.release()
    _settle(qtbot, win)


@pytest.mark.parametrize("mode", ["fail", "cancel"])
def test_a_failing_cached_apply_commits_nothing(qtbot, tmp_path, monkeypatch, mode):
    """The prepared path through _run_busy: an error or a cancel reports,
    commits nothing, and gives the controls back."""
    from nocturne.core import tasks
    win = _open(qtbot, tmp_path, monkeypatch)
    win._go_to_id("recover_core")
    win._panel.recover_slider.setValue(40)
    win._render_recover_preview()
    assert win._recover_prep is not None
    gate = threading.Event()

    def broken(img, blur, amount):
        assert gate.wait(10)
        if mode == "cancel":
            tasks.current().check()
        raise RuntimeError("boom")
    monkeypatch.setattr(mw, "recover_apply", broken)
    entries = list(win.project.entries())
    win._async_enabled = True
    win._apply_current_step()
    assert win._busy
    if mode == "cancel":
        win._cancel_active()
    gate.set()
    qtbot.waitUntil(lambda: not win._busy)
    assert win.project.entries() == entries
    assert win._panel.recover_slider.isEnabled() and win._panel.apply_btn.isEnabled()
    if mode == "fail":
        assert "boom" in win._warning.text()
