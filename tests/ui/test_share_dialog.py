import numpy as np
import pytest

pytest.importorskip("PySide6")
from nocturne.ui.share_dialog import ShareDialog
from nocturne.core.plate import PlateText
from nocturne.settings import Settings


def _rgb(h=400, w=300):
    a = np.zeros((h, w, 3), np.uint8); a[:] = 180
    return a

def _dlg(qtbot, meta=None, **kw):
    d = ShareDialog(_rgb(), meta or {"target": "NGC 7000", "source_label": "ngc7000.fits"},
                    Settings(handle="me"), **kw)
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


def test_the_plate_toggle_controls_what_is_drawn(qtbot):
    """Was test_caption_toggle_controls_band, against _current_caption(). The
    caption is now a three-slot PlateText, so the same question is asked of
    _plate(): off means nothing is drawn at all, not an empty band."""
    d = _dlg(qtbot)
    d._set_caption(False)
    assert d._plate() == PlateText("", "", "")
    d._set_caption(True)
    assert d._plate().designation == "NGC 7000"

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


def test_the_slots_are_free_text_prefilled_from_the_image(qtbot):
    """Was test_caption_is_free_text_prefilled_from_the_image, against the single
    _caption_edit. Free text rather than a checkbox per field: deleting a field
    is deleting words, and you also get "first light with the S30", which no set
    of toggles can express."""
    dlg = _dlg(qtbot)
    assert dlg._designation_edit.text() == "NGC 7000", "prefilled from the metadata"

    dlg._common_edit.setText("first light with the S30")
    assert dlg._plate().common == "first light with the S30"

    dlg._designation_edit.setText("")
    dlg._reset_slots()
    assert dlg._designation_edit.text() == "NGC 7000", "reset restores what the image says"


def test_the_look_is_persisted_but_the_text_is_not(qtbot):
    """Was test_caption_style_is_persisted_but_the_text_is_not, against the
    share_caption_* keys. Style is a house style; the text belongs to this one
    image."""
    saved = {}
    from nocturne.settings import Settings
    from nocturne.ui.share_dialog import ShareDialog
    dlg = ShareDialog(_rgb(), {"target": "NGC 7000"}, Settings(handle="me"),
                      settings_saver=lambda s: saved.update(
                          preset=s.plate_preset, style=dict(s.plate_style)))
    qtbot.addWidget(dlg)

    dlg._designation_edit.setText("do not save me")
    dlg._preset_box.setCurrentIndex(1)                  # "Plate"
    assert saved["preset"] == "Plate"
    assert saved["style"]["treatment"] == "shadow"      # the whole look, not just a name
    assert "do not save me" not in str(saved)


def test_caption_controls_disable_with_the_caption_checkbox(qtbot):
    dlg = _dlg(qtbot)
    assert dlg._caption_wrap.isEnabled()
    dlg._caption_check.setChecked(False)
    assert not dlg._caption_wrap.isEnabled(), "no point styling a plate that is off"
    assert dlg._plate() == PlateText("", "", "")


def test_a_saved_look_is_restored_next_time(qtbot):
    """Was test_a_saved_style_is_restored_next_time, against share_caption_*.
    The look now lives in plate_preset + plate_style; the type size stays in
    share_caption_size, which is the same quantity that field always held."""
    from nocturne.core.presets import preset_by_name, style_to_dict
    from nocturne.settings import Settings
    from nocturne.ui.share_dialog import ShareDialog
    from dataclasses import replace
    saved = style_to_dict(replace(preset_by_name("Plate"), colour="#ff8800",
                                  anchor="top-right", family="Marcellus"))
    s = Settings(handle="me", plate_preset="Plate", plate_style=saved,
                 share_caption_size=0.038)
    dlg = ShareDialog(_rgb(), {"target": "X"}, s)
    qtbot.addWidget(dlg)
    assert dlg._preset_box.currentData() == "Plate"
    assert dlg._cap_colour == "#ff8800"
    assert dlg._anchor_box.currentData() == "top-right"
    assert dlg._family_box.currentData() == "Marcellus"
    assert dlg._cap_size_box.currentData() == pytest.approx(0.038)
    assert dlg._style().anchor == "top-right", "and it reaches the renderer"


