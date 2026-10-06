"""The tool windows' work runs off the UI thread (no-freezes spec F5, 2026-10-06).

Star Spikes' per-tick render and Apply, Share's compose (open, every preview,
Export, Copy) and the 8-bit copy MainWindow makes to open it, Upscale's first
render, Export and Open as copy, Starless Levels' Apply.

Each test HOLDS the pool job on an event, so it can look at the window while it
runs: the UI thread still turns (a QTimer fires), the window is dimmed with
Close live, and nothing lands early. Released, the result must EQUAL what the
inline (synchronous) path makes for the same values — array equality, or the
same file bytes for an export. A job landing after the window closed must do
nothing at all.
"""
from __future__ import annotations

import threading

import numpy as np
import pytest
from PySide6.QtCore import QObject, QThread, QTimer
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QDialog

from nocturne.core.image import AstroImage
from nocturne.settings import Settings


# --- holding a job ----------------------------------------------------------------
class _Hold:
    """Wraps `real`: on a pool thread it waits for release() first; on the UI
    thread (the inline path the tests compare against) it runs at once."""

    def __init__(self, real) -> None:
        self.real = real
        self.event = threading.Event()
        self.started: list = []     # one per pool call
        self.on_ui: list = []       # one per UI-thread call

    def __call__(self, *a, **k):
        if threading.current_thread() is threading.main_thread():
            self.on_ui.append(a)
            return self.real(*a, **k)
        self.started.append(a)
        self.event.wait(20)
        return self.real(*a, **k)

    def wait(self, qtbot, n: int = 1) -> None:
        qtbot.waitUntil(lambda: len(self.started) >= n, timeout=5000)

    def release(self) -> None:
        self.event.set()


@pytest.fixture
def hold(monkeypatch):
    made = []

    def make(target, name, *, static=False):
        h = _Hold(getattr(target, name))
        monkeypatch.setattr(target, name, staticmethod(h) if static else h)
        made.append(h)
        return h
    yield make
    for h in made:          # never leave a pool thread waiting on a failed test
        h.release()


class _HoldJobs(_Hold):
    """Holds a module's pool jobs before they START, so a job that reads
    anything late reads what the test changed meanwhile."""

    def __init__(self, monkeypatch, module) -> None:
        super().__init__(None)
        real = module.run_async

        def wrapped(pool, fn, *a, **k):
            def held():
                self.started.append(1)
                self.event.wait(20)
                return fn()
            return real(pool, held, *a, **k)
        monkeypatch.setattr(module, "run_async", wrapped)


def _responsive(qtbot) -> None:
    """The UI thread is turning: a timer posted now fires."""
    fired = []
    QTimer.singleShot(0, lambda: fired.append(1))
    qtbot.waitUntil(lambda: fired == [1], timeout=1000)


def _drain(qtbot, ms: int = 150) -> None:
    """Let a released job land (or, closed, fail to)."""
    from PySide6.QtCore import QThreadPool
    QThreadPool.globalInstance().waitForDone(5000)
    qtbot.wait(ms)


ON = lambda: True        # noqa: E731  the shipped app's setting


# =============================================================================
# Star Spikes
# =============================================================================
def _many_stars(h=160, w=160):
    yy, xx = np.mgrid[0:h, 0:w]
    lum = np.full((h, w), 0.02, np.float32)
    rng = np.random.default_rng(5)
    for cy, cx in zip(rng.integers(10, h - 10, 12), rng.integers(10, w - 10, 12)):
        lum += 0.9 * np.exp(-(((yy - cy) ** 2 + (xx - cx) ** 2) / (2 * 1.7 ** 2)))
    lum = np.clip(lum + 0.004 * rng.standard_normal((h, w)), 0, 1).astype(np.float32)
    return AstroImage(np.repeat(lum[:, :, None], 3, axis=2), is_linear=False)


