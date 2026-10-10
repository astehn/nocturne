"""Shape buttons in each tool that uses them: the pixels each one produces have
the shape the button says, Portrait included."""
import datetime

import numpy as np
import pytest
from astropy.io import fits

pytest.importorskip("PySide6")
from PySide6.QtCore import QPointF  # noqa: E402

from nocturne.settings import Settings  # noqa: E402
from nocturne.ui.main_window import MainWindow  # noqa: E402


def _fits(tmp_path, h=60, w=100):
    arr = (np.random.default_rng(3).random((3, h, w)) * 1000 + 50).astype(np.uint16)
    p = tmp_path / "wide.fits"
    fits.PrimaryHDU(arr).writeto(str(p))
    return str(p)


def _crop_window(qtbot, tmp_path):
    win = MainWindow(settings_path=str(tmp_path / "settings.json"), check_updates=False,
                     telemetry=False)
    win._async_enabled = False
    qtbot.addWidget(win)
    win.open_fits(_fits(tmp_path))
    win._go_to_id("crop")
    return win


def _ratio(win):
    h, w = win.project.current().data.shape[:2]
    return w / h, (w, h)


def test_a_portrait_crop_is_tall_and_says_so_everywhere(qtbot, tmp_path):
    from nocturne.core import provenance
    win = _crop_window(qtbot, tmp_path)
    p = win._panel.shape_picker
    p.button("3:2").click()
    p.orientation.buttons()[1].click()                     # Portrait -> 2:3
    win.image_view.show_crop_box()                         # the first click
    assert win.image_view.crop_box_modified() is False, "no work to lose yet"
    win._apply_crop()
    r, (w, h) = _ratio(win)
    assert h > w and abs(r - 2 / 3) < 0.04, (w, h)

    name, option = win.project.entries()[-1]
    assert name == "Crop" and option.aspect == "2:3"
    report = provenance.build_report(win.project.entries(), {}, app_version="t",
                                     date=datetime.date(2026, 10, 10))
    assert "Crop — 2:3" in report and "aspect: 2:3" in report


def test_the_crop_log_line_names_the_shape(qtbot, tmp_path, monkeypatch):
    import nocturne.ui.main_window as mw
    lines = []
    real = mw.format_log_entry
    monkeypatch.setattr(mw, "format_log_entry",
                        lambda *a, **k: lines.append(real(*a, **k)) or lines[-1])
    win = _crop_window(qtbot, tmp_path)
    win._panel.shape_picker.button("Picture").click()
    win.image_view.show_crop_box()
    win.image_view._resize_to("br", QPointF(70, 50))      # smaller, still locked
    win._apply_crop()
    assert lines[-1] == "Crop (Original)", "the log must not say the internal 'Picture'"
    r, _ = _ratio(win)
    assert abs(r - 100 / 60) < 0.05


def test_free_drags_to_any_shape(qtbot, tmp_path):
    win = _crop_window(qtbot, tmp_path)
    assert win._panel.shape_picker.shape() == "Free"
    win.image_view.show_crop_box()
    assert win.image_view._aspect is None
    win.image_view._resize_to("br", QPointF(93, 17))
    win._apply_crop()
    assert win.project.current().data.shape[:2] == (17, 93)
    assert win.project.entries()[-1][1].aspect == "Free"


def test_choosing_a_shape_after_the_box_is_up_reshapes_it(qtbot, tmp_path):
    win = _crop_window(qtbot, tmp_path)
    win.image_view.show_crop_box()
    p = win._panel.shape_picker
    p.button("16:9").click()
    p.orientation.buttons()[1].click()
    t, b, l, r = win.image_view.crop_bounds()
    assert abs((r - l) / (b - t) - 9 / 16) < 0.05


# --- Share --------------------------------------------------------------------

def _share(qtbot):
    from nocturne.ui.share_dialog import ShareDialog
    rgb = np.full((300, 400, 3), 120, np.uint8)
    d = ShareDialog(rgb, {"target": "M 31", "source_label": "m31.fits"}, Settings(handle="me"))
    qtbot.addWidget(d)
    return d