def test_a_saved_look_naming_a_different_preset_is_ignored(qtbot):
    """plate_style and plate_preset disagreeing means one of them silently
    loses; the selected preset is the one the user can see, so it wins."""
    from nocturne.core.presets import preset_by_name, style_to_dict
    from nocturne.settings import Settings
    from nocturne.ui.share_dialog import ShareDialog
    s = Settings(plate_preset="Matte", plate_style=style_to_dict(preset_by_name("Keyline")))
    dlg = ShareDialog(_rgb(), {"target": "X"}, s)
    qtbot.addWidget(dlg)
    assert dlg._style().treatment == preset_by_name("Matte").treatment


def test_a_users_own_preset_is_offered_and_usable(qtbot):
    """plate_user_presets is a list of style dicts; a look saved there has to
    appear in the picker or it is unreachable."""
    from nocturne.core.presets import preset_by_name, style_to_dict
    from nocturne.settings import Settings
    from nocturne.ui.share_dialog import ShareDialog
    from dataclasses import replace
    mine = style_to_dict(replace(preset_by_name("Plate"), name="Mine", anchor="top-left"))
    s = Settings(plate_preset="Mine", plate_user_presets=[mine])
    dlg = ShareDialog(_rgb(), {"target": "X"}, s)
    qtbot.addWidget(dlg)
    assert dlg._preset_box.currentData() == "Mine"
    assert dlg._style().anchor == "top-left"


def test_a_malformed_saved_preset_does_not_stop_share_opening(qtbot):
    from nocturne.settings import Settings
    from nocturne.ui.share_dialog import ShareDialog
    s = Settings(plate_user_presets=["not a style at all"], plate_preset="nope")
    dlg = ShareDialog(_rgb(), {"target": "X"}, s)
    qtbot.addWidget(dlg)
    assert dlg._compose_current().width() > 0


def test_every_style_control_persists(qtbot):
    """Was test_alignment_and_opacity_persist, against the two controls the
    plate replaced. Anything you can change here is a house style, so all of it
    has to survive the dialog closing."""
    saved = {}
    from nocturne.settings import Settings
    from nocturne.ui.share_dialog import ShareDialog
    dlg = ShareDialog(_rgb(), {"target": "X"}, Settings(handle="me"),
                      settings_saver=lambda s: saved.update(style=dict(s.plate_style),
                                                            size=s.share_caption_size))
    qtbot.addWidget(dlg)
    dlg._anchor_box.setCurrentIndex(0)                   # Top left
    assert saved["style"]["anchor"] == "top-left"
    dlg._family_box.setCurrentIndex(3)
    assert saved["style"]["family"] == dlg._family_box.currentData()
    dlg._treatment_box.setCurrentIndex(3)                # None
    assert saved["style"]["treatment"] == "none"
    dlg._cap_size_box.setCurrentIndex(2)                 # Large
    assert saved["size"] == pytest.approx(0.038)


# --- caption vs burned annotations -------------------------------------------

def _annotated_dlg(qtbot, preset="Scrim"):
    from nocturne.settings import Settings
    from nocturne.ui.share_dialog import ShareDialog
    d = ShareDialog(_rgb(), {"target": "NGC 7000"},
                    Settings(handle="me", plate_preset=preset),
                    annotated_rgb8=_rgb(), annotations_on=True)
    qtbot.addWidget(d)
    return d


def test_annotations_default_the_plate_to_a_matte(qtbot):
    """Was test_annotations_default_the_caption_below_the_image. Every other
    treatment paints over whatever the overlay drew at the bottom: on a real
    NGC 7000 export the band swallowed the RA grid labels and cut the B 358
    label in half. The matte extends the canvas instead."""
    d = _annotated_dlg(qtbot, preset="Scrim")     # saved look says gradient
    assert d._style().treatment == "matte"
    assert d._treatment_box.currentData() == "matte", \
        "the control must not read Gradient while the preview shows a matte"


def test_without_annotations_the_saved_look_is_respected(qtbot):
    """The default belongs to "this share has annotations", not to the user."""
    d = _dlg(qtbot)                                # no annotated frame supplied
    assert d._style().treatment == "scrim"


def test_the_user_can_still_choose_any_treatment(qtbot):
    """A default, not a lock — and once chosen it must stick."""
    d = _annotated_dlg(qtbot)
    assert d._style().treatment == "matte"
    idx = next(i for i in range(d._treatment_box.count())
               if d._treatment_box.itemData(i) == "scrim")
    d._treatment_box.setCurrentIndex(idx)
    assert d._style().treatment == "scrim"
    assert d._placement_touched
    # toggling annotations must not override the explicit choice
    d._set_annotations(False)
    d._set_annotations(True)
    assert d._style().treatment == "scrim", "an explicit choice was overridden by the default"