def _spikes(qtbot, **kw):
    from nocturne.ui.star_spikes_dialog import StarSpikesDialog
    d = StarSpikesDialog(_many_stars(), is_async=ON, **kw)
    qtbot.addWidget(d)
    d.show()
    qtbot.waitUntil(lambda: d._stars is not None and not d._runner.busy
                    and d._shown_params is not None, timeout=8000)
    return d


def _spikes_inline(params):
    """What the inline path draws for `params` — the comparison for every
    pooled result."""
    from nocturne.core.star_spikes import detect_stars
    from nocturne.ui.star_spikes_dialog import _render
    img = _many_stars()
    return _render(img, detect_stars(img.data), params)[0]


def test_a_spikes_tick_renders_on_the_pool_and_equals_the_inline_render(qtbot, hold):
    import nocturne.ui.star_spikes_dialog as sd
    d = _spikes(qtbot)
    held = hold(sd, "_render")
    before = d._result
    d.length_slider.setValue(70)
    held.wait(qtbot)                        # the debounce fired; the job is on the pool
    _responsive(qtbot)
    assert d._result is before, "the picture changed before its render landed"
    pressed = d._params()
    held.release()
    qtbot.waitUntil(lambda: d._shown_params == pressed, timeout=5000)
    assert held.on_ui == [], "the tick rendered on the UI thread"
    assert np.array_equal(d.result().data, _spikes_inline(pressed).data)


def test_a_drag_renders_the_first_and_the_last_value_only(qtbot, hold):
    import nocturne.ui.star_spikes_dialog as sd
    d = _spikes(qtbot)
    held = hold(sd, "_render")
    d.length_slider.setValue(30)
    held.wait(qtbot)
    for v in (40, 50, 60):                  # three ticks while the first computes
        d.length_slider.setValue(v)
        d._timer.stop()
        d._queue_render()
    held.release()
    last = d._params()
    qtbot.waitUntil(lambda: not d._runner.busy, timeout=5000)
    assert [a[2][0] for a in held.started] == [0.30, 0.60], \
        "every tick computed, not the first and the newest"
    assert d._shown_params == last
    assert np.array_equal(d.result().data, _spikes_inline(last).data)


def test_spikes_apply_uses_the_values_at_the_press_and_dims_the_window(qtbot, hold):
    import nocturne.ui.star_spikes_dialog as sd
    got = []
    d = _spikes(qtbot, on_apply=lambda img, params: got.append((img, params)))
    d.length_slider.setValue(55)            # the debounce has NOT fired: Apply must draw
    held = hold(sd, "_render")
    pressed = d._params()
    d.apply_btn.click()
    held.wait(qtbot)
    _responsive(qtbot)
    assert got == []
    assert all(not s.isEnabled() for s in d._sliders()), "sliders live mid-Apply"
    assert not d.apply_btn.isEnabled() and not d.reset_btn.isEnabled()
    close = [b for b in d.findChildren(type(d.apply_btn)) if b.text() == "Close"][0]
    assert close.isEnabled()
    held.release()
    qtbot.waitUntil(lambda: bool(got), timeout=5000)
    img, params = got[0]
    assert held.on_ui == []
    assert np.array_equal(img.data, _spikes_inline(pressed).data)
    assert params == d._named(pressed)
    assert d.result() is img
    assert d.isHidden() and len(got) == 1


def test_spikes_apply_on_a_current_preview_hands_it_over_without_drawing(qtbot, hold):
    import nocturne.ui.star_spikes_dialog as sd
    got = []
    d = _spikes(qtbot, on_apply=lambda img, params: got.append(img))
    shown = d._result
    held = hold(sd, "_render")
    d.apply_btn.click()
    assert got == [shown], "the picture on screen IS the pressed values"
    assert held.started == [] and held.on_ui == []


