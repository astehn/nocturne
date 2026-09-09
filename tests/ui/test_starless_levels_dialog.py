import numpy as np
import pytest

from nocturne.core.image import AstroImage
from nocturne.ui.curves_dialog import _PREVIEW_MAX
from nocturne.ui.preview import qimage_to_rgb8
from nocturne.ui.starless_levels_dialog import StarlessLevelsDialog


@pytest.fixture
def split():
    starless = np.zeros((32, 32, 3), np.float32)
    starless[8:16, 8:16] = 0.60
    stars = np.zeros((32, 32, 3), np.float32)
    stars[0, 0] = 0.95
    return (AstroImage(starless, is_linear=False, metadata={}),
            AstroImage(stars, is_linear=False, metadata={}))


def test_opens_at_identity_endpoints(qtbot, split):
    dlg = StarlessLevelsDialog(*split)
    qtbot.addWidget(dlg)
    assert dlg.values() == (0.0, 1.0)


def test_sliders_can_represent_their_own_defaults(qtbot, split):
    """A slider whose divisor cannot express its default silently shifts the
    image the moment the dialog opens."""
    dlg = StarlessLevelsDialog(*split)
    qtbot.addWidget(dlg)
    black, white = dlg.values()
    assert black == 0.0 and white == 1.0


def test_compose_matches_the_core_function_exactly(qtbot, split):
    """WYSIWYG: the dialog must not have its own arithmetic."""
    from nocturne.core.enhance import starless_levels_layers
    starless, stars = split
    dlg = StarlessLevelsDialog(starless, stars)
    qtbot.addWidget(dlg)
    dlg.white_slider.setValue(600)
    out = dlg.compose()
    expected = starless_levels_layers(starless, stars, 0.0, 0.6)
    assert np.allclose(out.data, expected.data, atol=1e-6)


def test_white_slider_drives_the_white_point(qtbot, split):
    dlg = StarlessLevelsDialog(*split)
    qtbot.addWidget(dlg)
    dlg.white_slider.setValue(600)
    assert dlg.values()[1] == pytest.approx(0.6, abs=1e-6)


def test_clipping_toggle_is_off_by_default(qtbot, split):
    dlg = StarlessLevelsDialog(*split)
    qtbot.addWidget(dlg)
    assert dlg.clip_check.isChecked() is False


def test_apply_delivers_the_composed_image_and_the_values(qtbot, split):
    seen = {}
    dlg = StarlessLevelsDialog(*split,
                               on_apply=lambda img, vals: seen.update(img=img, vals=vals))
    qtbot.addWidget(dlg)
    dlg.white_slider.setValue(600)
    dlg._apply()
    assert seen["vals"] == (0.0, 0.6)
    assert seen["img"].data.shape == (32, 32, 3)


def test_stars_are_untouched_by_the_dialog(qtbot, split):
    """Assert the stars array is EQUAL to what it was, not merely different
    from some known-bad value."""
    starless, stars = split
    before = stars.data.copy()
    dlg = StarlessLevelsDialog(starless, stars)
    qtbot.addWidget(dlg)
    dlg.white_slider.setValue(400)
    dlg.compose()
    assert np.array_equal(stars.data, before)


# --- Show Clipping: the mask must come from the full-resolution composite ----