def test_turning_annotations_on_mid_session_mattes_an_untouched_plate(qtbot):
    from nocturne.settings import Settings
    from nocturne.ui.share_dialog import ShareDialog
    d = ShareDialog(_rgb(), {"target": "X"}, Settings(plate_preset="Scrim"),
                    annotated_rgb8=_rgb(), annotations_on=False)
    qtbot.addWidget(d)
    assert d._style().treatment == "scrim"
    d._set_annotations(True)
    assert d._style().treatment == "matte", "the collision should have been pre-empted"
    assert not d._placement_touched, "a default must not count as a user choice"
    d._set_annotations(False)
    assert d._style().treatment == "scrim", "and it lifts again when they come off"


def test_the_annotation_default_is_not_persisted(qtbot):
    """It belongs to this share, not to the user's house style."""
    from nocturne.settings import Settings
    from nocturne.ui.share_dialog import ShareDialog
    saved = {}
    d = ShareDialog(_rgb(), {"target": "X"}, Settings(plate_preset="Scrim"),
                    annotated_rgb8=_rgb(), annotations_on=True,
                    settings_saver=lambda s: saved.update(t=s.plate_style.get("treatment")))
    qtbot.addWidget(d)
    assert d._style().treatment == "matte"
    assert saved == {}, "opening the dialog must not rewrite the saved look"

    d._cap_size_box.setCurrentIndex(2)          # an unrelated, explicit change
    assert saved["t"] == "scrim", \
        "the matte came from the annotations, so it must not be saved as a house style"


# --- the title plate ----------------------------------------------------------

def test_the_three_slots_are_prefilled_from_the_image(qtbot):
    d = _dlg(qtbot, meta={"target_designation": "IC 1396A",
                          "target_common": "Elephant's Trunk Nebula"})
    assert d._designation_edit.text() == "IC 1396A"
    assert d._common_edit.text() == "Elephant's Trunk Nebula"


def test_clearing_a_slot_removes_that_line(qtbot):
    """Auto-fill is a starting point, never a constraint."""
    from nocturne.ui.plate_render import last_layout
    d = _dlg(qtbot, meta={"target_designation": "IC 1396A",
                          "target_common": "Elephant's Trunk Nebula"})
    d._refresh_preview()
    with_both = last_layout()["block_height"]
    d._designation_edit.setText("")
    d._refresh_preview()
    assert last_layout()["block_height"] < with_both


def test_choosing_a_preset_changes_the_preview(qtbot):
    """A picker that does not visibly do anything reads as broken."""
    d = _dlg(qtbot)
    d._preset_box.setCurrentIndex(0)
    a = d._compose_current()
    d._preset_box.setCurrentIndex(3)          # Matte extends the canvas
    b = d._compose_current()
    assert (a.width(), a.height()) != (b.width(), b.height())


def test_the_slot_reset_button_restores_what_the_image_says(qtbot):
    d = _dlg(qtbot, meta={"target_designation": "IC 1396A",
                          "target_common": "Elephant's Trunk Nebula"})
    d._common_edit.setText("something else")
    d._reset_slots()
    assert d._common_edit.text() == "Elephant's Trunk Nebula"


def test_the_chosen_font_reaches_the_renderer(qtbot):
    """A family picker that the painter ignores is the silent-substitution bug
    we bundled fonts to avoid, reintroduced one layer up."""
    d = _dlg(qtbot)
    d._family_box.setCurrentIndex(2)
    chosen = d._family_box.currentData()
    assert d._style().family == chosen


def test_the_chosen_size_reaches_the_renderer(qtbot):
    """The size control scales the preset rather than flattening its three
    sizes into one — the hierarchy is what the preset is for."""
    d = _dlg(qtbot)
    d._cap_size_box.setCurrentIndex(0)                   # Small
    small = d._style()
    d._cap_size_box.setCurrentIndex(2)                   # Large
    large = d._style()
    assert large.size_title > small.size_title
    assert large.size_title / large.size_credit == pytest.approx(
        small.size_title / small.size_credit), "the preset's proportions survive"