def test_a_spikes_apply_landing_after_close_applies_nothing(qtbot, hold):
    import nocturne.ui.star_spikes_dialog as sd
    got = []
    d = _spikes(qtbot, on_apply=lambda img, params: got.append(img))
    d.length_slider.setValue(45)
    held = hold(sd, "_render")
    d.apply_btn.click()
    held.wait(qtbot)
    d.reject()
    painted = []
    d.preview.show_image = lambda *a: painted.append(1)
    held.release()
    _drain(qtbot)
    assert got == [] and painted == []
    # QDialog.result: StarSpikesDialog.result() returns the picture instead.
    assert QDialog.result(d) == QDialog.DialogCode.Rejected


# =============================================================================
# Share
# =============================================================================
def _rgb(h=400, w=300):
    rng = np.random.default_rng(3)
    return (rng.random((h, w, 3)) * 255).astype(np.uint8)


def _share(qtbot, *, is_async=ON):
    from nocturne.ui.share_dialog import ShareDialog
    d = ShareDialog(_rgb(), {"target": "NGC 7000", "source_label": "ngc7000.fits"},
                    Settings(handle="me"), is_async=is_async)
    qtbot.addWidget(d)
    d.show()
    return d


def _pixels(img: QImage) -> np.ndarray:
    img = img.convertToFormat(QImage.Format.Format_RGB888)
    w, h = img.width(), img.height()
    return np.frombuffer(img.constBits(), np.uint8).reshape(h, img.bytesPerLine())[:, :w * 3].copy()


def _assert_share_gated(d) -> None:
    assert not d._export_btn.isEnabled() and not d._copy_btn.isEnabled()
    assert not d._designation_edit.isEnabled() and not d._size_box.isEnabled()
    assert d._close_btn.isEnabled()
    assert d.status_ring.isVisible()


def test_share_opens_without_composing_on_the_ui_thread(qtbot, hold):
    from nocturne.ui.share_dialog import ShareDialog
    held = hold(ShareDialog, "_compose", static=True)
    d = _share(qtbot)
    held.wait(qtbot)
    _responsive(qtbot)
    assert d._preview_image is None, "a preview landed before its compose did"
    assert d.status_ring.isVisible(), "the wait shows no ring"
    held.release()
    qtbot.waitUntil(lambda: d._preview_image is not None, timeout=5000)
    assert held.on_ui == []
    expected = held.real(d._snapshot(for_preview=True))
    assert np.array_equal(_pixels(d._preview_image), _pixels(expected))
    qtbot.waitUntil(lambda: d.status_ring.isHidden(), timeout=2000)


def test_share_export_writes_the_same_bytes_as_the_inline_export(qtbot, hold, tmp_path):
    from nocturne.ui.share_dialog import ShareDialog
    inline = _share(qtbot, is_async=None)
    inline._do_export(str(tmp_path / "inline.jpg"))
    d = _share(qtbot)
    qtbot.waitUntil(lambda: d._preview_image is not None and not d._runner.busy, timeout=5000)
    held = hold(ShareDialog, "_compose", static=True)
    out = tmp_path / "pooled.jpg"
    d._do_export(str(out))
    held.wait(qtbot)
    _responsive(qtbot)
    assert not out.exists()
    _assert_share_gated(d)
    d._note_wrap()                           # the wrap check re-writes the status line
    assert "Saving" in d.status.text(), "the working message was wiped mid-export"
    before = d._designation_edit.text()
    qtbot.keyClicks(d._designation_edit, "zz")
    assert d._designation_edit.text() == before, "the plate text changed mid-export"
    held.release()
    qtbot.waitUntil(lambda: "Saved" in d.status.text(), timeout=5000)
    assert held.on_ui == []
    assert out.read_bytes() == (tmp_path / "inline.jpg").read_bytes()
    assert d._export_btn.isEnabled() and d._designation_edit.isEnabled()
    assert d.status_ring.isHidden()