def test_share_portrait_frames_a_tall_picture_and_names_the_file(qtbot):
    d = _share(qtbot)
    assert "Free" not in d.shape_picker.labels()
    d.shape_picker.button("16:9").click()
    d.shape_picker.orientation.buttons()[1].click()
    t, b, l, r = d._current_crop()
    assert abs((r - l) / (b - t) - 9 / 16) < 0.03
    out = d._compose_current()
    assert out.height() > out.width()
    from nocturne.core.share import share_filename
    assert share_filename("m31.fits", d._aspect_label) == "m31_9x16.jpg"


def test_share_original_is_still_the_whole_picture(qtbot):
    d = _share(qtbot)
    d.shape_picker.button("1:1").click()
    d.shape_picker.button("Picture").click()
    assert d._current_crop() == (0, 300, 0, 400)
    assert d._aspect_label == "Original"


# --- Upscale Crop -------------------------------------------------------------

def _upscale(qtbot, h=60, w=90):
    from nocturne.core.image import AstroImage
    from nocturne.ui.upscale_dialog import UpscaleDialog
    data = np.full((h, w, 3), 0.1, np.float32)
    data[30, 30] = 1.0
    meta = {"target": "M42", "source_label": "m42.fits"}
    d = UpscaleDialog(AstroImage(data, is_linear=False, metadata=meta), meta, Settings())
    qtbot.addWidget(d)
    return d


def test_upscale_opens_free_as_before_and_its_original_is_locked(qtbot):
    """Upscale's box was always free to drag (its old "Original"); it keeps Free
    and opens on it. The new Original locks to the picture's proportions."""
    d = _upscale(qtbot)
    assert d.shape_picker.labels() == ["Free", "Original", "1:1", "5:4", "4:3", "3:2", "16:9"]
    assert d.shape_picker.ratio() is None
    from nocturne.ui.shape_picker import PICTURE
    d.shape_picker.button(PICTURE).click()
    d.picker.show_crop_box()
    assert d.picker._aspect == pytest.approx(90 / 60)
    d.picker._resize_to("br", QPointF(50, 50))
    t, b, l, r = d.picker.crop_bounds()
    assert abs((r - l) / (b - t) - 1.5) < 0.05


def test_upscale_portrait_crop_enlarges_a_tall_region(qtbot):
    d = _upscale(qtbot)
    d.shape_picker.button("3:2").click()
    d.shape_picker.orientation.buttons()[1].click()
    t, b, l, r = d.picker.crop_bounds()
    d._run_upscale()
    rh, rw = d._result.data.shape[:2]
    assert (rh, rw) == (2 * (b - t), 2 * (r - l))
    assert abs(rw / rh - 2 / 3) < 0.05


def test_the_crop_panel_does_not_widen_the_right_column_at_1280x800(qtbot, tmp_path):
    """Four shape buttons across, under the real stylesheet, at the smallest
    window the app supports: the column keeps the width Stretch gives it and
    nothing in the Crop panel is cut off."""
    from PySide6.QtWidgets import QApplication
    from nocturne.ui.theme import build_stylesheet
    app = QApplication.instance()
    before = app.styleSheet()
    app.setStyleSheet(build_stylesheet())
    try:
        win = MainWindow(settings_path=str(tmp_path / "settings.json"), check_updates=False,
                         telemetry=False)
        win._async_enabled = False
        qtbot.addWidget(win)
        win.open_fits(_fits(tmp_path))
        win.resize(1280, 800); win.show(); qtbot.waitExposed(win)
        win._go_to_id("stretch", user_initiated=False); qtbot.wait(30)
        side_w = win._side.width()
        win._go_to_id("crop", user_initiated=False); qtbot.wait(50)
        assert win._side.width() == side_w, "the Crop panel widened the right column"
        p = win._panel.shape_picker
        for b in p.buttons() + p.orientation.buttons() + win._panel.guides_box.buttons() + [
                win._panel.rotate_btn, win._panel.flip_h_btn, win._panel.flip_v_btn]:
            assert b.width() >= b.minimumSizeHint().width(), b.text()
            assert b.mapTo(win._side, b.rect().topRight()).x() <= win._side.width(), b.text()
        assert p.buttons()[0].width() >= 52, "a shape button too narrow for its label"
    finally:
        app.setStyleSheet(before)
