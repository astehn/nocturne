"""Opening a TIFF: a linear master from another stacker, or a finished picture.

The pipeline needed no new entry point. A linear TIFF enters at the top exactly
as a FITS does; a stretched one enters non-linear, and `_ensure_stretched`
already gates the finishing steps on `is_linear`, so the whole post-stretch tail
is reachable and correct with no new machinery.
"""
import numpy as np
import pytest
import tifffile

pytest.importorskip("PySide6")
from PySide6.QtGui import QAction  # noqa: E402

from nocturne.core.image import AstroImage  # noqa: E402
from nocturne.core.stretch import apply_stretch  # noqa: E402
from tests.ui.test_main_window import _make_fits, _window  # noqa: E402


def _linear_pixels():
    rng = np.random.default_rng(0)
    d = np.clip(rng.normal(0.02, 0.005, (240, 180, 3)), 0, 1).astype(np.float32)
    d[10:14, 10:14] = 0.9
    return d


def _write_linear_tiff(tmp_path, name="stack.tif"):
    p = tmp_path / name
    tifffile.imwrite(str(p), _linear_pixels())
    return str(p)


def _write_stretched_tiff(tmp_path, name="finished.tif"):
    st = apply_stretch(AstroImage(_linear_pixels(), is_linear=True), 0.3).data
    p = tmp_path / name
    tifffile.imwrite(str(p), (st * 65535).astype(np.uint16))
    return str(p)


def test_the_open_action_is_named_for_what_it_opens(qtbot, tmp_path):
    """"Open FITS" promised one format and now takes three extensions. The other
    open action is named for what it opens too ("Open Project", and a .nocturne
    bundle really is a different kind of thing), so this keeps the pair
    consistent rather than inventing a new convention."""
    win = _window(qtbot, tmp_path)
    labels = [a.text() for a in win.findChildren(QAction)]
    assert "Open Image" in labels, labels
    assert "Open FITS" not in labels