def test_share_copy_composes_on_the_pool_and_sets_the_clipboard_on_the_ui_thread(qtbot, hold):
    from nocturne.ui.share_dialog import ShareDialog
    d = _share(qtbot)
    qtbot.waitUntil(lambda: d._preview_image is not None and not d._runner.busy, timeout=5000)
    expected = d._compose_current()
    got = []
    d._clipboard_runner = lambda img: got.append(
        (QImage(img), QThread.currentThread() is QApplication.instance().thread()))
    held = hold(ShareDialog, "_compose", static=True)
    d._do_copy()
    held.wait(qtbot)
    _responsive(qtbot)
    assert got == []
    _assert_share_gated(d)
    held.release()
    qtbot.waitUntil(lambda: bool(got), timeout=5000)
    image, on_ui = got[0]
    assert on_ui, "the clipboard was set off the UI thread"
    assert np.array_equal(_pixels(image), _pixels(expected))
    assert "Copied" in d.status.text()


@pytest.mark.parametrize("action", ["export", "copy"])
def test_a_share_job_landing_after_close_does_nothing(qtbot, hold, tmp_path, action):
    from nocturne.ui.share_dialog import ShareDialog
    d = _share(qtbot)
    qtbot.waitUntil(lambda: d._preview_image is not None and not d._runner.busy, timeout=5000)
    copied = []
    d._clipboard_runner = lambda img: copied.append(1)
    held = hold(ShareDialog, "_compose", static=True)
    if action == "export":
        d._do_export(str(tmp_path / "x.jpg"))
    else:
        d._do_copy()
    held.wait(qtbot)
    status = d.status.text()
    d.reject()
    held.release()
    _drain(qtbot)
    assert copied == []
    assert d.status.text() == status, "a closed window reported a result"


def test_mainwindow_makes_shares_8bit_copy_on_the_pool(qtbot, tmp_path, monkeypatch, hold):
    import nocturne.ui.main_window as mw
    from tests.ui.test_main_window import _stretched_window
    win = _stretched_window(qtbot, tmp_path)
    win._async_enabled = True
    opened = []

    class _Fake:
        def __init__(self, rgb8, meta, *a, **k):
            opened.append((rgb8, meta, k))

        def exec(self):
            return 0
    monkeypatch.setattr(mw, "ShareDialog", _Fake)
    data = win.project.current().data
    held = hold(mw, "_share_rgb8")
    win._share()
    held.wait(qtbot)
    _responsive(qtbot)
    assert opened == []
    held.release()
    qtbot.waitUntil(lambda: bool(opened), timeout=5000)
    assert held.on_ui == []
    rgb8, meta, k = opened[0]
    assert np.array_equal(rgb8, held.real(data))
    assert k["is_async"]() is True


def test_share_opens_on_the_pressed_picture_even_if_a_step_started(qtbot, tmp_path,
                                                                    monkeypatch, hold):
    """A step started while the 8-bit copy was made must not swallow the
    press: the dialog opens anyway, on the picture as it was at the press, and
    the step lands behind it (ruled 2026-10-05: no silent drops)."""
    import nocturne.ui.main_window as mw
    from tests.ui.test_main_window import _stretched_window
    win = _stretched_window(qtbot, tmp_path)
    win._async_enabled = True
    opened = []

    class _Fake:
        def __init__(self, rgb8, meta, *a, **k):
            opened.append((rgb8, win._busy))

        def exec(self):
            return 0
    monkeypatch.setattr(mw, "ShareDialog", _Fake)
    held = hold(mw, "_share_rgb8")
    pressed = win.project.current().data.copy()
    win._share()
    held.wait(qtbot)
    step = threading.Event()
    win._run_busy(lambda: step.wait(20), lambda _r: None, "Holding", "Held step")
    try:
        assert win._busy, "precondition: a step is running"
        held.release()
        qtbot.waitUntil(lambda: bool(opened), timeout=5000)
    finally:
        step.set()
    held_rgb, busy_at_open = opened[0]
    assert busy_at_open is True, "the dialog must open while the step still runs"
    assert np.array_equal(held_rgb, held.real(pressed))
    qtbot.waitUntil(lambda: not win._busy, timeout=5000)


