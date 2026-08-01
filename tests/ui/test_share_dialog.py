import numpy as np
import pytest

pytest.importorskip("PySide6")
from nocturne.ui.share_dialog import ShareDialog
from nocturne.settings import Settings


def _rgb(h=400, w=300):
    a = np.zeros((h, w, 3), np.uint8); a[:] = 180
    return a

def _dlg(qtbot, meta=None):
    d = ShareDialog(_rgb(), meta or {"target": "NGC 7000", "source_label": "ngc7000.fits"},
                    Settings(handle="me"))
    qtbot.addWidget(d)
    return d

def test_dialog_builds_with_preview(qtbot):
    d = _dlg(qtbot)
    assert d._compose_current().width() > 0

def test_selecting_aspect_locks_ratio(qtbot):
    d = _dlg(qtbot)
    d._select_aspect(1.0, "1:1")
    out = d._compose_current()
    assert abs(out.width() - out.height()) <= 2      # square

def test_original_after_ratio_restores_full_frame(qtbot):
    d = _dlg(qtbot)
    d._select_aspect(1.0, "1:1")               # lock to a square box
    d._select_aspect(None, "Original")         # go back to Original
    assert d._current_crop() == (0, 400, 0, 300)   # full frame (h=400,w=300), not the 1:1 box


def test_caption_toggle_controls_band(qtbot):
    d = _dlg(qtbot)
    d._set_caption(False)
    assert d._current_caption() == ""
    d._set_caption(True)
    assert "NGC 7000" in d._current_caption()

def test_export_uses_injected_saver(qtbot, tmp_path):
    d = _dlg(qtbot)
    saved = {}
    d._save_runner = lambda img, path: saved.update(w=img.width(), path=path)
    d._do_export(str(tmp_path / "out.jpg"))          # bypass the file dialog
    assert saved["w"] > 0 and saved["path"].endswith("out.jpg")

def test_copy_uses_injected_clipboard(qtbot):
    d = _dlg(qtbot)
    grabbed = {}
    d._clipboard_runner = lambda img: grabbed.update(w=img.width())
    d._do_copy()
    assert grabbed["w"] > 0


def test_close_button_rejects(qtbot):
    from PySide6.QtWidgets import QDialog
    d = _dlg(qtbot)
    d._close_btn.click()
    assert d.result() == QDialog.DialogCode.Rejected


def test_the_selected_aspect_is_visible(qtbot):
    """Six plain push-buttons showed no state at all: after clicking around, the
    only way to know what you would get was to read the preview's shape."""
    dlg = _dlg(qtbot)
    checked = [lbl for lbl, b in dlg._aspect_buttons.items() if b.isChecked()]
    assert checked == ["Original"], "the starting aspect must be shown as active"

    dlg._aspect_buttons["4:5"].click()
    checked = [lbl for lbl, b in dlg._aspect_buttons.items() if b.isChecked()]
    assert checked == ["4:5"], "exactly one aspect is active at a time"
    assert dlg._aspect_label == "4:5"


def test_selecting_an_aspect_in_code_updates_the_buttons(qtbot):
    """The row must not go stale when the aspect is set other than by a click."""
    dlg = _dlg(qtbot)
    dlg._select_aspect(1.0, "1:1")
    assert dlg._aspect_buttons["1:1"].isChecked()
    assert not dlg._aspect_buttons["Original"].isChecked()


def test_size_choice_changes_the_composed_output(qtbot):
    """2048 was hardcoded. A tool whose whole purpose is producing a file for
    somewhere else must let you say how big it is."""
    dlg = _dlg(qtbot, meta={"target": "X", "source_label": "x.fits"})
    dlg._size = 1080
    small = dlg._compose_current()
    dlg._size = None                       # "Full size"
    full = dlg._compose_current()
    assert max(small.width(), small.height()) <= 1080
    assert max(full.width(), full.height()) >= max(small.width(), small.height())


def test_share_is_never_upscaled(qtbot):
    """A 400x300 source asked for 4096 must stay 400x300 — adding pixels without
    adding detail is not a service."""
    dlg = _dlg(qtbot)
    dlg._size = 4096
    img = dlg._compose_current()
    assert max(img.width(), img.height()) == 400


def test_format_choice_drives_the_filename_and_writer(qtbot):
    from nocturne.core.share import share_filename
    dlg = _dlg(qtbot)
    assert share_filename("ngc7000.fits", "4:5", "png") == "ngc7000_4x5.png"
    assert share_filename("ngc7000.fits", "4:5", "jpg") == "ngc7000_4x5.jpg"

    written = {}
    dlg._save_runner = lambda img, path: written.setdefault("path", path)
    dlg._do_export("/tmp/out.png")
    assert written["path"].endswith(".png")


def test_export_reports_the_pixel_size(qtbot):
    """"Saved name.jpg" never answered the question you actually have before
    posting: how big is it?"""
    dlg = _dlg(qtbot)
    dlg._save_runner = lambda img, path: None
    dlg._do_export("/tmp/out.jpg")
    assert "×" in dlg.status.text() and "400" in dlg.status.text()


def test_caption_is_free_text_prefilled_from_the_image(qtbot):
    """Free text rather than a checkbox per field: deleting a field is deleting
    words, and you also get "first light with the S30", which no set of toggles
    can express."""
    dlg = _dlg(qtbot)
    assert "NGC 7000" in dlg._caption_edit.text(), "prefilled from the metadata"

    dlg._caption_edit.setText("first light with the S30")
    assert dlg._current_caption() == "first light with the S30"

    dlg._reset_caption()
    assert "NGC 7000" in dlg._caption_edit.text(), "reset restores the generated line"


def test_caption_style_is_persisted_but_the_text_is_not(qtbot):
    """Style is a house style; the text belongs to this one image."""
    saved = {}
    from nocturne.settings import Settings
    from nocturne.ui.share_dialog import ShareDialog
    dlg = ShareDialog(_rgb(), {"target": "NGC 7000"}, Settings(handle="me"),
                      settings_saver=lambda s: saved.update(
                          size=s.share_caption_size, colour=s.share_caption_colour,
                          placement=s.share_caption_placement))
    qtbot.addWidget(dlg)

    dlg._caption_edit.setText("do not save me")
    dlg._place_box.setCurrentIndex(1)          # "Below image"
    assert saved["placement"] == "below"
    assert "text" not in saved and "caption" not in saved


def test_caption_controls_disable_with_the_caption_checkbox(qtbot):
    dlg = _dlg(qtbot)
    assert dlg._caption_wrap.isEnabled()
    dlg._caption_check.setChecked(False)
    assert not dlg._caption_wrap.isEnabled(), "no point styling a caption that is off"
    assert dlg._current_caption() == ""


def test_a_saved_style_is_restored_next_time(qtbot):
    from nocturne.settings import Settings
    from nocturne.ui.share_dialog import ShareDialog
    s = Settings(handle="me", share_caption_placement="below",
                 share_caption_colour="#ff8800", share_caption_size=0.038)
    dlg = ShareDialog(_rgb(), {"target": "X"}, s)
    qtbot.addWidget(dlg)
    assert dlg._cap_placement == "below"
    assert dlg._cap_colour == "#ff8800"
    assert dlg._place_box.currentData() == "below"
    assert dlg._cap_size_box.currentData() == pytest.approx(0.038)
