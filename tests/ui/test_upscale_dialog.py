import numpy as np
import pytest

pytest.importorskip("PySide6")
from nocturne.ui.upscale_dialog import UpscaleDialog
from nocturne.settings import Settings


def _img(h=60, w=60):
    d = np.full((h, w, 3), 0.1, np.float32); d[30, 30] = 1.0
    from nocturne.core.image import AstroImage
    return AstroImage(d, is_linear=False, metadata={"target": "M42", "source_label": "m42.fits"})


def _dlg(qtbot, **kw):
    d = UpscaleDialog(_img(), {"target": "M42", "source_label": "m42.fits"}, Settings(), **kw)
    qtbot.addWidget(d)
    return d


def test_dialog_builds(qtbot):
    d = _dlg(qtbot)
    assert d.windowTitle() == "Upscale Crop"
    assert d.pages.currentIndex() == 0
    assert not hasattr(d, "_engine_box") and not hasattr(d, "_compare_check")
    assert d._engine.name == "Lanczos"


def test_run_upscale_produces_2x_result(qtbot):
    d = _dlg(qtbot)
    d._run_upscale()                       # full-frame (no crop box shown)
    assert d._result is not None
    assert d._result.data.shape == (120, 120, 3)


def test_export_uses_injected_saver_and_writes_report(qtbot, tmp_path):
    d = _dlg(qtbot)
    d._run_upscale()
    saved = {}
    d._save_runner = lambda img, path: saved.update(path=path, shape=img.data.shape)
    d._do_export(str(tmp_path / "out.jpg"))
    assert saved["shape"] == (120, 120, 3)
    assert (tmp_path / "out.txt").exists()          # provenance report written
    assert "Lanczos" in (tmp_path / "out.txt").read_text()


def test_open_as_copy_calls_callback(qtbot):
    got = {}
    d = _dlg(qtbot, on_open_copy=lambda img: got.update(shape=img.data.shape))
    d._run_upscale()
    d._do_open_copy()
    assert got["shape"] == (120, 120, 3)


def test_open_as_copy_closes_the_dialog(qtbot):
    from PySide6.QtWidgets import QDialog
    opened = {}
    d = _dlg(qtbot, on_open_copy=lambda img: opened.update(ok=True))
    d._run_upscale()
    d._do_open_copy()
    assert opened.get("ok") is True
    assert d.result() == QDialog.DialogCode.Accepted   # dialog closed -> main window (with the copy) is revealed


def test_a_declined_open_leaves_the_dialog_up(qtbot):
    """The main window returns False when the user cancels its "save your
    unsaved edits first?" prompt. Closing anyway would look like the copy had
    opened, over a main window still showing the old project."""
    from PySide6.QtWidgets import QDialog
    asked = []
    d = _dlg(qtbot, on_open_copy=lambda img: asked.append(True) or False)
    d._run_upscale()
    assert d._open_copy_btn.isEnabled()          # reachable at all, once there is a result
    d._open_copy_btn.click()                     # through the real wiring, not the handler
    assert asked == [True]                              # it did try
    assert d.result() != QDialog.DialogCode.Accepted    # and did not close on the refusal


def test_close_button_rejects(qtbot):
    from PySide6.QtWidgets import QDialog
    d = _dlg(qtbot)
    d._close_btn.click()
    assert d.result() == QDialog.DialogCode.Rejected


def test_the_size_follows_the_crop_box(qtbot):
    d = _dlg(qtbot)                                     # 60x60 image
    assert d.size_label.text() == "60 × 60 → 120 × 120"  # no box = whole frame
    d.picker.set_crop_overlay(True, content_bounds=(10, 40, 5, 25))
    d.picker.show_crop_box()
    d._sync_size()
    assert d.size_label.text() == "20 × 30 → 40 × 60"


def test_above_the_limit_upscale_is_refused_with_the_reason_beside_it(qtbot):
    """The reason sits beside the button it disables, in the panel — in the
    status line at the foot he did not see it (2026-09-29)."""
    d = _dlg(qtbot)                                     # 60x60 -> 0.0144 MP out
    d._limit_mp = 0.01
    d._sync_size()
    assert not d.upscale_btn.isEnabled()
    assert not d.limit_note.isHidden()
    assert d.limit_note.text() == "Too large to enlarge on this computer: 0 MP. Make the crop smaller."
    assert "Too large" not in d.status.text()
    d._limit_mp = 60
    d._sync_size()
    assert d.upscale_btn.isEnabled() and d.limit_note.isHidden()