def test_the_preview_equals_the_export(qtbot, tmp_path):
    """The project's stated principle: the preview at any step must EQUAL what
    export would produce; "probably the same" is a bug.

    Compares PIXELS, not dimensions. The dimensions-only version of this test
    was proven toothless by mutation on 2026-09-02 — replacing _do_export's
    body with a compose of PlateText("WRONG","WRONG","WRONG") left all 42
    dialog tests green, because the canvas size was unchanged. Text, style,
    crop and font could all differ between what you saw and what you got.
    """
    import numpy as np
    from PySide6.QtGui import QImage

    def pixels(img):
        img = img.convertToFormat(QImage.Format.Format_RGB888)
        w, h = img.width(), img.height()
        return np.frombuffer(img.constBits(), np.uint8).reshape(
            h, img.bytesPerLine())[:, :w * 3].copy()

    d = _dlg(qtbot)
    d._preset_box.setCurrentIndex(1)
    d._common_edit.setText("Elephant's Trunk Nebula")
    shown = d._compose_current()
    saved = {}
    d._save_runner = lambda img, path, *a, **k: saved.update(img=QImage(img))
    d._do_export(str(tmp_path / "x.jpg"))
    assert saved, "nothing was handed to the writer"
    got = saved["img"]
    assert (got.width(), got.height()) == (shown.width(), shown.height())
    assert np.array_equal(pixels(got), pixels(shown)), \
        "the exported pixels differ from the ones you were shown"


def test_the_clipboard_gets_what_you_were_shown_too(qtbot):
    """Copy is an output path like Export, and it goes through the same single
    compose. Guarded because a second compose path is exactly how the preview
    and the output drift apart."""
    import numpy as np
    from PySide6.QtGui import QImage

    def pixels(img):
        img = img.convertToFormat(QImage.Format.Format_RGB888)
        w, h = img.width(), img.height()
        return np.frombuffer(img.constBits(), np.uint8).reshape(
            h, img.bytesPerLine())[:, :w * 3].copy()

    d = _dlg(qtbot)
    shown = d._compose_current()
    got = {}
    d._clipboard_runner = lambda img: got.update(img=QImage(img))
    d._do_copy()
    assert got, "nothing reached the clipboard"
    assert np.array_equal(pixels(got["img"]), pixels(shown))


def test_with_annotations_on_the_default_becomes_matte(qtbot):
    """Closes the known bug: the band paints over burned annotations — RA
    labels land inside it and 'B 358' is cut in half. Matte extends the canvas,
    so nothing is covered."""
    d = _dlg(qtbot, annotated_rgb8=np.zeros((400, 300, 3), np.uint8), annotations_on=True)
    assert d._style().treatment == "matte"


def test_a_users_explicit_choice_survives_the_annotation_default(qtbot):
    """A default must not overrule a choice — the existing _placement_touched
    rule, kept."""
    d = _dlg(qtbot, annotated_rgb8=np.zeros((400, 300, 3), np.uint8), annotations_on=False)
    d._preset_box.setCurrentIndex(1)                  # the user picks Plate
    chosen = d._style().treatment                     # capture BEFORE, and assert
    d._annot_check.setChecked(True)                   # then turns annotations on
    assert d._style().treatment == chosen, (
        f"annotations overrode an explicit choice: {chosen} -> {d._style().treatment}")
    assert d._style().treatment != "matte"


def test_long_text_says_it_wrapped_rather_than_vanishing(qtbot):
    """It used to elide in silence. The notice says WRAPPED, not "did not fit":
    the flag is set on any second line, and a two-line nebula name fits fine."""
    d = _dlg(qtbot)
    d._common_edit.setText("x" * 400)
    assert "wrapped" in d.status.text().lower()
    assert "will not fit" not in d.status.text().lower()


def test_exporting_does_not_erase_the_wrap_notice(qtbot, tmp_path):
    """One label, two channels. Export wrote straight over it, so the notice
    vanished the moment you acted on it — you read "this wrapped", exported,
    and the reason it wrapped was gone."""
    d = _dlg(qtbot)
    d._common_edit.setText("x" * 400)
    assert "wrapped" in d.status.text().lower()
    d._save_runner = lambda img, path, *a, **k: None
    d._do_export(str(tmp_path / "x.jpg"))
    assert "Saved" in d.status.text(), "the export result is gone"
    assert "wrapped" in d.status.text().lower(), "the warning was erased by the result"


def test_copying_does_not_erase_it_either(qtbot):
    d = _dlg(qtbot)
    d._common_edit.setText("x" * 400)
    d._clipboard_runner = lambda img: None
    d._do_copy()
    assert "Copied" in d.status.text()
    assert "wrapped" in d.status.text().lower()


def test_the_warning_clears_when_the_text_fits_again(qtbot):
    """A warning that stays up after the problem is gone is worse than none."""
    d = _dlg(qtbot)
    d._common_edit.setText("x" * 400)
    assert d.status.text()
    d._common_edit.setText("M 31")
    assert d.status.text() == ""


