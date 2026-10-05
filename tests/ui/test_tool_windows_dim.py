"""The tool windows dim their inputs while they work (spec 2026-10-05 B3).

Each window runs its work on a HELD worker (its module's run_async patched to
wait on an event), so the test can look at the window mid-run. While held,
every input outside a picture/list view is off unless it is marked keep-live
(Close, Cancel, and view-only toggles). After the run, enablement is compared
with a snapshot taken BEFORE it — unchanged, not merely "enabled" (CLAUDE.md).

The audit's data bugs (docs/audit/2026-10-05-busy-controls-audit.md §6) are
asserted as "the input cannot change": a key typed into the field, or a click
on a frame's tick, leaves it exactly as it was.
"""
from __future__ import annotations

import os
import threading
import types

import numpy as np
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (QAbstractButton, QAbstractScrollArea, QAbstractSlider,
                               QAbstractSpinBox, QComboBox, QLineEdit, QPushButton,
                               QWidget)

from nocturne.core.image import AstroImage
from nocturne.settings import Settings
from nocturne.stacking.grade import FrameStats
from nocturne.ui.busy_gate import KEEP_LIVE
from nocturne.ui.curve_editor import CurveEditor
from nocturne.ui.frame_browser import COL_USE
from nocturne.ui.range_handles import RangeHandles

_KINDS = (QAbstractSlider, QAbstractButton, QComboBox, QAbstractSpinBox, QLineEdit,
          CurveEditor, RangeHandles)


# --- looking at a window -------------------------------------------------------
def _in_view(w: QWidget, top: QWidget) -> bool:
    """Inside a picture or list view: its scrollbars and zoom pill are viewing,
    not input, and stay live (audit: keep zoom/pan/Fit live)."""
    p = w.parentWidget()
    while p is not None and p is not top:
        if isinstance(p, QAbstractScrollArea):
            return True
        p = p.parentWidget()
    return False


def _inputs(dlg) -> list:
    return [w for w in dlg.findChildren(QWidget)
            if isinstance(w, _KINDS) and not _in_view(w, dlg)]


def _name(w) -> str:
    text = w.text() if isinstance(w, (QAbstractButton, QLineEdit)) else ""
    return f"{type(w).__name__}:{w.objectName()}:{text}"


def _snapshot(dlg) -> list:
    return [(w, w.isEnabled()) for w in _inputs(dlg)]


def _assert_unchanged(dlg, before) -> None:
    changed = [(_name(w), was, w.isEnabled()) for w, was in before
               if w.isEnabled() != was]
    assert changed == []


def _live(dlg) -> list:
    return [_name(w) for w in _inputs(dlg) if w.isEnabled() and not w.property(KEEP_LIVE)]


def _button(dlg, text: str) -> QPushButton:
    found = [b for b in dlg.findChildren(QPushButton) if b.text() == text]
    assert len(found) == 1, (text, len(found))
    return found[0]


def _assert_gated(dlg, *, cancel: str | None = None) -> None:
    assert _live(dlg) == []
    close = _button(dlg, "Close")
    assert close.isEnabled() and close.property(KEEP_LIVE)
    if cancel is not None:
        assert cancel.isEnabled()


def _browse_of(edit: QLineEdit) -> QPushButton:
    found = [b for b in edit.parentWidget().findChildren(QPushButton)
             if b.text() == "Browse…"]
    assert len(found) == 1
    return found[0]


def _assert_cannot_type(qtbot, edit: QLineEdit) -> None:
    before = edit.text()
    qtbot.keyClicks(edit, "zz")
    assert edit.text() == before


