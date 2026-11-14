"""The Background paint editor: Sky / Nebula / Erase brushes over the picture.

Mouse behaviour is driven with QApplication.sendEvent, never qtbot.mouseMove
(CLAUDE.md: mouseMove is unreliable here).
"""
import numpy as np
import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QEvent, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent, QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from nocturne.core.image import AstroImage  # noqa: E402
from nocturne.steps.background import BackgroundStep  # noqa: E402
from nocturne.ui.background_paint_dialog import (BackgroundPaintDialog,  # noqa: E402
                                                 _pixmap_rgb8)


def _base(h=300, w=450, mono=False):
    rng = np.random.default_rng(1)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    grad = 0.05 + 0.04 * xx / w + 0.02 * yy / h          # a light-pollution ramp
    a = grad + rng.normal(0, 0.003, (h, w)).astype(np.float32)
    a[100:180, 150:260] += 0.05                           # a "nebula"
    if not mono:
        a = np.stack([a, a * 0.95, a * 1.05], axis=2)
    return AstroImage(np.clip(a, 0, 1).astype(np.float32), is_linear=True, metadata={})


def _open(qtbot, base=None, option=None, on_apply=None):
    dlg = BackgroundPaintDialog(base if base is not None else _base(),
                                option=option, on_apply=on_apply)
    qtbot.addWidget(dlg)
    dlg.resize(1000, 700)
    dlg.show()
    qtbot.waitExposed(dlg)
    dlg._render()
    return dlg


def _send(view, kind, pos, button, held, mods=Qt.KeyboardModifier.NoModifier):
    p = QPointF(*pos)
    QApplication.sendEvent(view, QMouseEvent(kind, p, view.mapToGlobal(p),
                                             button, held, mods))


def _drag(view, pts):
    L, N = Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton
    _send(view, QEvent.Type.MouseButtonPress, pts[0], L, L)
    for p in pts[1:]:
        _send(view, QEvent.Type.MouseMove, p, N, L)
    _send(view, QEvent.Type.MouseButtonRelease, pts[-1], L, N)


def _expected_image_xy(dlg, wx, wy):
    """Independent of the view's own mapping: the visible rect, and the pixmap
    centred in the label."""
    view = dlg.view
    x0, y0, x1, y1 = view.visible_rect(dlg._base.data.shape)
    pm = view.pixmap()
    ox = (view.width() - pm.width()) / 2
    oy = (view.height() - pm.height()) / 2
    return (x0 + (wx - ox) * (x1 - x0) / pm.width(),
            y0 + (wy - oy) * (y1 - y0) / pm.height())


def _centre(dlg):
    return dlg.view.width() / 2, dlg.view.height() / 2


def test_drag_with_sky_brush_records_a_sky_stroke_in_image_coords(qtbot):
    dlg = _open(qtbot)
    dlg.view.set_zoom(3.0)
    dlg.view._centre = [0.7, 0.6]
    dlg.view._clamp()
    dlg._render()
    x0, y0, _, _ = dlg.view.visible_rect(dlg._base.data.shape)
    assert x0 > 0 and y0 > 0, "fixture not zoomed: mapping would be trivial"
    dlg.sky_btn.click()
    dlg.size_slider.setValue(20)
    cx, cy = _centre(dlg)
    pts = [(cx - 60, cy), (cx, cy + 10), (cx + 60, cy + 20)]
    _drag(dlg.view, pts)
    strokes = dlg.option()["strokes"]
    assert len(strokes) == 1
    s = strokes[0]
    assert s["kind"] == "sky"
    first, last = s["points"][0], s["points"][-1]
    ex0, ey0 = _expected_image_xy(dlg, *pts[0])
    ex1, ey1 = _expected_image_xy(dlg, *pts[-1])
    assert first == pytest.approx([ex0, ey0], abs=0.15)
    assert last == pytest.approx([ex1, ey1], abs=0.15)
    # radius: slider px times base px per widget px — about 1/3 at 3x zoom here
    x0, _, x1, _ = dlg.view.visible_rect(dlg._base.data.shape)
    assert s["radius"] == pytest.approx(20 * (x1 - x0) / dlg.view.pixmap().width(), abs=0.1)