def test_the_panel_says_this_computers_limit_and_why(qtbot, monkeypatch):
    import nocturne.ui.upscale_dialog as ud
    monkeypatch.setattr(ud, "upscale_limit_mp", lambda: 42)
    monkeypatch.setattr(ud, "memory_gb", lambda: 16)
    d = _dlg(qtbot)
    assert d.limit_label.text() == "Up to 42 MP on this computer (16 GB of memory)"


def test_the_noise_note_shows_only_without_noise_reduction(qtbot):
    msg = ("Noise Reduction hasn't been applied — enlarging makes noise twice as "
           "visible. Worth running it first.")
    d = _dlg(qtbot, denoised=False)
    assert not d.noise_note.isHidden() and d.noise_note.text() == msg
    assert _dlg(qtbot, denoised=True).noise_note.isHidden()


def test_a_shape_constrains_the_crop_box(qtbot):
    d = _dlg(qtbot)
    d.shape_buttons["1:1"].click()
    d.picker.show_crop_box()
    t, b, l, r = d.picker.crop_bounds()
    assert (b - t) == pytest.approx(r - l, abs=1)


def test_a_tiny_crop_does_not_break_the_panel(qtbot):
    d = _dlg(qtbot)
    d.picker.set_crop_overlay(True, content_bounds=(10, 11, 10, 13))   # 3x1
    d.picker.show_crop_box()
    d._sync_size()
    assert d.size_label.text() == "3 × 1 → 6 × 2"


def test_upscale_shows_a_linked_pair_at_100_percent(qtbot):
    d = _dlg(qtbot)
    d.resize(900, 600); d.show()
    d._run_upscale()
    assert d.pages.currentIndex() == 1
    assert d.original_view.zoom() == pytest.approx(1.0) and d.result_view.zoom() == pytest.approx(1.0)
    d.result_view.zoom_in()
    assert d.original_view.zoom() == pytest.approx(d.result_view.zoom())


def test_wipe_keeps_the_zoom_and_back(qtbot):
    d = _dlg(qtbot); d.resize(900, 600); d.show()
    d._run_upscale()
    d.result_view.zoom_in()
    z = d.result_view.zoom()
    d.mode_wipe.click()
    assert d.wipe_view.zoom() == pytest.approx(z) and d.wipe_view.compare_active()
    d.wipe_view.zoom_in()
    d.mode_side.click()
    assert d.result_view.zoom() == pytest.approx(d.wipe_view.zoom())


def test_change_crop_goes_back_and_a_new_upscale_relinks_once(qtbot):
    """[RF 4]"""
    d = _dlg(qtbot); d.resize(900, 600); d.show()
    d._run_upscale()
    d.change_crop_btn.click()
    assert d.pages.currentIndex() == 0 and d._result is None and d._layers is None
    d._run_upscale()
    for _ in range(8):
        d.result_view.zoom_in()             # a 120 px result has no scroll range at 100%
    bar = d.result_view.horizontalScrollBar()
    assert bar.maximum() > bar.value() + 5
    moves = []
    d.original_view.viewChanged.connect(lambda: moves.append(1))
    bar.setValue(bar.value() + 5)
    assert 1 <= len(moves) <= 2             # followed, and by ONE link not two


def test_cancel_returns_to_the_picker_untouched(qtbot, monkeypatch):
    """[RF 2]"""
    import threading
    import nocturne.ui.upscale_dialog as ud
    from nocturne.core.tasks import current
    started = threading.Event()

    def slow(*a, **k):
        started.set()
        while True:
            current().check()
    monkeypatch.setattr(ud, "prepare_upscale", slow)
    d = _dlg(qtbot); d.show()
    d.picker.set_crop_overlay(True, content_bounds=(10, 40, 5, 25)); d.picker.show_crop_box()
    crop = d.picker.crop_bounds()
    d.upscale_btn.click()
    assert started.wait(5) and d.cancel_btn.isVisible()
    d.cancel_btn.click()
    qtbot.waitUntil(lambda: not d._busy, timeout=5000)
    assert d.pages.currentIndex() == 0 and d._result is None
    assert d.picker.crop_bounds() == crop and d.upscale_btn.isEnabled()
    assert d.status.text() == "Cancelled."


def test_the_navigator_moves_both_views(qtbot):
    d = _dlg(qtbot); d.resize(900, 600); d.show()
    d._run_upscale()
    d.navigator.centreRequested.emit(10.0, 10.0)
    c1 = d.result_view.mapToScene(d.result_view.viewport().rect().center())
    c2 = d.original_view.mapToScene(d.original_view.viewport().rect().center())
    assert c1.x() == pytest.approx(c2.x(), abs=1) and c1.y() == pytest.approx(c2.y(), abs=1)