# --- holding the work -----------------------------------------------------------
class _Held:
    def __init__(self, monkeypatch, module, fail: bool = False) -> None:
        self.event = threading.Event()
        self.started: list = []
        real = module.run_async

        def wrapped(pool, fn, *a, **k):
            def held():
                self.started.append(1)
                self.event.wait(20)
                if fail:
                    raise RuntimeError("held run failed")
                return fn()
            return real(pool, held, *a, **k)

        monkeypatch.setattr(module, "run_async", wrapped)

    def wait(self, qtbot, n: int = 1) -> None:
        qtbot.waitUntil(lambda: len(self.started) >= n, timeout=5000)

    def release(self) -> None:
        self.event.set()


@pytest.fixture
def hold(monkeypatch):
    made = []

    def make(module, fail=False):
        h = _Held(monkeypatch, module, fail)
        made.append(h)
        return h
    yield make
    for h in made:          # never leave a pool thread waiting 20 s on a failed test
        h.release()


# --- images and files ---------------------------------------------------------
def _rgb(h=64, w=64, seed=1):
    rng = np.random.default_rng(seed)
    d = (0.2 + 0.05 * rng.random((h, w, 3))).astype(np.float32)
    for _ in range(10):
        y, x = rng.integers(5, h - 5, 2)
        d[y - 1:y + 2, x - 1:x + 2] = 0.95
    return AstroImage(d, is_linear=False, metadata={})


def _layers(base):
    return (AstroImage(base.data * 0.9, is_linear=False, metadata={}),
            AstroImage(np.zeros_like(base.data), is_linear=False, metadata={}))


def _held_splitter(started, event, layers, fail=False):
    def run(_img):
        started.append(1)
        event.wait(20)
        if fail:
            raise RuntimeError("split failed")
        return layers
    return run


def _blob(path, cy, shape=(64, 64)):
    from astropy.io import fits
    yy, xx = np.mgrid[0:shape[0], 0:shape[1]]
    blob = (np.exp(-(((yy - cy) ** 2 + (xx - 32) ** 2) / 18.0)) * 1000 + 10).astype(np.float32)
    h = fits.PrimaryHDU(blob)
    h.header["STACKCNT"] = 20
    h.writeto(path, overwrite=True)
    return str(path)


def _subs(folder, n=6):
    folder.mkdir()
    for i in range(n):
        (folder / f"s{i}.fit").write_text("x")
    return folder


def _grader(paths, on_progress=None, strictness="normal"):
    out = []
    for p in paths:
        s = FrameStats(p, 100, 3.0, 0.02, 0.9, True)
        s.exposure, s.target = 10.0, "M42"
        out.append(s)
    return out


# =============================================================================
# Narrowband and Colour Balance: the split on open, and Apply
# =============================================================================
@pytest.mark.parametrize("fail", [False, True], ids=["lands", "fails"])
@pytest.mark.parametrize("which", ["narrowband", "color_balance"])
def test_star_split_on_open_dims_every_control(qtbot, monkeypatch, which, fail):
    if which == "narrowband":
        from nocturne.ui import narrowband_dialog as m
        make = lambda: m.NarrowbandDialog(Settings(), base)          # noqa: E731
    else:
        from nocturne.ui import color_balance_dialog as m
        make = lambda: m.ColorBalanceDialog(Settings(), base)        # noqa: E731
    monkeypatch.setattr(m, "preferred_splitter", lambda s: object())
    base = _rgb()
    event, started = threading.Event(), []
    d = make()
    d._starx_runner = _held_splitter(started, event, _layers(base), fail)
    qtbot.addWidget(d)
    before = _snapshot(d)
    try:
        d.show()
        qtbot.waitUntil(lambda: started == [1], timeout=5000)
        _assert_gated(d)
    finally:
        event.set()
    qtbot.waitUntil(lambda: d._prev_starless is not None, timeout=5000)
    _assert_unchanged(d, before)