def test_a_share_copy_landing_on_a_replaced_workspace_opens_nothing(qtbot, tmp_path, monkeypatch, hold):
    import nocturne.ui.main_window as mw
    from tests.ui.test_main_window import _stretched_window
    win = _stretched_window(qtbot, tmp_path)
    win._async_enabled = True
    opened = []
    monkeypatch.setattr(mw, "ShareDialog", lambda *a, **k: opened.append(1))
    held = hold(mw, "_share_rgb8")
    win._share()
    held.wait(qtbot)
    win._project_gen += 1                # a new image was opened meanwhile
    held.release()
    qtbot.waitUntil(lambda: not win._share_pending, timeout=5000)
    qtbot.wait(100)
    assert opened == []


# =============================================================================
# Upscale
# =============================================================================
def _up_img(h=60, w=60):
    d = np.full((h, w, 3), 0.1, np.float32)
    d[30, 30] = 1.0
    d[10, 45] = 0.8
    return AstroImage(d, is_linear=False, metadata={"target": "M42", "source_label": "m42.fits"})


def _upscale(qtbot, **kw):
    from nocturne.ui.upscale_dialog import UpscaleDialog
    d = UpscaleDialog(_up_img(), {"target": "M42", "source_label": "m42.fits"}, Settings(), **kw)
    qtbot.addWidget(d)
    d.show()
    return d


def _up_inline(tighten):
    from nocturne.core.upscale import LanczosEngine, finish_upscale, prepare_upscale
    return finish_upscale(prepare_upscale(_up_img(), None, LanczosEngine()), tighten)


def test_upscales_first_render_is_made_on_the_pool(qtbot, hold):
    import nocturne.ui.upscale_dialog as ud
    d = _upscale(qtbot)
    held = hold(ud, "finish_upscale")
    d.upscale_btn.click()
    held.wait(qtbot)
    _responsive(qtbot)
    assert d._result is None and d.pages.currentIndex() == 0
    held.release()
    qtbot.waitUntil(lambda: d.pages.currentIndex() == 1 and not d._busy, timeout=10000)
    assert held.on_ui == [], "the first render ran on the UI thread"
    assert np.array_equal(d._result.data, _up_inline(d._tighten).data)


def test_upscale_export_writes_the_value_at_the_press(qtbot, hold, tmp_path, monkeypatch,
                                                      request):
    """The slider stays live through the export (it drives re-renders), so
    the export snapshots it: moved mid-save, the file still holds the value
    the user pressed Export at."""
    import nocturne.ui.upscale_dialog as ud
    inline = _upscale(qtbot)
    inline._run_upscale()
    inline.tighten_slider.setValue(90)
    inline._do_export(str(tmp_path / "inline.tiff"))
    d = _upscale(qtbot, is_async=ON)
    d._run_upscale()
    d.tighten_slider.setValue(90)            # the debounce has not fired
    finish = hold(ud, "finish_upscale")
    finish.release()                         # recorded, not held: the job itself is
    held = _HoldJobs(monkeypatch, ud)
    request.addfinalizer(held.release)
    out = tmp_path / "pooled.tiff"
    d._do_export(str(out))
    held.wait(qtbot)
    _responsive(qtbot)
    assert not out.exists()
    assert not d._export_btn.isEnabled() and not d._open_copy_btn.isEnabled()
    assert not d.change_crop_btn.isEnabled()
    assert d._close_btn.isEnabled() and d.tighten_slider.isEnabled()
    assert not d.status_ring.isHidden()
    d.tighten_slider.setValue(20)            # moved mid-save
    held.release()
    qtbot.waitUntil(lambda: d.status.text().startswith("Saved"), timeout=5000)
    qtbot.waitUntil(lambda: d.change_crop_btn.isEnabled(), timeout=5000)
    assert finish.started and finish.on_ui == [], "the finish ran on the UI thread"
    assert out.read_bytes() == (tmp_path / "inline.tiff").read_bytes()
    assert (tmp_path / "pooled.txt").read_text() == (tmp_path / "inline.txt").read_text()
    assert d._export_btn.isEnabled() and d.status_ring.isHidden()