def test_a_second_upscale_in_wipe_opens_at_100_percent(qtbot):
    d = _dlg(qtbot); d.resize(900, 600); d.show()
    d._run_upscale()
    d.mode_wipe.click()
    d.wipe_view.zoom_in()
    d.change_crop_btn.click()
    d._run_upscale()
    assert d.wipe_view.zoom() == pytest.approx(1.0)
    assert d.result_view.zoom() == pytest.approx(1.0)


def test_the_slider_changes_the_nocturne_view_only(qtbot):
    d = _dlg(qtbot); d.show()
    d._run_upscale()
    plain_before = d.original_view._item.pixmap().toImage()
    d.tighten_slider.setValue(100)
    qtbot.waitUntil(lambda: d._result.metadata["upscale"]["tighten"] == 1.0, timeout=5000)
    assert d.original_view._item.pixmap().toImage() == plain_before


def test_export_uses_the_slider_value_even_before_the_view_catches_up(qtbot, tmp_path):
    """[RF 3] WYSIWYG: the file carries the slider's current value."""
    d = _dlg(qtbot); d.show()
    d._run_upscale()
    d.tighten_slider.setValue(90)                   # debounce has NOT fired yet
    saved = {}
    d._save_runner = lambda img, path: saved.update(t=img.metadata["upscale"]["tighten"])
    d._do_export(str(tmp_path / "o.jpg"))
    assert saved["t"] == 0.9


def test_open_as_copy_uses_the_slider_value(qtbot):
    got = {}
    d = _dlg(qtbot, on_open_copy=lambda img: got.update(t=img.metadata["upscale"]["tighten"]))
    d._run_upscale()
    d.tighten_slider.setValue(10)
    d._do_open_copy()
    assert got["t"] == 0.1


# --- final whole-branch review fixes (2026-09-29) ---

def _no_image(view) -> bool:
    return view._item.pixmap().isNull() and not view.compare_active()


def _centre(view):
    from PySide6.QtCore import QRectF
    c = view.mapToScene(QRectF(view.viewport().rect()).center().toPoint())
    return c.x(), c.y()


def test_cancel_with_a_splitter_that_never_checks_shows_no_result(qtbot, monkeypatch):
    """[final 1] The free splitter and the Lanczos steps never look at the
    token, so the work finishes after Cancel; that result must not be shown."""
    import threading
    import nocturne.ui.upscale_dialog as ud
    from nocturne.core.upscale import LanczosEngine, prepare_upscale as real_prepare
    started, release = threading.Event(), threading.Event()
    # Built here, not in the worker: the real prepare now checks the token itself,
    # and this must prove the dialog drops a result that arrives after Cancel.
    ready = real_prepare(_img(), None, LanczosEngine())

    def deaf(img, crop, engine, **k):
        started.set()
        release.wait(5)                        # never checks the token
        return ready
    monkeypatch.setattr(ud, "prepare_upscale", deaf)
    d = _dlg(qtbot); d.show()
    d.upscale_btn.click()
    assert started.wait(5)
    d.cancel_btn.click()
    release.set()
    qtbot.waitUntil(lambda: not d._busy, timeout=5000)
    assert d.pages.currentIndex() == 0
    assert d.status.text() == "Cancelled."
    assert d._result is None and d._layers is None
    assert all(_no_image(v) for v in (d.original_view, d.result_view, d.wipe_view))


def test_closing_releases_the_layers_result_and_views(qtbot):
    """[final 2] exec() never deleted the dialog, and it held ~1.3 GB at 20 MP."""
    d = _dlg(qtbot); d.resize(900, 600); d.show()
    d._run_upscale()
    assert not d.result_view._item.pixmap().isNull()       # precondition: there was a result
    d._close_btn.click()
    assert d._layers is None and d._result is None
    assert all(_no_image(v) for v in (d.original_view, d.result_view, d.wipe_view))
    assert d.navigator._frame.isNull()