def _split_dialog(qtbot, which):
    base = _rgb()
    starless, stars = _layers(base)
    if which == "narrowband":
        from nocturne.ui import narrowband_dialog as m
        d = m.NarrowbandDialog(Settings(), base, starless=starless, stars=stars)
        go = d.apply
    else:
        from nocturne.ui import color_balance_dialog as m
        d = m.ColorBalanceDialog(Settings(), base, starless=starless, stars=stars)
        go = d._apply
    qtbot.addWidget(d)
    d.show()
    qtbot.waitUntil(lambda: d._prev_starless is not None, timeout=5000)
    return m, d, go


@pytest.mark.parametrize("which", ["narrowband", "color_balance"])
def test_apply_dims_every_control_and_a_failure_gives_them_back(qtbot, hold, which):
    m, d, go = _split_dialog(qtbot, which)
    if which == "narrowband":
        d.palette_box.setCurrentText("Pseudo-SHO")     # Green blend legitimately off
        assert not d.blend_slider.isEnabled()
    before = _snapshot(d)
    held = hold(m, fail=True)
    go()
    held.wait(qtbot)
    _assert_gated(d)
    held.release()
    qtbot.waitUntil(lambda: d.status.text().startswith(("Apply failed", "Could not apply")),
                    timeout=5000)
    _assert_unchanged(d, before)


# =============================================================================
# Upscale: prepare and re-render
# =============================================================================
def _upscale(qtbot):
    from nocturne.ui import upscale_dialog as m
    d = m.UpscaleDialog(_rgb(60, 60), {}, Settings())
    qtbot.addWidget(d)
    d.show()
    return m, d


def _press_picker(d) -> None:
    vp = d.picker.viewport()
    QTest.mouseClick(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     vp.rect().center())


def test_upscale_prepare_dims_shape_buttons_and_locks_the_crop(qtbot, hold):
    m, d = _upscale(qtbot)
    assert not d.picker.crop_box_visible()
    before = _snapshot(d)
    held = hold(m, fail=True)
    d._on_upscale_clicked()
    held.wait(qtbot)
    _assert_gated(d, cancel=d.cancel_btn)
    assert all(not b.isEnabled() for b in d.shape_buttons.values())
    _press_picker(d)                       # a crop drawn mid-run
    assert not d.picker.crop_box_visible()
    held.release()
    qtbot.waitUntil(lambda: not d._busy, timeout=5000)
    _assert_unchanged(d, before)
    _press_picker(d)                       # and the box is drawable again
    assert d.picker.crop_box_visible()


def test_upscale_rerender_dims_crop_controls_and_gives_them_back(qtbot, hold):
    m, d = _upscale(qtbot)
    d._on_upscale_clicked()
    qtbot.waitUntil(lambda: d._layers is not None and d.pages.currentIndex() == 1,
                    timeout=10000)
    before = _snapshot(d)
    held = hold(m)
    d._tighten = 0.10
    d._rerender()
    held.wait(qtbot)
    _assert_gated(d)
    assert all(not b.isEnabled() for b in d.shape_buttons.values())
    assert not d.change_crop_btn.isEnabled()
    # The slider that drives the re-render stays live: disabling it would
    # end a drag the moment the debounce fired (latest-wins handles it).
    assert d.tighten_slider.isEnabled()
    held.release()
    qtbot.waitUntil(lambda: d._result.metadata["upscale"]["tighten"] == 0.10, timeout=5000)
    qtbot.waitUntil(lambda: d.change_crop_btn.isEnabled(), timeout=5000)
    _assert_unchanged(d, before)


# =============================================================================
# Combine: the alignment check and the combine
# =============================================================================
def _combine(qtbot, tmp_path):
    from nocturne.ui import combine_dialog as m
    ha = _blob(tmp_path / "ha.fits", 32)
    o1 = _blob(tmp_path / "o1.fits", 32)
    d = m.CombineDialog(Settings())
    qtbot.addWidget(d)
    d.show()
    d.ha_edit.setText(ha)
    d.oiii_edit.setText(o1)
    return m, d