def test_show_clipping_finds_a_speck_the_decimated_preview_would_hide(qtbot):
    """The brief's own 7 tests never toggle `clip_check` and render — this is
    the task's only subtle correctness requirement, and a "simplification" to
    build the mask from the decimated preview would pass every one of them
    while silently blinding the tool.

    Size comfortably larger than `_PREVIEW_MAX` (640) so the preview really is
    decimated (2x2 block averaging, not a no-op). A MID-GREY background, not
    black: a black background is itself shadow-clipped (rgb == 0), which would
    light the whole overlay for the wrong reason and let this assertion pass
    even from a broken implementation.

    One pixel is seeded so that, after the levels below, it alone is blown:
    - full resolution: 1.0 / white(0.7) = 1.43 -> clips to 1.0 (255)
    - its own 2x2 decimation block: (1.0 + 3*0.5) / 4 = 0.625; 0.625/0.7 = 0.89
      -> stays under 1.0, so the decimated copy shows nothing wrong there
    - the plain background: 0.5 / 0.7 = 0.71 -> 182, neither 0 nor 255, so it
      cannot itself trip the shadow or highlight mask
    """
    size = 2 * _PREVIEW_MAX   # 1280: guarantees real 2x2-block decimation
    starless = np.full((size, size, 3), 0.5, np.float32)
    starless[100, 100] = 1.0
    stars = np.zeros((size, size, 3), np.float32)
    dlg = StarlessLevelsDialog(AstroImage(starless, is_linear=False, metadata={}),
                               AstroImage(stars, is_linear=False, metadata={}))
    qtbot.addWidget(dlg)
    # A label SMALLER than the source, so the overlay is really reduced 4x and
    # the speck has to survive a genuine block-max. The first version of this
    # test matched the label to the overlay's own resolution, which made the
    # reduction an identity — it could not have caught a diluting one.
    dlg.preview_label.resize(320, 320)
    dlg.white_slider.setValue(700)
    dlg.clip_check.setChecked(True)
    dlg._render_preview()

    rgb = qimage_to_rgb8(dlg.preview_label.pixmap().toImage())
    assert rgb.max() >= 250, (
        "no clipped pixel reached the overlay: the mask was built from the "
        "decimated preview, which averaged the seeded pixel away")


def test_an_isolated_speck_reaches_the_screen_at_full_intensity(qtbot):
    """The block-max is undone by whatever happens after it.

    `clip_overlay` goes to lengths to keep an isolated speck at 255, and the
    pixmap was then `.scaled(..., SmoothTransformation)` to the label —
    measured to drop an isolated lit block to 195, 111 or 55 depending on the
    factor. A blown speck could therefore render DIMMER than a flat crushed
    background, which inverts the legend all over again. The overlay is now
    block-maxed straight to the displayed size, with no rescale.

    `>= 250`, not `> 0`: the whole failure mode is a speck that survives while
    being dimmed, so truthiness cannot see it. The background is mid-grey so it
    contributes nothing of its own — a np.zeros background is itself
    shadow-clipped and would light the frame for the wrong reason.
    """
    size = 1200
    starless = np.full((size, size, 3), 0.5, np.float32)
    starless[600, 600] = 1.0                # one pixel, blown after the levels
    stars = np.zeros((size, size, 3), np.float32)
    dlg = StarlessLevelsDialog(AstroImage(starless, is_linear=False, metadata={}),
                               AstroImage(stars, is_linear=False, metadata={}))
    qtbot.addWidget(dlg)
    dlg.preview_label.resize(400, 400)      # 3x reduction: a real rescale
    dlg.white_slider.setValue(700)
    dlg.clip_check.setChecked(True)
    dlg._render_preview()

    pm = dlg.preview_label.pixmap()
    assert (pm.width(), pm.height()) == (400, 400), \
        "the overlay was not produced at the size it is displayed at"
    rgb = qimage_to_rgb8(pm.toImage())
    assert int(rgb.max()) == 255, (
        f"the speck reached the screen at {int(rgb.max())}, not 255 — something "
        "re-diluted the block-max after clip_overlay produced it")
    assert np.count_nonzero(rgb) <= 12, \
        "more than one block lit: the speck was smeared across neighbours"


# --- pan and zoom --------------------------------------------------------

def test_view_changes_queue_a_redraw(qtbot, split):
    """`_ZoomPreview.viewChanged` fires on both wheel-zoom and drag-pan
    (curves_dialog.py). Without this wired to the debounced re-render, the
    widget still tracks the gesture internally but the picture never updates
    -- reads as a frozen dialog, and finding the first clipped specks by
    zooming in IS this tool's workflow."""
    dlg = StarlessLevelsDialog(*split)
    qtbot.addWidget(dlg)
    with qtbot.waitSignal(dlg._timer.timeout, timeout=500, raising=True):
        dlg.preview_label.set_zoom(2.0)