def test_an_upscale_export_runs_no_second_finish_and_the_view_catches_up(
        qtbot, hold, tmp_path, monkeypatch, request):
    """One finish at a time (memory), and a slider moved mid-save is drawn
    once the save lands — not left stale."""
    import nocturne.ui.upscale_dialog as ud
    d = _upscale(qtbot, is_async=ON)
    d._run_upscale()
    d.tighten_slider.setValue(90)
    held = _HoldJobs(monkeypatch, ud)
    request.addfinalizer(held.release)
    d._do_export(str(tmp_path / "x.tiff"))
    held.wait(qtbot)
    assert not d._tighten_timer.isActive(), "a pending re-render would run beside the export"
    d.tighten_slider.setValue(30)            # moved mid-save; the debounce fires mid-save
    qtbot.wait(ud.TIGHTEN_DEBOUNCE_MS + 100)
    assert len(held.started) == 1, "a second finish was started during the export"
    held.release()
    qtbot.waitUntil(lambda: d._result.metadata["upscale"]["tighten"] == 0.30
                    and not d._busy and d._rerenders == 0, timeout=5000)
    assert np.array_equal(d._result.data, _up_inline(0.30).data)


def test_upscale_open_as_copy_hands_over_the_value_at_the_press(qtbot, hold):
    import nocturne.ui.upscale_dialog as ud
    got = []
    d = _upscale(qtbot, is_async=ON, on_open_copy=lambda img: got.append(img))
    d._run_upscale()
    d.tighten_slider.setValue(10)
    held = hold(ud, "finish_upscale")
    d._open_copy_btn.click()
    held.wait(qtbot)
    _responsive(qtbot)
    assert got == []
    held.release()
    qtbot.waitUntil(lambda: bool(got), timeout=5000)
    assert np.array_equal(got[0].data, _up_inline(0.10).data)
    assert d.result() == QDialog.DialogCode.Accepted


def test_an_upscale_export_landing_after_close_does_nothing(qtbot, hold, tmp_path):
    import nocturne.ui.upscale_dialog as ud
    d = _upscale(qtbot, is_async=ON)
    d._run_upscale()
    d.tighten_slider.setValue(70)
    held = hold(ud, "finish_upscale")
    d._do_export(str(tmp_path / "x.tiff"))
    held.wait(qtbot)
    d.reject()
    status = d.status.text()
    held.release()
    _drain(qtbot)
    assert d.status.text() == status and d._result is None


# =============================================================================
# Starless Levels
# =============================================================================
def _split():
    starless = np.full((32, 32, 3), 0.30, np.float32)
    starless[8:16, 8:16] = 0.60
    stars = np.zeros((32, 32, 3), np.float32)
    stars[0, 0] = 0.95
    return (AstroImage(starless, is_linear=False, metadata={}),
            AstroImage(stars, is_linear=False, metadata={}))


def _levels(qtbot, got):
    from nocturne.ui.starless_levels_dialog import StarlessLevelsDialog
    d = StarlessLevelsDialog(*_split(), on_apply=lambda img, v: got.append((img, v)),
                             is_async=ON)
    qtbot.addWidget(d)
    d.show()
    d.handles.set_range(0.1, 0.8)
    return d


def test_starless_levels_apply_composes_on_the_pool(qtbot, hold):
    import nocturne.ui.starless_levels_dialog as sl
    from nocturne.core.enhance import starless_levels_layers
    got = []
    d = _levels(qtbot, got)
    held = hold(sl, "starless_levels_layers")
    d.ok_btn.click()
    held.wait(qtbot)
    _responsive(qtbot)
    assert got == []
    assert not d.handles.isEnabled() and not d.ok_btn.isEnabled()
    assert not d.black_val.isEnabled() and not d.reset_btn.isEnabled()
    cancel = d._buttons.button(d._buttons.StandardButton.Cancel)
    assert cancel.isEnabled()
    assert not d.waiting.isHidden(), "the wait shows no ring"
    held.release()
    qtbot.waitUntil(lambda: bool(got), timeout=5000)
    img, values = got[0]
    assert held.started and all(a[2:] == (0.1, 0.8) for a in held.started)
    assert values == (0.1, 0.8)
    expected = starless_levels_layers(*_split(), 0.1, 0.8)
    assert np.array_equal(img.data, expected.data)
    assert d.result() == QDialog.DialogCode.Accepted