def test_erase_stroke_is_recorded_after(qtbot):
    dlg = _open(qtbot)
    cx, cy = _centre(dlg)
    dlg.nebula_btn.click()
    _drag(dlg.view, [(cx - 30, cy), (cx + 30, cy)])
    dlg.erase_btn.click()
    _drag(dlg.view, [(cx - 10, cy), (cx + 10, cy)])
    kinds = [s["kind"] for s in dlg.option()["strokes"]]
    assert kinds == ["nebula", "erase"]


def test_space_drag_pans_and_paints_nothing(qtbot):
    dlg = _open(qtbot)
    dlg.view.set_zoom(4.0)
    dlg._render()
    before = list(dlg.view._centre)
    QApplication.sendEvent(dlg.view, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Space,
                                               Qt.KeyboardModifier.NoModifier))
    cx, cy = _centre(dlg)
    _drag(dlg.view, [(cx, cy), (cx + 40, cy + 30)])
    QApplication.sendEvent(dlg.view, QKeyEvent(QEvent.Type.KeyRelease, Qt.Key.Key_Space,
                                               Qt.KeyboardModifier.NoModifier))
    assert dlg.option()["strokes"] == []
    assert dlg.view._centre != before
    # and once Space is released, a drag paints again
    _drag(dlg.view, [(cx, cy), (cx + 20, cy)])
    assert len(dlg.option()["strokes"]) == 1


def test_clear_all_empties_strokes(qtbot):
    dlg = _open(qtbot)
    cx, cy = _centre(dlg)
    _drag(dlg.view, [(cx, cy), (cx + 20, cy)])
    assert dlg.option()["strokes"]
    dlg.clear_btn.click()
    assert dlg.option()["strokes"] == []


def test_apply_hands_back_the_option_and_its_result(qtbot):
    """No preview first: Apply runs the fit itself, then hands back the option
    AND the image — the step's own result, so the window commits it as is."""
    got = []
    base = _base()
    dlg = _open(qtbot, base=base, on_apply=lambda o, r: got.append((o, r)))
    dlg.light_btn.click()
    dlg.sky_btn.click()
    cx, cy = _centre(dlg)
    _drag(dlg.view, [(cx, cy), (cx + 25, cy + 5)])
    dlg.apply_btn.click()
    qtbot.waitUntil(lambda: bool(got), timeout=20000)
    assert len(got) == 1
    opt, out = got[0]
    assert opt["method"] == "painted" and opt["amount"] == "light"
    assert [s["kind"] for s in opt["strokes"]] == ["sky"]
    assert opt == dlg.option()
    assert np.array_equal(out.data, BackgroundStep(None).apply(base, opt).data)
    assert dlg.result() == dlg.DialogCode.Accepted
    assert QApplication.overrideCursor() is None


def test_apply_reuses_the_previewed_result(qtbot, monkeypatch):
    """The preview IS the commit: no second fit."""
    import nocturne.core.painted_background as pb
    real, calls = pb.apply_painted, []
    monkeypatch.setattr(pb, "apply_painted",
                        lambda *a: calls.append(1) or real(*a))
    got = []
    dlg = _open(qtbot, on_apply=lambda o, r: got.append((o, r)))
    cx, cy = _centre(dlg)
    _drag(dlg.view, [(cx, cy), (cx + 25, cy + 5)])
    dlg.preview_btn.click()
    qtbot.waitUntil(lambda: dlg._result is not None and not dlg._result_busy,
                    timeout=20000)
    shown = dlg._result
    dlg.apply_btn.click()
    assert len(got) == 1 and got[0][1] is shown
    assert len(calls) == 1


def test_a_failed_apply_keeps_the_dialog_and_the_strokes(qtbot):
    """Nebula everywhere: the fit fails. Closing first lost the strokes, and
    the window had already discarded the old Background and later steps."""
    got = []
    dlg = _open(qtbot, on_apply=lambda o, r: got.append((o, r)))
    dlg.nebula_btn.click()
    dlg.size_slider.setValue(dlg.size_slider.maximum())
    w, h = dlg.view.width(), dlg.view.height()
    for y in range(0, h, 40):
        _drag(dlg.view, [(0, y), (w, y)])
    strokes = dlg.option()["strokes"]
    dlg.apply_btn.click()
    qtbot.waitUntil(lambda: "Too little sky" in dlg.status.text(), timeout=20000)
    assert got == []
    assert dlg.isVisible() and dlg.result() != dlg.DialogCode.Accepted
    assert not getattr(dlg, "_closed", False)
    assert dlg.option()["strokes"] == strokes
    assert dlg.apply_btn.isEnabled() and dlg.view.isEnabled()
    assert QApplication.overrideCursor() is None


