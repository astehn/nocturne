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