def test_a_late_worker_callback_after_close_builds_nothing(qtbot, monkeypatch):
    """[final 2] The worker's signals outlive the dialog: its done/failed must
    be inert once the dialog is closed, and after deleteLater has run."""
    import nocturne.ui.upscale_dialog as ud
    from PySide6.QtCore import QCoreApplication, QEvent
    from nocturne.core.tasks import Cancelled
    from nocturne.core.upscale import LanczosEngine, finish_upscale, prepare_upscale
    calls = []
    monkeypatch.setattr(ud, "run_async", lambda pool, fn, done, failed=None, **k:
                        calls.append((done, failed)))
    d = UpscaleDialog(_img(), {}, Settings())
    d.show()
    d.upscale_btn.click()
    d._layers = prepare_upscale(_img(), None, LanczosEngine())    # as if a result were up
    d._rerender()
    (up_done, up_failed), (re_done, _re_failed) = calls
    d.reject()
    layers = prepare_upscale(_img(), None, LanczosEngine())
    up_done(layers)
    re_done(finish_upscale(layers, 0.35))
    up_failed(RuntimeError("late"))
    assert d.pages.currentIndex() == 0 and d._result is None and d._layers is None
    assert all(_no_image(v) for v in (d.original_view, d.result_view, d.wipe_view))
    d.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    up_done(layers)                                  # C++ side gone: must not raise
    re_done(finish_upscale(layers, 0.35))
    up_failed(Cancelled())


def test_closing_mid_run_cancels_the_work(qtbot, monkeypatch):
    """[final 3] Closing left StarNet2 running and built state 2 on a hidden dialog."""
    import threading
    import time
    import nocturne.ui.upscale_dialog as ud
    from nocturne.core.tasks import Cancelled, current
    started, stopped = threading.Event(), threading.Event()

    def slow(*a, **k):
        started.set()
        deadline = time.monotonic() + 8          # a failure must fail, not hang the run
        try:
            while time.monotonic() < deadline:
                current().check()
                time.sleep(0.001)
        except Cancelled:
            stopped.set()
            raise
        raise RuntimeError("never cancelled")
    monkeypatch.setattr(ud, "prepare_upscale", slow)
    d = _dlg(qtbot); d.show()
    d.upscale_btn.click()
    assert started.wait(5)
    d.reject()
    assert stopped.wait(5)                           # the work heard the cancel
    qtbot.wait(50)                                   # let the error signal land
    assert d.pages.currentIndex() == 0 and d._result is None
    assert _no_image(d.result_view)


def test_a_shape_picked_before_the_box_shows_the_box_in_that_shape(qtbot):
    """[final 4] 100x60: a square box is NOT the default whole-frame box."""
    d = UpscaleDialog(_img(h=60, w=100), {}, Settings()); qtbot.addWidget(d)
    assert not d.picker.crop_box_visible()
    d.shape_buttons["1:1"].click()
    assert d.picker.crop_box_visible()
    t, b, l, r = d.picker.crop_bounds()
    assert (b - t) == pytest.approx(r - l, abs=1) and (r - l) < 100
    assert d.size_label.text() == f"{r - l} × {b - t} → {2 * (r - l)} × {2 * (b - t)}"


def test_a_box_shown_by_a_click_updates_the_size(qtbot):
    """[final 4] cropBoxShown feeds the size label."""
    d = UpscaleDialog(_img(h=60, w=100), {}, Settings()); qtbot.addWidget(d)
    d.picker.set_crop_overlay(True, content_bounds=(10, 40, 5, 25))
    d.size_label.setText("stale")
    d.picker.show_crop_box()
    assert d.size_label.text() == "20 × 30 → 40 × 60"


def test_switching_to_wipe_keeps_the_same_place_and_back(qtbot):
    """[final 5] Scroll values copied between viewports of different widths
    moved the picture; the centre must survive both ways."""
    d = UpscaleDialog(_img(h=500, w=600), {}, Settings()); qtbot.addWidget(d)
    d.resize(900, 600); d.show()
    d._run_upscale()
    x, y = 520.0, 430.0
    d._centre_views(x, y)
    assert _centre(d.result_view) == pytest.approx((x, y), abs=1)    # precondition
    d.mode_wipe.click()
    assert d.wipe_view.viewport().width() > d.result_view.viewport().width() + 100
    assert _centre(d.wipe_view) == pytest.approx((x, y), abs=1)
    d.mode_side.click()
    assert _centre(d.result_view) == pytest.approx((x, y), abs=1)


def test_every_shape_button_is_wide_enough_to_read(qtbot):
    """[final 6] Six buttons in one row of a 240 px panel were squeezed."""
    d = _dlg(qtbot); d.resize(900, 600); d.show()
    for label, b in d.shape_buttons.items():
        assert b.width() >= b.sizeHint().width(), label


