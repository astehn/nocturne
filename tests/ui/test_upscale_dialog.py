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


def test_above_the_ceiling_upscale_is_refused_with_a_reason(qtbot, monkeypatch):
    import nocturne.ui.upscale_dialog as ud
    monkeypatch.setattr(ud, "UPSCALE_MAX_MP", 0.01)     # 0.0144 MP > 0.01
    d = _dlg(qtbot)
    d._sync_size()
    assert not d.upscale_btn.isEnabled()
    assert "Too large to enlarge: 0 MP (limit 0.01 MP). Choose a smaller crop." in d.status.text()
    monkeypatch.setattr(ud, "UPSCALE_MAX_MP", 60)
    d._sync_size()
    assert d.upscale_btn.isEnabled() and "Too large" not in d.status.text()


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