def test_a_failed_starless_apply_message_goes_with_the_next_render(qtbot, monkeypatch):
    import nocturne.ui.starless_levels_dialog as sl
    real = sl.starless_levels_layers

    def boom(*a, **k):
        if threading.current_thread() is threading.main_thread():
            return real(*a, **k)
        raise RuntimeError("no memory")
    got = []
    d = _levels(qtbot, got)
    monkeypatch.setattr(sl, "starless_levels_layers", boom)
    d.ok_btn.click()
    qtbot.waitUntil(lambda: not d._applying, timeout=5000)
    assert not d.waiting.isHidden() and "Could not apply" in d.waiting.text()
    d.handles.set_range(0.15, 0.8)
    d._render_preview()                      # the next render, as a handle drag queues
    assert d.waiting.isHidden(), "the failure message covers the preview for good"


def test_a_starless_levels_apply_landing_after_cancel_applies_nothing(qtbot, hold):
    import nocturne.ui.starless_levels_dialog as sl
    got = []
    d = _levels(qtbot, got)
    held = hold(sl, "starless_levels_layers")
    d.ok_btn.click()
    held.wait(qtbot)
    d.reject()
    held.release()
    _drain(qtbot)
    assert got == []
    assert d.result() == QDialog.DialogCode.Rejected


@pytest.mark.parametrize("which", ["spikes", "levels"])
def test_a_failed_apply_gives_the_window_back(qtbot, monkeypatch, which):
    """Snapshot BEFORE, compare after: unchanged, not merely "enabled"."""
    import nocturne.ui.star_spikes_dialog as sd
    import nocturne.ui.starless_levels_dialog as sl
    got = []

    def boom(*a, **k):
        if threading.current_thread() is threading.main_thread():
            return real(*a, **k)
        raise RuntimeError("no memory")
    if which == "spikes":
        d = _spikes(qtbot, on_apply=lambda img, p: got.append(img))
        d.length_slider.setValue(40)
        real = sd._render
        monkeypatch.setattr(sd, "_render", boom)
        go = d.apply_btn
    else:
        d = _levels(qtbot, got)
        real = sl.starless_levels_layers
        monkeypatch.setattr(sl, "starless_levels_layers", boom)
        go = d.ok_btn
    from PySide6.QtWidgets import QAbstractButton, QAbstractSlider, QWidget
    inputs = [w for w in d.findChildren(QWidget)
              if isinstance(w, (QAbstractButton, QAbstractSlider))]
    before = [(w, w.isEnabled()) for w in inputs]
    go.click()
    qtbot.waitUntil(lambda: not d._applying, timeout=5000)
    assert got == [] and d.isVisible()
    assert [(w, w.isEnabled()) for w in inputs] == before
    assert go.isEnabled(), "and it can be pressed again"