def test_a_failed_rerender_says_so_and_keeps_the_view(qtbot, monkeypatch):
    """[final 7]"""
    import nocturne.ui.upscale_dialog as ud
    d = _dlg(qtbot); d.show()
    d._run_upscale()
    before = d.result_view._item.pixmap().toImage()

    def boom(*a, **k):
        raise MemoryError("out of memory")
    monkeypatch.setattr(ud, "finish_upscale", boom)
    d._rerender()
    qtbot.waitUntil(lambda: d.status.text().startswith("Couldn't update"), timeout=5000)
    assert d.status.text() == "Couldn't update the preview: out of memory"
    assert d.result_view._item.pixmap().toImage() == before


def test_the_navigator_gets_a_small_copy_and_the_full_geometry(qtbot, monkeypatch):
    """[final 8] It held a full-resolution pixmap, and the frame was converted twice."""
    import nocturne.ui.upscale_dialog as ud
    n = []
    real = ud._qimage_from_float
    monkeypatch.setattr(ud, "_qimage_from_float", lambda a: n.append(1) or real(a))
    d = UpscaleDialog(_img(h=700, w=1400), {}, Settings()); qtbot.addWidget(d)
    assert len(n) == 1
    fr = d.navigator._frame
    assert max(fr.width(), fr.height()) <= 600 and fr.width() == 2 * fr.height()
    assert (d.navigator._fw, d.navigator._fh) == (1400, 700)


def test_change_crop_lets_go_of_the_pictures(qtbot):
    """[final 10] ~320 MB at 20 MP stayed in the hidden views."""
    d = _dlg(qtbot); d.resize(900, 600); d.show()
    d._run_upscale()
    assert not d.original_view._item.pixmap().isNull()      # precondition
    d.change_crop_btn.click()
    assert all(_no_image(v) for v in (d.original_view, d.result_view, d.wipe_view))


def test_the_left_view_is_the_original_pixel_for_pixel(qtbot):
    """His question: does upscaling degrade the picture? So the left side is the
    ORIGINAL crop, each pixel a 2x2 block — not another resize (2026-09-29)."""
    from nocturne.core.image import AstroImage
    d0 = np.zeros((20, 20, 3), np.float32)
    d0[5, 7] = (1.0, 0.0, 0.0)                         # one red pixel
    img = AstroImage(d0, is_linear=False, metadata={})
    d = UpscaleDialog(img, {}, Settings())
    qtbot.addWidget(d)
    d._run_upscale()
    q = d.original_view._item.pixmap().toImage()
    assert (q.width(), q.height()) == (40, 40)
    for x, y in ((14, 10), (15, 10), (14, 11), (15, 11)):   # the 2x2 block
        c = q.pixelColor(x, y)
        assert (c.red(), c.green(), c.blue()) == (255, 0, 0), (x, y)
    assert q.pixelColor(16, 10).red() == 0, "no smoothing bleeds into its neighbour"
    assert d.wipe_view.compare_active()


def test_the_navigator_fills_the_panel(qtbot):
    """His note: 'very very small even though there is plenty of room'."""
    d = _dlg(qtbot); d.resize(1000, 700); d.show()
    d._run_upscale()
    qtbot.wait(20)
    nav = d.navigator
    assert nav.width() >= 240
    assert nav.height() >= 0.8 * nav.heightForWidth(nav.width())   # square frame -> square map
    assert nav.height() >= 200


def test_the_original_is_the_same_crop_the_upscale_used(qtbot):
    """A wrong crop slice would still fill the view at the right size (it is
    scaled to fit), so the linked views would show different stars. Non-square
    frame, odd-sized crop at an offset, a marker inside it (review 2026-09-29)."""
    from nocturne.core.image import AstroImage
    d0 = np.zeros((40, 60, 3), np.float32)
    d0[13, 22] = (0.0, 1.0, 0.0)                        # green marker, frame coords
    img = AstroImage(d0, is_linear=False, metadata={})
    d = UpscaleDialog(img, {}, Settings())
    qtbot.addWidget(d)
    d.picker.set_crop_overlay(True, content_bounds=(10, 27, 20, 31))   # 11 wide x 17 tall
    d.picker.show_crop_box()
    d._run_upscale()
    assert d._layers.crop == (10, 27, 20, 31)
    q = d.original_view._item.pixmap().toImage()
    assert (q.width(), q.height()) == (22, 34)
    c = q.pixelColor((22 - 20) * 2, (13 - 10) * 2)      # the marker, at 2x, inside the crop
    assert (c.red(), c.green(), c.blue()) == (0, 255, 0)
    assert q.pixelColor(0, 0).green() == 0