def test_default_amount_is_strong(qtbot):
    dlg = _open(qtbot)
    assert dlg.option()["amount"] == "strong"
    assert dlg.strong_btn.isChecked() and not dlg.light_btn.isChecked()


def test_seeded_option_restores_strokes_and_amount(qtbot):
    seed = {"method": "painted", "amount": "light", "strokes": [
        {"kind": "sky", "radius": 12.0, "points": [[10.0, 20.0], [40.0, 22.5]]},
        {"kind": "erase", "radius": 5.0, "points": [[15.0, 20.0]]}]}
    dlg = _open(qtbot, option=seed)
    assert dlg.option() == seed
    assert dlg.light_btn.isChecked()
    # and an edit appends rather than replaces
    cx, cy = _centre(dlg)
    _drag(dlg.view, [(cx, cy), (cx + 10, cy)])
    assert dlg.option()["strokes"][:2] == seed["strokes"]


def test_cancel_discards(qtbot):
    got = []
    dlg = _open(qtbot, on_apply=got.append)
    cx, cy = _centre(dlg)
    _drag(dlg.view, [(cx, cy), (cx + 10, cy)])
    dlg.reject()
    assert got == []


def test_preview_equals_apply_result(qtbot):
    """The preview is the Background step's own painted route on the FULL base
    — the same code Apply's option replays through — and the pixels shown at
    fit are that result, under the original view's display stretch."""
    base = _base()
    dlg = _open(qtbot, base=base)
    dlg.sky_btn.click()
    dlg.size_slider.setValue(30)
    _drag(dlg.view, [(dlg.view.width() * 0.8, 60), (dlg.view.width() * 0.85, 120)])
    dlg.nebula_btn.click()
    cx, cy = _centre(dlg)
    _drag(dlg.view, [(cx - 20, cy), (cx + 20, cy)])
    dlg.preview_btn.click()
    qtbot.waitUntil(lambda: dlg._result is not None, timeout=20000)
    dlg.show_mask_check.setChecked(False)       # compare the picture, not the paint
    dlg._render()

    expected = BackgroundStep(None).apply(base, dlg.option())
    assert dlg._result.data.shape == base.data.shape
    assert np.array_equal(dlg._result.data, expected.data)

    shown = _pixmap_rgb8(dlg.view.pixmap())
    want = _pixmap_rgb8(dlg._pixmap_for_image(expected, dlg.view.visible_rect(base.data.shape)))
    assert np.array_equal(shown, want)
    # the result is shown under the ORIGINAL's stretch numbers, not re-measured
    from nocturne.ui.background_paint_dialog import _stretch_params, _stretched
    from nocturne.ui.curves_dialog import _downscale, _pixmap_for
    small = _downscale(expected, max_edge=max(dlg.view.width(), dlg.view.height()))
    manual = _pixmap_for(AstroImage(_stretched(small.data, _stretch_params(base.data)),
                                    is_linear=False, metadata={}), dlg.view.size())
    assert np.array_equal(shown, _pixmap_rgb8(manual))
    # and it is not just the original again: the gradient came out
    orig = _pixmap_rgb8(dlg._pixmap_for_image(base, dlg.view.visible_rect(base.data.shape)))
    assert not np.array_equal(shown, orig)

    # toggling back shows the painted view
    dlg.preview_btn.click()
    dlg._render()
    assert not dlg._showing_result()


def test_preview_error_is_shown_not_raised(qtbot):
    """Nebula over everything leaves no sky: the core's message reaches the
    status line and the dialog stays usable."""
    dlg = _open(qtbot)
    dlg.nebula_btn.click()
    dlg.size_slider.setValue(dlg.size_slider.maximum())
    w, h = dlg.view.width(), dlg.view.height()
    for y in range(0, h, 40):
        _drag(dlg.view, [(0, y), (w, y)])
    dlg.preview_btn.click()
    qtbot.waitUntil(lambda: "Too little sky" in dlg.status.text(), timeout=20000)
    assert not dlg.preview_btn.isChecked()
    assert QApplication.overrideCursor() is None