@pytest.mark.parametrize("fail", [False, True], ids=["lands", "fails"])
def test_combine_alignment_check_locks_the_oiii_file(qtbot, hold, tmp_path, fail):
    m, d = _combine(qtbot, tmp_path)
    before = _snapshot(d)
    held = hold(m, fail=fail)
    d.check_alignment()
    held.wait(qtbot)
    _assert_gated(d)
    # The audit's bug: OIII swapped mid-read, the stale shift trusted.
    assert not d.oiii_edit.isEnabled() and not _browse_of(d.oiii_edit).isEnabled()
    _assert_cannot_type(qtbot, d.oiii_edit)
    held.release()
    qtbot.waitUntil(lambda: not d._busy, timeout=5000)
    _assert_unchanged(d, before)


def test_combine_run_dims_every_control(qtbot, hold, tmp_path):
    m, d = _combine(qtbot, tmp_path)
    d.check_alignment()
    qtbot.waitUntil(lambda: not d._busy and d._small is not None, timeout=5000)
    before = _snapshot(d)
    held = hold(m, fail=True)
    d.run()
    held.wait(qtbot)
    _assert_gated(d)
    held.release()
    qtbot.waitUntil(lambda: not d._busy, timeout=5000)
    _assert_unchanged(d, before)


# =============================================================================
# Ha/OIII and Stack: grading, and the run — the frame list included
# =============================================================================
def _tick_rect_point(browser, source_row: int) -> QPoint:
    proxy_index = browser.proxy.mapFromSource(browser.model.index(source_row, COL_USE))
    rect = browser.view.visualRect(proxy_index)
    return QPoint(rect.left() + 10, rect.center().y())


def _click_tick(browser, source_row: int) -> None:
    QTest.mouseClick(browser.view.viewport(), Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier, _tick_rect_point(browser, source_row))


def _ticks(browser) -> list:
    return [bool(s.included) for s in browser.frames()]


def _assert_ticks_frozen(qtbot, browser) -> None:
    before = _ticks(browser)
    _click_tick(browser, 0)
    browser.view.setCurrentIndex(browser.proxy.mapFromSource(browser.model.index(1, 0)))
    QTest.keyClick(browser.view, Qt.Key.Key_Space)
    assert _ticks(browser) == before


def _assert_click_ticks(browser) -> None:
    """Precondition: the click lands on the box, so a frozen tick is the gate's
    doing and not a click that missed."""
    was = browser.is_checked(0)
    _click_tick(browser, 0)
    assert browser.is_checked(0) is (not was)
    _click_tick(browser, 0)
    assert browser.is_checked(0) is was


def _haoiii(qtbot, tmp_path):
    from nocturne.ui import haoiii_dialog as m
    d = m.HaOIIIDialog(Settings())
    qtbot.addWidget(d)
    d.show()
    d._grade_runner = _grader
    d.folder_edit.setText(str(_subs(tmp_path / "A")))
    return m, d


def _stack(qtbot, tmp_path):
    from nocturne.ui import stack_dialog as m
    d = m.StackDialog(Settings())
    qtbot.addWidget(d)
    d.show()
    d._find_panels = lambda paths, on_progress=None: []
    d._confirm_stop = lambda: True      # a failed assertion mid-run must not hang teardown
    d._grade_runner = _grader
    d.folder_edit.setText(str(_subs(tmp_path / "A")))
    return m, d


@pytest.mark.parametrize("which", ["haoiii", "stack"])
def test_grading_locks_the_folder(qtbot, hold, tmp_path, which):
    m, d = (_haoiii if which == "haoiii" else _stack)(qtbot, tmp_path)
    before = _snapshot(d)
    held = hold(m, fail=True)
    d.grade()
    held.wait(qtbot)
    _assert_gated(d, cancel=d._cancel_btn)
    # The audit's bug: folder B picked while A grades.
    assert not d.folder_edit.isEnabled() and not _browse_of(d.folder_edit).isEnabled()
    _assert_cannot_type(qtbot, d.folder_edit)
    held.release()
    qtbot.waitUntil(lambda: not d._busy, timeout=5000)
    _assert_unchanged(d, before)


