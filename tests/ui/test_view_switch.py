"""The Import step's Linked/Unlinked switch — a VIEW, never a commitment.

Andreas, 2026-09-14, on opening the same IC 1396A master in both tools: Nocturne
is *"all monochromatic, always red"* while AstroWizard shows *"red where its
supposed to be red and blue where its supposed to be"*. The cause is the import
view's stretch, not the committed one, so the fix is a switch that changes how
the linear data is DRAWN and nothing else.
"""
import numpy as np
import pytest
from astropy.io import fits

pytest.importorskip("PySide6")
from nocturne.ui.main_window import MainWindow  # noqa: E402
from nocturne.ui.pipeline import Stage  # noqa: E402
from nocturne.ui.step_panels import build_panel  # noqa: E402


def _make_fits(tmp_path, name="stack.fits"):
    """Red given the wider spread, as on the real data — channels that commute
    cannot tell the two stretches apart."""
    rng = np.random.default_rng(0)
    arr = rng.normal(1200, 60, (3, 24, 24))
    arr[0] = 1200 + (arr[0] - 1200) * 2.67
    p = tmp_path / name
    hdu = fits.PrimaryHDU(np.clip(arr, 0, 65535).astype(np.uint16))
    hdu.header["FILTER"] = "L"
    hdu.writeto(str(p))
    return str(p)


def _window(qtbot, tmp_path):
    win = MainWindow(settings_path=str(tmp_path / "settings.json"), check_updates=False)
    win._async_enabled = False
    qtbot.addWidget(win)
    win.open_fits(_make_fits(tmp_path))
    return win


def test_the_import_panel_has_no_open_fits_button(qtbot):
    """The toolbar has one (main_window.py:1755) and the cold-start screen has
    its own pair, so the panel's copy was unreachable in every state where it
    would have been the entry point. Andreas: "the function serves no purpose"."""
    from PySide6.QtWidgets import QPushButton
    w = build_panel(Stage("load", "Import", "import"))
    assert [b.text() for b in w.findChildren(QPushButton) if "Open FITS" in b.text()] == []


def test_the_import_panel_offers_the_view_switch(qtbot):
    w = build_panel(Stage("load", "Import", "import"))
    assert hasattr(w, "view_linked")
    assert w.view_linked.isChecked() is True          # linked is the default


def _on_screen(win):
    """What the CANVAS is actually displaying, read back from the widget.

    Not a re-render through the same code path the switch feeds: an earlier
    version of this test called a helper that recomputed to_rgb8() itself, so it
    passed with the canvas hard-wired to ignore the switch entirely. The pixmap
    is the only independent witness.
    """
    from nocturne.ui.preview import qimage_to_rgb8
    return qimage_to_rgb8(win.image_view._item.pixmap().toImage())


def test_the_switch_changes_the_canvas(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    shown = np.array(_on_screen(win), copy=True)
    win._set_view_linked(False)
    assert not np.array_equal(_on_screen(win), shown)


def test_the_canvas_shows_the_chosen_stretch_not_merely_a_different_one(qtbot, tmp_path):
    """'It changed' is satisfied by changing to anything. Pin WHAT it changed to."""
    from nocturne.ui.preview import to_rgb8
    win = _window(qtbot, tmp_path)
    win._set_view_linked(False)
    expected = to_rgb8(win._canvas_img, linked=False)
    assert np.array_equal(_on_screen(win), expected)


def test_the_switch_touches_neither_the_data_nor_the_history(qtbot, tmp_path):
    """Captured before and asserted UNCHANGED, per CLAUDE.md — a check that the
    data is merely 'not some known wrong value' passes while a different wrong
    value is written."""
    win = _window(qtbot, tmp_path)
    before = np.array(win.project.current().data, copy=True)
    depth = len(win.project.entries())
    win._set_view_linked(False)
    assert np.array_equal(win.project.current().data, before)
    assert len(win.project.entries()) == depth


def test_the_choice_survives_walking_to_the_next_linear_step(qtbot, tmp_path):
    """Import alone is not enough: every pre-stretch step draws linear data, so
    walking to Crop must not flip the picture back or the switch looks broken."""
    win = _window(qtbot, tmp_path)
    win._set_view_linked(False)
    win.go_next()                                  # Import -> Crop
    assert win.current_stage_id() == "crop"
    assert win._view_linked is False


def test_it_does_not_leak_into_a_measurement(qtbot, tmp_path):
    """The clipping baseline is a measurement. A number that moves because of
    how the user is looking at the image is the failure this project has hit
    three times."""
    win = _window(qtbot, tmp_path)
    before = win._structural_baseline
    win._set_view_linked(False)
    assert win._structural_baseline == before