def test_auto_mask_runs_off_the_gui_thread_and_lands(qtbot):
    dlg = _open(qtbot)
    dlg.auto_btn.click()
    assert dlg._auto is None or dlg._auto_busy      # not computed inline
    qtbot.waitUntil(lambda: dlg._auto is not None, timeout=20000)
    assert dlg._auto.shape == dlg._base.data.shape[:2]
    dlg.auto_btn.click()
    assert dlg._auto is None


def test_mono_base_opens_and_paints(qtbot):
    base = _base(mono=True)
    dlg = _open(qtbot, base=base)
    cx, cy = _centre(dlg)
    _drag(dlg.view, [(cx, cy), (cx + 30, cy + 10)])
    assert len(dlg.option()["strokes"]) == 1
    dlg.preview_btn.click()
    qtbot.waitUntil(lambda: dlg._result is not None, timeout=20000)
    assert dlg._result.data.ndim == 2


def test_no_ai_wording(qtbot):
    from PySide6.QtWidgets import QAbstractButton, QLabel
    dlg = _open(qtbot)
    texts = [w.text() for w in dlg.findChildren(QAbstractButton)]
    texts += [w.text() for w in dlg.findChildren(QLabel)]
    texts += [w.toolTip() for w in dlg.findChildren(QAbstractButton)]
    assert not any("AI" in t.split() for t in texts)


def _rgb_of(pm):
    return _pixmap_rgb8(pm)


def test_before_and_result_at_fit_share_one_decimation(qtbot):
    """Larger than the curves dialog's fixed 640 px copy: the base at fit must
    be decimated exactly as the result is, or toggling Preview changes the
    noise texture as well as the gradient."""
    from nocturne.ui.background_paint_dialog import _stretch_params, _stretched
    from nocturne.ui.curves_dialog import _downscale, _pixmap_for
    base = _base(h=900, w=1400)
    dlg = _open(qtbot, base=base)
    dlg.show_mask_check.setChecked(False)
    dlg._render()
    edge = max(dlg.view.width(), dlg.view.height())
    assert _downscale(base).data.shape != _downscale(base, max_edge=edge).data.shape, \
        "fixture does not separate the 640 px copy from the view-sized one"
    params = _stretch_params(base.data)

    def manual(img):
        small = _downscale(img, max_edge=edge)
        return _rgb_of(_pixmap_for(AstroImage(_stretched(small.data, params),
                                              is_linear=False, metadata={}),
                                   dlg.view.size()))

    assert np.array_equal(_rgb_of(dlg.view.pixmap()), manual(base))
    dlg.preview_btn.click()
    qtbot.waitUntil(lambda: dlg._result is not None, timeout=30000)
    dlg._render()
    assert np.array_equal(_rgb_of(dlg.view.pixmap()), manual(dlg._result))


def test_preview_jobs_are_single_flight(qtbot, monkeypatch):
    """Each edit with Preview on used to start another full-resolution job;
    now at most one runs and quick edits fold into one rerun."""
    import threading
    import time

    import nocturne.core.painted_background as pb
    real = pb.apply_painted
    lock = threading.Lock()
    state = {"running": 0, "peak": 0, "calls": 0, "last": None}

    def slow(img, strokes, amount):
        with lock:
            state["running"] += 1
            state["calls"] += 1
            state["peak"] = max(state["peak"], state["running"])
            state["last"] = strokes
        time.sleep(0.4)
        try:
            return real(img, strokes, amount)
        finally:
            with lock:
                state["running"] -= 1

    monkeypatch.setattr(pb, "apply_painted", slow)
    dlg = _open(qtbot)
    dlg.preview_btn.click()
    cx, cy = _centre(dlg)
    for i in range(4):
        _drag(dlg.view, [(cx - 50 + 20 * i, cy), (cx - 40 + 20 * i, cy)])
    qtbot.waitUntil(lambda: dlg._result is not None and not dlg._result_busy,
                    timeout=30000)
    assert state["peak"] == 1
    assert state["calls"] == 2          # the first, then one rerun for all four edits
    assert state["last"] == dlg.option()["strokes"]
    assert QApplication.overrideCursor() is None