def test_a_linear_tiff_opens_at_the_top_of_the_pipeline(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_any(_write_linear_tiff(tmp_path))
    assert win.project is not None
    assert win.project.current().is_linear is True
    assert win.current_stage_id() == "load"


def test_a_stretched_tiff_opens_without_forcing_a_stretch(qtbot, tmp_path):
    """The whole point of landing non-linear: the finishing tail is reachable
    and nothing was committed on the way."""
    win = _window(qtbot, tmp_path)
    win.open_any(_write_stretched_tiff(tmp_path))
    assert win.project.current().is_linear is False
    win._go_to_id("levels")
    assert win.current_stage_id() == "levels"
    assert not any(n == "Stretch" for n, _ in win.project.entries())


def test_a_fits_still_opens_exactly_as_before(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_any(_make_fits(tmp_path))
    assert win.project.current().is_linear is True
    assert win.current_stage_id() == "load"


def test_an_uppercase_extension_is_accepted(qtbot, tmp_path):
    """macOS hands back whatever the file is actually called. A case-sensitive
    dispatch would send a .TIF down the FITS reader and fail confusingly."""
    win = _window(qtbot, tmp_path)
    win.open_any(_write_linear_tiff(tmp_path, name="STACK.TIF"))
    assert win.project is not None


def test_the_target_comes_from_the_filename_when_there_is_no_header(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_any(_write_linear_tiff(tmp_path, name="M 42 final.tif"))
    assert "M 42" in win._panel.meta_label.text()


# --- the verdict, and honest metadata ------------------------------------

def test_the_panel_states_which_it_decided(qtbot, tmp_path):
    win = _window(qtbot, tmp_path)
    win.open_any(_write_stretched_tiff(tmp_path))
    assert hasattr(win._panel, "opened_as_linear")
    assert win._panel.opened_as_linear.isChecked() is False      # already stretched
    win2 = _window(qtbot, tmp_path)
    win2.open_any(_write_linear_tiff(tmp_path))
    assert win2._panel.opened_as_linear.isChecked() is True


def test_the_override_re_enters_at_the_other_point(qtbot, tmp_path):
    """One click, because both known failure modes — a stretched STARLESS file
    with no bright tail, and a very bright subject — are invisible to us and
    obvious to the person looking at the picture."""
    win = _window(qtbot, tmp_path)
    win.open_any(_write_stretched_tiff(tmp_path))
    assert win.project.current().is_linear is False
    win._set_opened_as_linear(True)
    assert win.project.current().is_linear is True


def test_the_override_does_not_touch_the_pixels(qtbot, tmp_path):
    """Captured and asserted UNCHANGED. It corrects how the file is READ, and a
    reading is not an edit."""
    win = _window(qtbot, tmp_path)
    win.open_any(_write_stretched_tiff(tmp_path))
    before = np.array(win.project.current().data, copy=True)
    win._set_opened_as_linear(True)
    assert np.array_equal(win.project.current().data, before)


def test_no_switch_for_a_fits(qtbot, tmp_path):
    """A FITS is linear by the definition of the format we accept. Offering the
    choice would invite someone to get it wrong."""
    win = _window(qtbot, tmp_path)
    win.open_any(_make_fits(tmp_path))
    assert getattr(win._panel, "opened_as_linear", None) is None


def test_the_panel_names_no_camera_for_a_tiff(qtbot, tmp_path):
    """Asserted as ABSENT, not as "not the wrong camera" — per CLAUDE.md, a
    check that one wrong value is missing passes while a different wrong value
    is written.

    import_summary({}) assumes the S30 Pro and prints a sensor, a pixel size, a
    focal length and an image scale. Every one of those is a fabrication for a
    file that carries no headers, and image scale in particular feeds plate
    solving.
    """
    win = _window(qtbot, tmp_path)
    win.open_any(_write_linear_tiff(tmp_path))
    text = win._panel.meta_label.text()
    for banned in ("IMX585", "IMX662", "Seestar", "Pixel size", "Focal length",
                   "Image scale", "Sensor"):
        assert banned not in text, banned


def test_a_fits_still_gets_its_camera(qtbot, tmp_path):
    """The guard on the guard: omitting the block for a TIFF must not omit it
    for the file type that genuinely carries the information."""
    win = _window(qtbot, tmp_path)
    win.open_any(_make_fits(tmp_path))
    assert "Sensor" in win._panel.meta_label.text()


def test_the_panel_says_why_it_is_sparse(qtbot, tmp_path):
    """An empty panel reads as broken. It should say that a TIFF carries no
    capture details rather than leave the user wondering."""
    win = _window(qtbot, tmp_path)
    win.open_any(_write_linear_tiff(tmp_path))
    assert "TIFF" in win._panel.meta_label.text()


def test_a_corrected_tiff_survives_a_save_and_reopen(qtbot, tmp_path):
    """Open a TIFF, correct the verdict, save the project, reopen it.

    `is_linear` is per-snapshot state in the bundle (project_store writes it for
    the base and every step), so this should hold — but the whole point of the
    override is that the stored reading is the user's, not ours, and a bundle
    that forgot it would silently re-apply our guess.
    """
    win = _window(qtbot, tmp_path)
    win.open_any(_write_stretched_tiff(tmp_path))
    assert win.project.current().is_linear is False
    win._set_opened_as_linear(True)

    bundle = str(tmp_path / "corrected.nocturne")
    win._save_project_to(bundle) if hasattr(win, "_save_project_to") else win._do_save_project(bundle)

    win2 = _window(qtbot, tmp_path)
    win2._open_project(bundle)
    assert win2.project is not None, "the bundle did not reopen"
    assert win2.project.current().is_linear is True, "the correction was forgotten"


def test_batch_does_not_silently_skip_tiffs(qtbot, tmp_path):
    """Batch globs .fit/.fits/.fts only, so a folder of TIFFs yields nothing.

    Pinned as a KNOWN limitation rather than a bug: it fails visibly (no files
    matched) rather than half-processing, and extending it is separate work.
    This test exists so the next person meets the decision instead of the
    symptom.
    """
    from nocturne.ui.batch_dialog import _INPUT_PATTERNS
    assert _INPUT_PATTERNS == ("*.fit", "*.fits", "*.fts"), _INPUT_PATTERNS
    assert not any("tif" in p for p in _INPUT_PATTERNS), (
        "Batch grew TIFF support — update this test, the help, and batch.py's "
        "docstring, which still says the input glob is FITS-only")


def test_the_open_dialog_offers_every_extension_the_loader_reads():
    """The picker's filter IS the list of files a user can see.

    `.fts` loaded fine and batch's glob accepted it, but the dialog did not
    list it, so someone browsing for their own file simply could not find it —
    while the FAQ promised the extension. Asserted against the real filter
    string rather than a copy of it.
    """
    import inspect
    from nocturne.ui.main_window import MainWindow
    src = inspect.getsource(MainWindow._choose_fits)
    for ext in ("*.fit", "*.fits", "*.fts", "*.tif", "*.tiff"):
        assert ext in src, f"{ext} is readable but not offered in the Open dialog"