# =============================================================================
# The plumbing, and what the jobs hold
# =============================================================================
@pytest.mark.parametrize("switch", [True, False])
def test_every_opener_hands_its_dialog_the_windows_switch(qtbot, tmp_path, monkeypatch, switch):
    """Off, the dialogs run inline — as every MainWindow test expects; on, as
    the shipped app runs. A dialog left on its standalone default would freeze
    the app again while every test still passed."""
    import nocturne.ui.main_window as mw
    from nocturne.ui.share_dialog import ShareDialog
    from nocturne.ui.star_spikes_dialog import StarSpikesDialog
    from nocturne.ui.starless_levels_dialog import StarlessLevelsDialog
    from tests.ui.test_main_window import _stretched_window
    win = _stretched_window(qtbot, tmp_path)
    win._async_enabled = switch
    seen = {}

    def recording(name):
        def exec_(self):
            seen[name] = self._is_async()
            self.reject()
            return 0
        return exec_
    for name, cls in (("spikes", StarSpikesDialog), ("share", ShareDialog),
                      ("upscale", mw.UpscaleDialog), ("levels", StarlessLevelsDialog)):
        monkeypatch.setattr(cls, "exec", recording(name))
    win._open_star_spikes()
    win._share()
    qtbot.waitUntil(lambda: "share" in seen, timeout=5000)
    win._upscale()
    win._open_starless_levels()
    assert seen == {"spikes": switch, "share": switch, "upscale": switch, "levels": switch}


def _qt_held(fn, depth: int = 0) -> list:
    """Qt objects a job's closure reaches — a dialog, a widget, a bound
    method of one. A job must hold values, never the window."""
    found = []
    if isinstance(fn, QObject):
        return [fn]
    if getattr(fn, "__self__", None) is not None and isinstance(fn.__self__, QObject):
        return [fn]
    cells = getattr(fn, "__closure__", None) or ()
    defaults = getattr(fn, "__defaults__", None) or ()
    for v in [c.cell_contents for c in cells] + list(defaults):
        if isinstance(v, QObject):
            found.append(v)
        elif callable(v) and depth < 3:
            found += _qt_held(v, depth + 1)
    return found


def test_no_job_holds_a_window(qtbot, tmp_path, monkeypatch):
    import nocturne.ui.main_window as mw
    import nocturne.ui.preview_runner as pr
    import nocturne.ui.share_dialog as sh
    import nocturne.ui.star_spikes_dialog as sd
    import nocturne.ui.starless_levels_dialog as sl
    import nocturne.ui.upscale_dialog as ud
    jobs = []
    for m in (mw, pr, sh, sd, sl, ud):
        real = m.run_async

        def recording(pool, fn, *a, _real=real, **k):
            jobs.append(fn)
            return _real(pool, fn, *a, **k)
        monkeypatch.setattr(m, "run_async", recording)

    got = []
    d = _spikes(qtbot, on_apply=lambda img, p: got.append(img))
    d.length_slider.setValue(60)
    d.apply_btn.click()
    qtbot.waitUntil(lambda: bool(got), timeout=5000)

    s = _share(qtbot)
    qtbot.waitUntil(lambda: s._preview_image is not None, timeout=5000)
    s._clipboard_runner = lambda img: got.append(img)
    s._do_copy()
    qtbot.waitUntil(lambda: not s._working, timeout=5000)
    s._do_export(str(tmp_path / "s.jpg"))
    qtbot.waitUntil(lambda: not s._working, timeout=5000)

    u = _upscale(qtbot, is_async=ON)
    u.upscale_btn.click()
    qtbot.waitUntil(lambda: u.pages.currentIndex() == 1 and not u._busy, timeout=10000)
    u.tighten_slider.setValue(5)
    u._do_export(str(tmp_path / "u.tiff"))
    qtbot.waitUntil(lambda: not u._busy, timeout=5000)

    levels = []
    lv = _levels(qtbot, levels)
    lv.ok_btn.click()
    qtbot.waitUntil(lambda: bool(levels), timeout=5000)

    from tests.ui.test_main_window import _stretched_window
    win = _stretched_window(qtbot, tmp_path)
    win._async_enabled = True
    class _Fake:
        def __init__(self, *a, **k):
            got.append("share")

        def exec(self):
            return 0
    monkeypatch.setattr(mw, "ShareDialog", _Fake)
    win._share()
    qtbot.waitUntil(lambda: "share" in got, timeout=5000)

    assert len(jobs) >= 9, f"the exercise did not reach the pool ({len(jobs)} jobs)"
    holding = [(getattr(j, "__qualname__", j), _qt_held(j)) for j in jobs if _qt_held(j)]
    assert holding == []