def test_fit_mapping_anchors_with_letterbox(qtbot):
    dlg = _open(qtbot)
    view = dlg.view
    pm = view.pixmap()
    ox, oy = (view.width() - pm.width()) / 2, (view.height() - pm.height()) / 2
    assert ox > 1 or oy > 1, "no letterbox: offset untested"
    L, N = Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton
    h, w = dlg._base.data.shape[:2]
    for (px, py), want in (((ox + pm.width() / 2, oy + pm.height() / 2), (w / 2, h / 2)),
                           ((ox, oy), (0.0, 0.0))):
        dlg.clear_btn.click()
        _send(view, QEvent.Type.MouseButtonPress, (px, py), L, L)
        _send(view, QEvent.Type.MouseButtonRelease, (px, py), L, N)
        got = dlg.option()["strokes"][0]["points"][0]
        assert got == pytest.approx(list(want), abs=1.0)


def test_a_reused_id_never_shows_the_previous_result(qtbot, monkeypatch):
    """The decimation and pixmap caches are keyed on id(); a freed result's id
    can come back on the next one (6 in 200, measured). Force every id equal:
    the picture must still be the image actually shown."""
    from nocturne.ui import background_paint_dialog as bpd
    from nocturne.ui.background_paint_dialog import _stretch_params, _stretched
    from nocturne.ui.curves_dialog import _downscale, _pixmap_for
    base = _base()
    dlg = _open(qtbot, base=base)
    dlg.show_mask_check.setChecked(False)
    monkeypatch.setattr(bpd, "id", lambda o: 1, raising=False)
    dlg._render()
    edge = max(dlg.view.width(), dlg.view.height())
    params = _stretch_params(base.data)

    def manual(img):
        small = _downscale(img, max_edge=edge)
        return _rgb_of(_pixmap_for(AstroImage(_stretched(small.data, params),
                                              is_linear=False, metadata={}),
                                   dlg.view.size()))

    first = AstroImage(base.data * 0.5, is_linear=True, metadata={})
    second = AstroImage(base.data * 0.8, is_linear=True, metadata={})
    dlg.preview_btn.blockSignals(True)
    dlg.preview_btn.setChecked(True)
    dlg.preview_btn.blockSignals(False)
    for img in (first, second):
        dlg._result = img
        dlg._render()
        assert np.array_equal(_rgb_of(dlg.view.pixmap()), manual(img))


def test_apply_during_a_running_preview_waits_for_it(qtbot, monkeypatch):
    """Apply pressed while the preview is still fitting the same strokes takes
    that fit rather than cancelling it and starting another."""
    import time

    import nocturne.core.painted_background as pb
    real, calls = pb.apply_painted, []

    def slow(*a):
        calls.append(1)
        time.sleep(0.4)
        return real(*a)
    monkeypatch.setattr(pb, "apply_painted", slow)
    got = []
    dlg = _open(qtbot, on_apply=lambda o, r: got.append((o, r)))
    cx, cy = _centre(dlg)
    _drag(dlg.view, [(cx, cy), (cx + 25, cy + 5)])
    dlg.preview_btn.click()
    assert dlg._result_busy
    dlg.apply_btn.click()
    qtbot.waitUntil(lambda: bool(got), timeout=20000)
    assert len(calls) == 1
    assert got[0][1] is dlg._result
    assert QApplication.overrideCursor() is None


# --- brush ring + zoom pill (his first test, 2026-11-14) ----------------------

def _ring_pixels(dlg, cx, cy):
    """RGB of the view around the point one brush radius right of (cx, cy)."""
    img = dlg.view.grab().toImage()
    r = dlg.view.brush_px
    dpr = img.devicePixelRatio()
    out = []
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            c = img.pixelColor(int((cx + r + dx) * dpr), int((cy + dy) * dpr))
            out.append((c.red(), c.green(), c.blue()))
    return np.array(out, dtype=int)


def _hover(dlg, pos):
    _send(dlg.view, QEvent.Type.MouseMove, pos, Qt.MouseButton.NoButton,
          Qt.MouseButton.NoButton)