def test_an_empty_plate_does_not_inherit_the_last_warning(qtbot):
    """last_layout() is global and written by the last draw_plate ANYWHERE — an
    empty plate never reaches the painter, so it would otherwise report the
    previous image's overflow."""
    d = _dlg(qtbot)
    d._common_edit.setText("x" * 400)
    assert d.status.text()
    d._caption_check.setChecked(False)
    assert d.status.text() == ""


def test_the_preview_fills_the_pane_it_is_given(qtbot):
    """__init__ composes before the layout has run, when the label is still at
    its 240x220 minimum. Without a re-fit the preview stayed that size for the
    life of the dialog — a small picture in a large empty box. Tolerable for
    checking a crop, not for judging type, which is what this pane is now for."""
    d = _dlg(qtbot)
    d.resize(1200, 760)
    d.show()
    qtbot.waitExposed(d)
    small = d._preview_label.pixmap().size()
    d.resize(1600, 1000)
    qtbot.waitUntil(lambda: d._preview_label.pixmap().width() > small.width(), timeout=2000)
    assert d._preview_label.pixmap().width() > small.width()
    # and it must actually USE the pane, not sit at the old minimum
    assert d._preview_label.pixmap().width() > d._preview_label.width() * 0.6


def test_resizing_does_not_recompose(qtbot):
    """A drag emits a resize per frame; recomposing a 4096 px share on each one
    would make the dialog crawl."""
    d = _dlg(qtbot)
    d.show(); qtbot.waitExposed(d)
    calls = []
    real = d._compose_current
    d._compose_current = lambda: (calls.append(1), real())[1]
    d.resize(1300, 820)
    qtbot.wait(50)
    assert calls == [], f"recomposed {len(calls)} times on resize"


def test_a_solve_hands_the_plate_both_halves_directly(qtbot, tmp_path):
    """The spec's intended path was dead code: the solve wrote only the joined
    "M 31 · Andromeda Galaxy" and plate_text split it back apart. That works,
    but it makes the " · " separator load-bearing for no reason when the solve
    has the pair in hand."""
    from nocturne.core.catalog import CatalogObject
    from nocturne.core.plate import plate_text
    objs = [CatalogObject(name="NGC 7000", common="North America Nebula",
                          ra_deg=314.8, dec_deg=44.5, major_arcmin=120.0, x=50, y=50)]
    from nocturne.core.catalog import identify_target_parts
    desig, common = identify_target_parts(objs, (100, 100))
    t = plate_text({"target_designation": desig, "target_common": common}, "")
    assert (t.designation, t.common) == ("NGC 7000", "North America Nebula")
    # and the wiring exists at the call site, not only in the helper
    from pathlib import Path
    src = (Path(__file__).parents[2] / "nocturne" / "ui" / "main_window.py").read_text()
    assert "target_designation" in src and "identify_target_parts" in src, \
        "the solve does not write the pair; the plate is back to splitting a string"


def test_the_preview_is_right_sized_on_FIRST_open(qtbot):
    """resizeEvent alone was not enough: the resizes during show arrive before
    the splitter has its final geometry, so first open showed 276x345 inside a
    547x473 pane. You should not have to nudge the window to see your image."""
    d = _dlg(qtbot)
    d.resize(1120, 700)
    d.show()
    qtbot.waitExposed(d)
    pane = d._preview_label
    pm = pane.pixmap()
    assert pm.height() >= pane.height() * 0.95 or pm.width() >= pane.width() * 0.95, (
        f"first open shows {pm.width()}x{pm.height()} in a {pane.width()}x{pane.height()} pane")


def test_a_build_with_no_bundled_fonts_says_so_instead_of_lying(qtbot, monkeypatch):
    """The fallback used to be `available_families() or PLATE_FAMILIES`, so a
    build whose assets/fonts folder was missing offered all five families and
    drew every one of them in the system font, silently. That is precisely the
    failure bundling exists to prevent — fonts.py's own docstring calls it "the
    worst failure available: the export is wrong and nothing says so."
    """
    import nocturne.ui.share_dialog as sd
    monkeypatch.setattr(sd, "available_families", lambda: [])
    d = _dlg(qtbot)
    offered = [d._family_box.itemData(i) for i in range(d._family_box.count())]
    assert not any(offered), f"offers type it cannot draw: {offered}"
    assert not d._family_box.isEnabled(), "the picker pretends to offer a choice"
    assert "unavailable" in d._family_box.itemText(0).lower()