@pytest.mark.parametrize("which", ["haoiii", "stack"])
def test_a_graded_folder_comes_back_live(qtbot, hold, tmp_path, which):
    m, d = (_haoiii if which == "haoiii" else _stack)(qtbot, tmp_path)
    held = hold(m)
    d.grade()
    held.wait(qtbot)
    held.release()
    qtbot.waitUntil(lambda: not d._busy and bool(d._stats), timeout=5000)
    assert d.folder_edit.isEnabled() and _browse_of(d.folder_edit).isEnabled()
    assert d._stack_btn.isEnabled()
    _assert_click_ticks(d.browser)


@pytest.mark.parametrize("which", ["haoiii", "stack"])
def test_the_run_freezes_the_frame_ticks(qtbot, hold, tmp_path, which):
    m, d = (_haoiii if which == "haoiii" else _stack)(qtbot, tmp_path)
    d.grade()
    qtbot.waitUntil(lambda: not d._busy and bool(d._stats), timeout=5000)
    if which == "haoiii":
        d.output_edit.setText(str(tmp_path / "out.fits"))
    _assert_click_ticks(d.browser)
    before = _snapshot(d)
    held = hold(m, fail=True)
    d.run()
    held.wait(qtbot)
    _assert_gated(d, cancel=d._cancel_btn)
    assert not d.folder_edit.isEnabled()
    # The audit's bug: frames re-ticked mid-stack, the file named for 6, recorded as 4.
    _assert_ticks_frozen(qtbot, d.browser)
    held.release()
    qtbot.waitUntil(lambda: not d._busy, timeout=5000)
    _assert_unchanged(d, before)
    _assert_click_ticks(d.browser)


def test_stack_mosaic_check_follows_the_grade_not_the_gate(qtbot, hold, tmp_path):
    """mosaic_check was ON before a re-grade that finds one pointing: the gate
    took it, _show_panels turns it off — it must stay off (re-derived after
    the gate opens, not re-lit by it)."""
    m, d = _stack(qtbot, tmp_path)
    d.mosaic_check.setEnabled(True)
    held = hold(m)
    d.grade()
    held.wait(qtbot)
    held.release()
    qtbot.waitUntil(lambda: not d._busy and bool(d._stats), timeout=5000)
    assert not d.mosaic_check.isEnabled()


# =============================================================================
# Batch
# =============================================================================
@pytest.mark.parametrize("fail", [False, True], ids=["lands", "fails"])
def test_batch_run_dims_every_control(qtbot, hold, monkeypatch, tmp_path, fail):
    from nocturne.ui import batch_dialog as m
    monkeypatch.setattr(m, "load_recipe", lambda p: object())
    monkeypatch.setattr(m, "missing_tools", lambda r, s: [])
    monkeypatch.setattr(m, "preflight", lambda r, s: None)
    monkeypatch.setattr(m, "preflight_summary", lambda p: "plan")
    d = m.BatchDialog(Settings())
    qtbot.addWidget(d)
    d.show()
    (tmp_path / "x.fits").write_text("x")
    rp = tmp_path / "r.json"
    rp.write_text("{}")
    d.recipe_edit.setText(str(rp))
    d.input_edit.setText(str(tmp_path))
    d.output_edit.setText(str(tmp_path / "out"))
    d._batch_runner = lambda *a, **k: []
    before = _snapshot(d)
    held = hold(m, fail=fail)
    d.run()
    held.wait(qtbot)
    _assert_gated(d, cancel=d.cancel_btn)
    _assert_cannot_type(qtbot, d.recipe_edit)
    held.release()
    qtbot.waitUntil(lambda: d._active_token is None, timeout=5000)
    _assert_unchanged(d, before)