def test_hovering_draws_the_brush_ring_at_its_size_in_the_brush_colour(qtbot):
    dlg = _open(qtbot)
    cx, cy = _centre(dlg)
    dlg.size_slider.setValue(40)
    dlg.view._end_flash()
    before = _ring_pixels(dlg, cx, cy)
    _hover(dlg, (cx, cy))
    sky = _ring_pixels(dlg, cx, cy)
    assert not np.array_equal(before, sky), "no ring drawn under the pointer"
    assert (sky[:, 2] - sky[:, 0]).max() > 60          # blue ring for Sky
    dlg.nebula_btn.click()
    neb = _ring_pixels(dlg, cx, cy)
    assert (neb[:, 0] - neb[:, 2]).max() > 60          # orange ring for Nebula


def test_the_ring_goes_when_the_pointer_leaves(qtbot):
    dlg = _open(qtbot)
    cx, cy = _centre(dlg)
    dlg.view._end_flash()
    _hover(dlg, (cx, cy))
    assert dlg.view.ring_centre() is not None
    QApplication.sendEvent(dlg.view, QEvent(QEvent.Type.Leave))
    assert dlg.view.ring_centre() is None


def test_moving_the_size_slider_shows_the_ring_centred(qtbot):
    dlg = _open(qtbot)
    dlg.view._end_flash()
    assert dlg.view.ring_centre() is None              # pointer not over the view
    dlg.size_slider.setValue(60)
    c = dlg.view.ring_centre()
    assert c is not None and (c.x(), c.y()) == _centre(dlg)
    assert dlg.view.brush_px == 60


def test_space_pan_hides_the_ring(qtbot):
    dlg = _open(qtbot)
    cx, cy = _centre(dlg)
    dlg.view._end_flash()
    _hover(dlg, (cx, cy))
    QApplication.sendEvent(dlg.view, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Space,
                                               Qt.KeyboardModifier.NoModifier))
    assert dlg.view.ring_centre() is None


def test_zoom_pill_is_on_the_view_and_zooms_it(qtbot):
    dlg = _open(qtbot)
    pill = dlg.zoom_pill
    assert pill.parent() is dlg.view and pill.isVisible()
    fit_text = pill.level.text()
    z0 = dlg.view.zoom_level()
    pill.in_btn.click()
    assert dlg.view.zoom_level() > z0
    assert pill.level.text() != fit_text
    pill.fit_btn.click()
    assert dlg.view.zoom_level() == 1.0 and pill.level.text() == fit_text


def test_a_click_on_the_pill_label_paints_nothing(qtbot):
    dlg = _open(qtbot)
    before = list(dlg._strokes)
    lab = dlg.zoom_pill.level
    L, N = Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton
    c = (lab.width() / 2, lab.height() / 2)
    _send(lab, QEvent.Type.MouseButtonPress, c, L, L)
    _send(lab, QEvent.Type.MouseButtonRelease, c, L, N)
    assert dlg.view.live is None
    assert dlg._strokes == before


def test_the_ring_leaves_when_the_pointer_moves_onto_the_pill(qtbot):
    dlg = _open(qtbot)
    dlg.view._end_flash()
    _hover(dlg, _centre(dlg))
    assert dlg.view.ring_centre() is not None
    QApplication.sendEvent(dlg.zoom_pill, QEvent(QEvent.Type.Enter))
    assert dlg.view.ring_centre() is None


def _fill(btn):
    """The button's face colour, sampled left of its label."""
    img = btn.grab().toImage()
    return img.pixelColor(6, img.height() // 2).name()


def test_the_chosen_amount_brush_and_auto_mask_look_chosen(qtbot):
    """He could not tell which of Light/Strong was pressed: a checked plain
    QPushButton is unstyled app-wide, so it must render unlike its neighbour."""
    from nocturne.ui.theme import build_stylesheet
    dlg = _open(qtbot, option={"method": "painted", "amount": "strong"})
    dlg.setStyleSheet(build_stylesheet())
    assert dlg.strong_btn.isChecked() and dlg.sky_btn.isChecked()
    assert _fill(dlg.strong_btn) != _fill(dlg.light_btn)
    assert _fill(dlg.sky_btn) != _fill(dlg.nebula_btn)
    off = _fill(dlg.auto_btn)
    dlg.auto_btn.setChecked(True)
    assert _fill(dlg.auto_btn) != off
