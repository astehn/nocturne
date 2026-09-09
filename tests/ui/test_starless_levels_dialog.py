import numpy as np
import pytest
from PySide6.QtGui import QImage

from nocturne.core.enhance import starless_levels_layers
from nocturne.core.image import AstroImage
from nocturne.core.inspect import CLIP_HIGHLIGHT, CLIP_MARK_OFF, CLIP_MARK_ON
from nocturne.ui.curves_dialog import _PREVIEW_MAX
from nocturne.ui.preview import qimage_to_rgb8, to_rgb8
from nocturne.ui.starless_levels_dialog import _MODES, StarlessLevelsDialog


@pytest.fixture
def split():
    """A mid-grey starless background, never np.zeros: a black background is
    itself shadow-clipped, which lights the clipping overlay for the wrong
    reason and lets a clipping assertion pass from a broken implementation."""
    starless = np.full((32, 32, 3), 0.30, np.float32)
    starless[8:16, 8:16] = 0.60
    stars = np.zeros((32, 32, 3), np.float32)
    stars[0, 0] = 0.95
    return (AstroImage(starless, is_linear=False, metadata={}),
            AstroImage(stars, is_linear=False, metadata={}))


def _drag(w, frm_x, to_x):
    """Press at normalised x `frm_x` on a RangeHandles and drag to `to_x`.

    Built and sent directly rather than driven with `qtbot.mouseMove`, which is
    unreliable here (CLAUDE.md) — the same helper `test_range_handles.py` uses.
    """
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication
    for typ, x, btn, held in (
        (QEvent.Type.MouseButtonPress, frm_x, Qt.MouseButton.LeftButton,
         Qt.MouseButton.LeftButton),
        (QEvent.Type.MouseMove, to_x, Qt.MouseButton.NoButton,
         Qt.MouseButton.LeftButton),
        (QEvent.Type.MouseButtonRelease, to_x, Qt.MouseButton.LeftButton,
         Qt.MouseButton.NoButton),
    ):
        pos = QPointF(w._x_to_px(x), w.height() / 2)
        QApplication.sendEvent(w, QMouseEvent(typ, pos, QPointF(0, 0), btn, held,
                                              Qt.KeyboardModifier.NoModifier))


def _size_preview(dlg, w, h):
    """Give the compare widget a real size AND lay its panes out.

    `resize()` updates the widget's own geometry immediately but only POSTS the
    child relayout, so without the explicit `activate()` the pane inside is
    still its default size when the render asks `pane_size()` for it.
    """
    dlg.preview.resize(w, h)
    dlg.preview.layout().activate()


def test_opens_at_identity_endpoints(qtbot, split):
    dlg = StarlessLevelsDialog(*split)
    qtbot.addWidget(dlg)
    assert dlg.values() == (0.0, 1.0)


def test_the_handles_can_represent_their_own_defaults(qtbot, split):
    """A control whose resolution cannot express its default silently shifts the
    image the moment the dialog opens."""
    dlg = StarlessLevelsDialog(*split)
    qtbot.addWidget(dlg)
    black, white = dlg.values()
    assert black == 0.0 and white == 1.0


def test_compose_matches_the_core_function_exactly(qtbot, split):
    """WYSIWYG: the dialog must not have its own arithmetic."""
    starless, stars = split
    dlg = StarlessLevelsDialog(starless, stars)
    qtbot.addWidget(dlg)
    dlg.handles.set_range(0.0, 0.6)
    out = dlg.compose()
    expected = starless_levels_layers(starless, stars, 0.0, 0.6)
    assert np.allclose(out.data, expected.data, atol=1e-6)


def test_dragging_the_high_handle_drives_the_white_point(qtbot, split):
    """The handles ARE the two points — there is no slider holding a second
    copy of the number that could disagree with them."""
    dlg = StarlessLevelsDialog(*split)
    qtbot.addWidget(dlg)
    dlg.handles.resize(400, 200)
    _drag(dlg.handles, 1.0, 0.6)
    black, white = dlg.values()
    assert white == pytest.approx(0.6, abs=0.03)
    assert black == pytest.approx(0.0, abs=0.001), "the black point moved too"
    assert dlg.white_val.text() == f"{white:.3f}"
    assert dlg.black_val.text() == f"{black:.3f}"


def test_the_handles_cannot_cross(qtbot, split):
    """Black 0.80 / white 0.20 used to be accepted: `apply_levels` quietly
    clamps a crossed pair to `white = black + 1e-4`, so the preview became a
    hard threshold while the labels still read "0.800 / 0.200" and the committed
    params described an operation that never happened.

    `RangeHandles` prevents it by construction (`_MIN_SPAN`), which is why the
    dialog no longer carries a clamp of its own — two guards that can disagree
    is the drift this rework removed."""
    dlg = StarlessLevelsDialog(*split)
    qtbot.addWidget(dlg)
    dlg.handles.resize(400, 200)
    _drag(dlg.handles, 0.0, 0.8)            # black up to 0.8
    _drag(dlg.handles, 1.0, 0.2)            # white down past it
    black, white = dlg.values()
    assert white > black, f"the handles crossed: black {black}, white {white}"
    assert dlg.black_val.text() == f"{black:.3f}"
    assert dlg.white_val.text() == f"{white:.3f}"


def test_reset_returns_exactly_the_identity_endpoints(qtbot, split):
    """Without a way back to exactly (0.0, 1.0) there is nothing to compare the
    edit against — the same job double-clicking a ResetSlider used to do."""
    dlg = StarlessLevelsDialog(*split)
    qtbot.addWidget(dlg)
    dlg.handles.resize(400, 200)
    _drag(dlg.handles, 0.0, 0.3)
    _drag(dlg.handles, 1.0, 0.6)
    assert dlg.values() != (0.0, 1.0)
    dlg.reset_btn.click()
    assert dlg.values() == (0.0, 1.0)
    assert (dlg.black_val.text(), dlg.white_val.text()) == ("0.000", "1.000")


def test_the_histogram_is_the_starless_layer_not_the_composite(qtbot, split):
    """The two points act on the starless layer. A composite histogram would
    show the screened-back stars as a bright tail neither handle can touch —
    exactly the confusion the tool exists to remove.

    The fixture's starless layer tops out at 0.60 while its star pixel screens
    the composite up past 0.95, so the top bins separate the two sources."""
    from nocturne.ui.range_handles import RangeHandles
    starless, stars = split
    dlg = StarlessLevelsDialog(starless, stars)
    qtbot.addWidget(dlg)

    reference = RangeHandles()
    qtbot.addWidget(reference)
    reference.set_histogram(starless.data)
    assert np.array_equal(dlg.handles._hist, reference._hist)

    composite = RangeHandles()
    qtbot.addWidget(composite)
    composite.set_histogram(starless_levels_layers(starless, stars, 0.0, 1.0).data)
    # bin 100 of 128 is luminance 0.78: above the starless layer's own maximum
    # of 0.60, and below the 0.965 the screened-back star reaches.
    assert composite._hist[100:].sum() > 0, "the fixture does not separate the two"
    assert dlg.handles._hist[100:].sum() == 0, \
        "the histogram carries the stars' bright tail — it is the composite"


# --- Show Clipping: the mask must come from the full-resolution composite ----

def test_show_clipping_finds_a_speck_the_decimated_preview_would_hide(qtbot):
    """A "simplification" to build the mask from the decimated preview would
    pass every other test in this file while silently blinding the tool.

    Size comfortably larger than `_PREVIEW_MAX` (640) so the preview really is
    decimated (2x2 block averaging, not a no-op). A MID-GREY background, not
    black: a black background is itself shadow-clipped (rgb == 0), which would
    light the whole overlay for the wrong reason and let this assertion pass
    even from a broken implementation.

    One pixel is seeded so that, after the levels below, it alone is blown:
    - full resolution: 0.9 / white(0.7) = 1.29 -> clips to 1.0 (255)
    - its own 2x2 decimation block: (0.9 + 3*0.5) / 4 = 0.6; 0.6/0.7 = 0.86
      -> stays under 1.0, so the decimated copy shows nothing wrong there
    - the plain background: 0.5 / 0.7 = 0.71 -> 182, neither 0 nor 255, so it
      cannot itself trip the shadow or highlight mask

    0.9 rather than 1.0, deliberately: a pixel already at 1.0 is blown with the
    tool doing NOTHING, so the baseline would (rightly) hold it back and this
    test would be asserting against the fix in change 3.
    """
    size = 2 * _PREVIEW_MAX   # 1280: guarantees real 2x2-block decimation
    starless = np.full((size, size, 3), 0.5, np.float32)
    starless[100, 100] = 0.9
    stars = np.zeros((size, size, 3), np.float32)
    dlg = StarlessLevelsDialog(AstroImage(starless, is_linear=False, metadata={}),
                               AstroImage(stars, is_linear=False, metadata={}))
    qtbot.addWidget(dlg)
    # A pane SMALLER than the source, so the overlay is really reduced 4x and
    # the speck has to survive a genuine block-max. The first version of this
    # test matched the pane to the overlay's own resolution, which made the
    # reduction an identity — it could not have caught a diluting one.
    _size_preview(dlg, 320, 320)
    dlg.handles.set_range(0.0, 0.7)
    dlg.clip_check.setChecked(True)
    dlg._render_preview()

    rgb = qimage_to_rgb8(dlg.preview._after_pane.pixmap().toImage())
    assert rgb.max() >= 250, (
        "no clipped pixel reached the overlay: the mask was built from the "
        "decimated preview, which averaged the seeded pixel away")


def test_an_isolated_speck_reaches_the_screen_at_full_intensity(qtbot):
    """The block-max is undone by whatever happens after it.

    `clip_overlay` goes to lengths to keep an isolated speck at 255, and the
    pixmap was then `.scaled(..., SmoothTransformation)` to the pane —
    measured to drop an isolated lit block to 195, 111 or 55 depending on the
    factor. A blown speck could therefore render DIMMER than a flat crushed
    background, which inverts the legend all over again. The overlay is now
    block-maxed straight to the displayed size, and handed to `CompareView` at
    exactly that size so its own scale-to-fit is a no-op.

    `>= 250`, not `> 0`: the whole failure mode is a speck that survives while
    being dimmed, so truthiness cannot see it. The background is mid-grey so it
    contributes nothing of its own — a np.zeros background is itself
    shadow-clipped and would light the frame for the wrong reason.
    """
    size = 1200
    starless = np.full((size, size, 3), 0.5, np.float32)
    starless[600, 600] = 0.9                # one pixel, blown after the levels
    stars = np.zeros((size, size, 3), np.float32)
    dlg = StarlessLevelsDialog(AstroImage(starless, is_linear=False, metadata={}),
                               AstroImage(stars, is_linear=False, metadata={}))
    qtbot.addWidget(dlg)
    _size_preview(dlg, 400, 400)            # 3x reduction: a real rescale
    dlg.handles.set_range(0.0, 0.7)
    dlg.clip_check.setChecked(True)
    dlg._render_preview()

    pm = dlg.preview._after_pane.pixmap()
    assert (pm.width(), pm.height()) == (400, 400), \
        "the overlay was not produced at the size it is displayed at"
    rgb = qimage_to_rgb8(pm.toImage())
    assert int(rgb.max()) == 255, (
        f"the speck reached the screen at {int(rgb.max())}, not 255 — something "
        "re-diluted the block-max after clip_overlay produced it")
    assert np.count_nonzero(rgb) <= 12, \
        "more than one block lit: the speck was smeared across neighbours"


# --- Show Clipping: only what the tool ADDS -------------------------------

@pytest.fixture
def already_crushed():
    """A starless layer that arrives with part of it already at zero, as every
    real one does: `auto_levels` puts the black point at median - 3.5*MAD
    earlier in the pipeline, and 2-6% of a master's pixels land on it. The rest
    is mid-grey, so nothing but the seeded patch can trip the shadow mask."""
    starless = np.full((64, 64, 3), 0.40, np.float32)
    starless[:8, :8] = 0.0                  # 64 of 4096 pixels = 1.6%
    stars = np.zeros((64, 64, 3), np.float32)
    return (AstroImage(starless, is_linear=False, metadata={}),
            AstroImage(stars, is_linear=False, metadata={}))


def test_clipping_toggle_is_off_by_default(qtbot, split):
    dlg = StarlessLevelsDialog(*split)
    qtbot.addWidget(dlg)
    assert dlg.clip_check.isChecked() is False


def test_pre_existing_clipping_is_not_lit(qtbot, already_crushed):
    """Andreas: "the Starless Levels function in Nocturne almost always shows
    black level as crushed even to begin with", while Photoshop says there is
    room. It was reporting everything the pipeline had already crushed before
    the dialog opened.

    At the identity endpoints the tool has added nothing, so the overlay must be
    entirely dark — asserted as UNCHANGED-from-black, not merely different from
    some known-bad value."""
    dlg = StarlessLevelsDialog(*already_crushed)
    qtbot.addWidget(dlg)
    _size_preview(dlg, 64, 64)
    dlg.clip_check.setChecked(True)

    rgb = qimage_to_rgb8(dlg.preview._after_pane.pixmap().toImage())
    assert int(rgb.max()) == 0, (
        "the overlay lit pixels that were already at zero when the dialog "
        "opened — the baseline was not subtracted")


def test_clipping_the_tool_adds_is_still_lit(qtbot, already_crushed):
    """The other half: subtracting the baseline must not blind the overlay to
    what the two points actually do."""
    dlg = StarlessLevelsDialog(*already_crushed)
    qtbot.addWidget(dlg)
    _size_preview(dlg, 64, 64)
    dlg.clip_check.setChecked(True)
    dlg.handles.set_range(0.6, 1.0)         # crushes the 0.40 background
    dlg._render_preview()

    rgb = qimage_to_rgb8(dlg.preview._after_pane.pixmap().toImage())
    assert int(rgb.max()) == 255, "newly crushed pixels were not marked"


def test_the_total_is_still_reported_in_words(qtbot, already_crushed):
    """The main window's rule, matched here: the TOTAL is always what is
    reported — those shadows really are gone, and hiding that from someone
    editing an already-crushed file would be its own lie. Only the MARKS are
    restricted to what this tool added."""
    dlg = StarlessLevelsDialog(*already_crushed)
    qtbot.addWidget(dlg)
    _size_preview(dlg, 64, 64)
    dlg.clip_check.setChecked(True)
    assert dlg.clip_line.isVisible() or dlg.clip_line.text()
    assert "1.6% crushed" in dlg.clip_line.text(), dlg.clip_line.text()


def test_the_baseline_is_recaptured_when_the_crop_changes(qtbot, already_crushed):
    """`clip_masks` raises on a shape mismatch, so a baseline captured at fit
    cannot be reused against a zoomed crop. Getting this wrong makes the dialog
    raise the moment the user zooms with clipping on."""
    dlg = StarlessLevelsDialog(*already_crushed)
    qtbot.addWidget(dlg)
    _size_preview(dlg, 64, 64)
    dlg.clip_check.setChecked(True)
    fit_baseline = dlg._baseline
    dlg.preview.set_zoom(4.0)
    dlg._render_preview()                   # would raise on a stale baseline
    assert dlg._baseline is not fit_baseline
    assert dlg._baseline.shadow.shape[:2] != fit_baseline.shadow.shape[:2]


def test_a_handle_drag_does_not_recapture_the_baseline(qtbot, already_crushed):
    """The baseline is a second full-resolution compose. Recapturing it on every
    tick of a drag would double the cost of the one gesture this tool is for."""
    dlg = StarlessLevelsDialog(*already_crushed)
    qtbot.addWidget(dlg)
    _size_preview(dlg, 64, 64)
    dlg.clip_check.setChecked(True)
    captured = dlg._baseline
    dlg.handles.set_range(0.2, 0.9)
    dlg._render_preview()
    assert dlg._baseline is captured


# --- before/after compare -------------------------------------------------

def test_the_preview_is_a_compare_view_defaulting_to_off(qtbot, split):
    """Default Off, so nothing changes for someone who does not want it."""
    from nocturne.ui.compare_view import CompareView
    dlg = StarlessLevelsDialog(*split)
    qtbot.addWidget(dlg)
    assert isinstance(dlg.preview, CompareView)
    assert dlg.preview.mode() == "off"
    assert dlg.mode_box.currentText() == "Off"


def test_the_mode_control_drives_the_compare_view(qtbot, split):
    dlg = StarlessLevelsDialog(*split)
    qtbot.addWidget(dlg)
    for index, mode in ((1, "wipe"), (2, "side"), (0, "off")):
        dlg.mode_box.setCurrentIndex(index)
        assert dlg.preview.mode() == mode


def test_before_is_the_untouched_composite(qtbot, split):
    """"Before" is the tool doing nothing — black 0.0, white 1.0 — not the
    starless layer and not the current result."""
    starless, stars = split
    dlg = StarlessLevelsDialog(starless, stars)
    qtbot.addWidget(dlg)
    _size_preview(dlg, 200, 200)
    dlg.mode_box.setCurrentIndex(2)         # side by side
    dlg.handles.set_range(0.1, 0.7)
    dlg._render_preview()

    shown = qimage_to_rgb8(dlg.preview._before_img)
    expected = to_rgb8(starless_levels_layers(dlg._small_starless,
                                             dlg._small_stars, 0.0, 1.0))
    assert np.array_equal(shown, expected)


def test_off_mode_does_not_compose_a_before(qtbot, split):
    """Off shows one pane, so composing the untouched image would be a second
    full compose per tick for a picture nobody can see."""
    dlg = StarlessLevelsDialog(*split)
    qtbot.addWidget(dlg)
    dlg._render_preview()
    assert dlg.preview._before_img is None


def test_both_panes_share_one_zoom(qtbot, split):
    """His requirement: "if the user PTZ's the view both views needs to
    follow"."""
    dlg = StarlessLevelsDialog(*split)
    qtbot.addWidget(dlg)
    dlg.mode_box.setCurrentIndex(2)
    dlg.preview._before_pane.set_zoom(3.0)
    assert dlg.preview._after_pane.zoom_level() == pytest.approx(3.0)
    assert dlg.preview.zoom_level() == pytest.approx(3.0)


# --- the rest -------------------------------------------------------------

def test_apply_delivers_the_composed_image_and_the_values(qtbot, split):
    seen = {}
    dlg = StarlessLevelsDialog(*split,
                               on_apply=lambda img, vals: seen.update(img=img, vals=vals))
    qtbot.addWidget(dlg)
    dlg.handles.set_range(0.0, 0.6)
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
    dlg.handles.set_range(0.0, 0.4)
    dlg.compose()
    assert np.array_equal(stars.data, before)


def test_view_changes_queue_a_redraw(qtbot, split):
    """`CompareView.viewChanged` fires on wheel-zoom and drag-pan alike. Without
    it wired to the debounced re-render, the widget still tracks the gesture
    internally but the picture never updates -- reads as a frozen dialog, and
    finding the first clipped specks by zooming in IS this tool's workflow."""
    dlg = StarlessLevelsDialog(*split)
    qtbot.addWidget(dlg)
    with qtbot.waitSignal(dlg._timer.timeout, timeout=500, raising=True):
        dlg.preview.set_zoom(2.0)


def test_the_layout_is_the_house_pattern_with_a_full_width_histogram(qtbot, split):
    """Preview left at stretch 1, control column right capped at 340 — but the
    histogram spans the full width underneath both, because a histogram inside
    a 340 px column is exactly the "small histogram levels" he rejected.

    Read back from the real widgets, per CLAUDE.md."""
    from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout
    dlg = StarlessLevelsDialog(*split)
    qtbot.addWidget(dlg)
    root = dlg.layout()
    assert isinstance(root, QVBoxLayout)
    body = root.itemAt(0).layout()
    assert isinstance(body, QHBoxLayout), "the body is still a vertical stack"
    assert body.itemAt(0).widget() is dlg.preview
    assert body.stretch(0) == 1, "the preview does not take the spare width"
    column = body.itemAt(1).widget()
    assert column.maximumWidth() == 340
    # the histogram is NOT in the narrow column
    assert dlg.handles.parent() is dlg
    assert root.indexOf(dlg.handles) >= 0
    assert dlg.handles.minimumHeight() >= 200


def test_there_is_no_slider_left_holding_a_second_copy_of_the_values(qtbot, split):
    """Two controls for one value is where drift comes from — the sliders were
    removed rather than kept beside the handles."""
    dlg = StarlessLevelsDialog(*split)
    qtbot.addWidget(dlg)
    assert not hasattr(dlg, "black_slider")
    assert not hasattr(dlg, "white_slider")


def test_there_is_a_way_back_to_fit(qtbot, split):
    """Zoom and pan were wired but shipped none of the affordances CurvesDialog
    has for the same widget. Worse here than there: the mask covers the whole
    frame only at fit, so a user who scroll-zoomed by accident on a trackpad
    silently lost the whole-frame clip mask with no button to get back."""
    dlg = StarlessLevelsDialog(*split)
    qtbot.addWidget(dlg)
    dlg.zoom_in_btn.click()
    assert dlg.preview.zoom_level() > 1.0
    assert dlg.zoom_label.text() == "1.5x"
    dlg.zoom_out_btn.click()
    assert dlg.preview.zoom_level() == pytest.approx(1.0)
    dlg.preview.set_zoom(8.0)
    dlg.fit_btn.click()
    assert dlg.preview.zoom_level() == 1.0
    assert dlg.zoom_label.text() == "1.0x"


def test_ok_is_the_primary_action(qtbot, split):
    """As curves, star_spikes, trim, upscale, narrowband, colour balance,
    combine, batch, stack and haoiii all mark it."""
    from PySide6.QtWidgets import QDialogButtonBox
    dlg = StarlessLevelsDialog(*split)
    qtbot.addWidget(dlg)
    box = dlg.findChild(QDialogButtonBox)
    assert box.button(QDialogButtonBox.StandardButton.Ok).objectName() == "primary"


def test_resizing_re_renders_rather_than_rescaling(qtbot, split):
    """`CompareView` scales what it holds to fit its panes, smoothly. On the
    clipping overlay that re-dilutes the block-max — an isolated speck measured
    195, 111 or 55 instead of 255 — so the dialog re-renders at the new size
    instead of letting the stored image be stretched into it."""
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QResizeEvent
    from PySide6.QtWidgets import QApplication
    dlg = StarlessLevelsDialog(*split)
    qtbot.addWidget(dlg)
    dlg._timer.stop()
    # Sent directly: a hidden widget only POSTS its resize event, so resize()
    # alone proves nothing about the handler.
    QApplication.sendEvent(dlg, QResizeEvent(QSize(900, 700), dlg.size()))
    assert dlg._timer.isActive(), "a resize left the old picture stretched in place"


# --- geometry after layout: the round-2 review's two Criticals -------------

def _shown(qtbot, size=1200, w=1180, h=860, corner_speck=True):
    """A shown, laid-out dialog on a frame big enough for the defects to bite.

    Mid-grey field, never np.zeros: a black field is itself shadow-clipped and
    would light the overlay for the wrong reason.
    """
    starless = np.full((size, size, 3), 0.5, np.float32)
    if corner_speck:
        starless[20, 20] = 0.9          # the reviewer's repro speck
    stars = np.zeros((size, size, 3), np.float32)
    dlg = StarlessLevelsDialog(AstroImage(starless, is_linear=False, metadata={}),
                               AstroImage(stars, is_linear=False, metadata={}))
    qtbot.addWidget(dlg)
    dlg.resize(w, h)
    dlg.show()
    qtbot.waitExposed(dlg)
    return dlg


def test_side_by_side_panes_match_after_the_layout_settles(qtbot):
    """Andreas' headline request, broken on the first click. `_ZoomPreview` is
    a QLabel whose sizeHint is its PIXMAP's size, so with no stretch the
    QHBoxLayout split the width by the two separately-rendered pictures:
    measured at 1180x860 on a real gesture, after pane 460x572 against before
    328x572 — a 40% scale difference between two panes whose whole job is to be
    comparable — and, mid-switch, a 611x611 picture inside the 460 px pane,
    which QLabel AlignCenter centre-crops with no scrollbar and no
    indication."""
    dlg = _shown(qtbot)
    dlg.clip_check.setChecked(True)
    dlg.handles.set_range(0.0, 0.7)
    dlg.mode_box.setCurrentIndex(2)             # Side by side
    view = dlg.preview
    qtbot.waitUntil(
        lambda: view._before_pane.width() == view._after_pane.width(), timeout=2000)
    assert view._before_pane.size() == view._after_pane.size()
    for name, pane in (("before", view._before_pane), ("after", view._after_pane)):
        pm = pane.pixmap()
        assert pm.width() <= pane.width() and pm.height() <= pane.height(), (
            f"{name} pane {pane.width()}x{pane.height()} holds a "
            f"{pm.width()}x{pm.height()} pixmap — centre-cropped")


def test_a_corner_speck_survives_into_side_by_side(qtbot):
    """"Drag until the first specks appear" is what this tool is for, and a
    centre-crop is precisely what hides them: 75 px off each side put the
    reviewer's speck at (20, 20) of a 1200^2 frame off-screen entirely."""
    dlg = _shown(qtbot)
    dlg.handles.set_range(0.0, 0.7)
    dlg.clip_check.setChecked(True)
    dlg.mode_box.setCurrentIndex(2)
    view = dlg.preview
    qtbot.waitUntil(
        lambda: view._before_pane.width() == view._after_pane.width(), timeout=2000)
    dlg._render_preview()

    shown = qimage_to_rgb8(view._after_pane.pixmap().toImage())
    h, w = shown.shape[:2]
    corner = shown[:max(1, h // 8), :max(1, w // 8)]
    assert int(corner.max()) == 255, (
        "the clipped speck is not in the top-left corner of the after pane — "
        "the picture was centre-cropped on its way to the screen")


def test_wipe_with_clipping_composites_two_layers_of_the_same_size(qtbot):
    """`ImageView.set_compare` takes `_split_x` and the divider's max from the
    COMPARE pixmap, so a mismatch spreads the divider across twice the picture
    and shows the "before" half as a magnified top-left quadrant. Measured on a
    1200^2 frame: base 601x601 against compare 1200x1200."""
    dlg = _shown(qtbot, corner_speck=False)
    dlg.handles.set_range(0.0, 0.7)
    dlg.clip_check.setChecked(True)
    dlg.mode_box.setCurrentIndex(1)             # Wipe
    dlg._render_preview()

    wipe = dlg.preview._wipe_view
    base = wipe._item.pixmap()
    compare = wipe._compare_item.pixmap()
    assert not base.isNull() and not compare.isNull()
    assert (base.width(), base.height()) == (compare.width(), compare.height()), (
        f"base {base.width()}x{base.height()} against compare "
        f"{compare.width()}x{compare.height()} — the wipe divider spans the "
        "wrong picture and magnifies the before half")


# --- the zoom row tells the truth in all three modes -----------------------

def test_the_zoom_buttons_drive_the_wipe_view_in_wipe_mode(qtbot, split):
    """They drove the side/off pane's model in every mode. In Wipe the picture
    is an `ImageView` that does not use that model: Fit did nothing, the readout
    froze, and "+" re-cropped from a DETACHED pane's stale geometry. The help
    documents these three buttons, so it was false in one of three modes."""
    dlg = StarlessLevelsDialog(*split)
    qtbot.addWidget(dlg)
    dlg.resize(900, 700)
    dlg.show()
    qtbot.waitExposed(dlg)
    dlg.mode_box.setCurrentIndex(1)             # Wipe
    wipe = dlg.preview._wipe_view
    fitted = wipe.zoom()

    dlg.zoom_in_btn.click()
    assert wipe.zoom() > fitted, "the + button did not touch the wipe view"
    assert dlg.zoom_label.text() != "1.0x", "the readout ignored the zoom"

    dlg.fit_btn.click()
    assert wipe.zoom() == pytest.approx(fitted, rel=1e-3), "Fit did nothing"
    assert dlg.zoom_label.text() == "1.0x"


def test_the_zoom_row_readout_is_in_fit_units_in_every_mode(qtbot, split):
    """`ImageView` reports an absolute scale while `_ZoomPreview` counts from
    1.0 = fit, and one readout serves all three modes — so it must not mean two
    different things in two of them."""
    dlg = StarlessLevelsDialog(*split)
    qtbot.addWidget(dlg)
    dlg.resize(900, 700)
    dlg.show()
    qtbot.waitExposed(dlg)
    for index in (0, 1, 2):
        dlg.mode_box.setCurrentIndex(index)
        assert dlg.preview.display_zoom() == pytest.approx(1.0, abs=0.02), (
            f"mode {_MODES[index][1]} does not read 1.0x when nothing is zoomed")


# --- what the image ARRIVED with does not change when you zoom -------------

def test_the_already_clipped_figure_is_the_whole_frame_not_the_crop(qtbot):
    """The sentence says "before this tool touched it", which reads as a
    property of the file — but it came from a baseline captured on the CURRENT
    crop, so zooming into a dark corner took it from "2.1% crushed" to "40%
    crushed". The overlay answers "what am I adding here" and is right to
    follow the crop; this sentence answers "what did this image arrive with"."""
    size = 200
    starless = np.full((size, size, 3), 0.40, np.float32)
    starless[:20, :20] = 0.0                # 400 of 40000 pixels = 1.0%
    stars = np.zeros((size, size, 3), np.float32)
    dlg = StarlessLevelsDialog(AstroImage(starless, is_linear=False, metadata={}),
                               AstroImage(stars, is_linear=False, metadata={}))
    qtbot.addWidget(dlg)
    _size_preview(dlg, 200, 200)
    dlg.clip_check.setChecked(True)
    at_fit = dlg.clip_line.text()
    assert "1.0% crushed" in at_fit, at_fit

    # Into the crushed corner, which is 100% crushed on its own.
    dlg.preview.set_zoom(8.0)
    dlg.preview._after_pane._centre = [0.03, 0.03]
    dlg._render_preview()
    dlg._update_clip_line()
    assert dlg.clip_line.text() == at_fit, (
        "the reported figure followed the crop — it describes the file, not "
        "the corner being looked at")
    # ...while the per-crop baseline the OVERLAY uses did follow the crop:
    # nearly half of this crop is crushed, against 1.0% of the whole frame.
    assert dlg._baseline.shadow_frac > 0.3, dlg._baseline.shadow_frac


# --- precision: the readouts are editable, and are not a second copy -------

def test_the_readouts_can_be_typed_into_and_drive_the_handles(qtbot, split):
    """The removed `ResetSlider` pair gave arrow-key stepping at 0.001; a
    histogram handle is mouse-only at ~0.001 per pixel, so the rework took the
    precision away with the sliders — on the one tool where "the levels IS the
    key"."""
    dlg = StarlessLevelsDialog(*split)
    qtbot.addWidget(dlg)
    dlg.black_val.setValue(0.123)
    assert dlg.handles.range()[0] == pytest.approx(0.123)
    assert dlg.values()[0] == pytest.approx(0.123)
    dlg.white_val.setValue(0.750)
    assert dlg.handles.range() == pytest.approx((0.123, 0.750))
    assert dlg.black_val.singleStep() == pytest.approx(0.001)


def test_the_readouts_show_what_the_handles_took_not_what_was_asked(qtbot, split):
    """One source of truth. A box that kept a number the handles clamped away
    would be exactly the second copy removing the sliders was meant to end."""
    from nocturne.ui.range_handles import _MIN_SPAN
    dlg = StarlessLevelsDialog(*split)
    qtbot.addWidget(dlg)
    dlg.black_val.setValue(0.500)
    dlg.white_val.setValue(0.500)               # a span the handles will refuse
    lo, hi = dlg.values()
    assert hi - lo == pytest.approx(_MIN_SPAN)
    assert dlg.black_val.value() == pytest.approx(lo)
    assert dlg.white_val.value() == pytest.approx(hi)


def test_the_readouts_use_a_decimal_point_whatever_the_locale(qtbot, split):
    """Every other number in the app is formatted "{:.3f}" — the history step,
    the provenance report, the log line — so on a Swedish machine (Andreas')
    a locale-formatted box read "0,000" beside a history entry saying "0.000"
    for the same value."""
    dlg = StarlessLevelsDialog(*split)
    qtbot.addWidget(dlg)
    dlg.black_val.setValue(0.125)
    assert dlg.black_val.text() == "0.125", dlg.black_val.text()


# --- clip polarity: the ground follows the handle being worked -------------
#
# Andreas: "In photoshop the clipping overlay for black point is white and for
# the highlights its black." His first report of trouble ("the overlay does
# not seem to fill the entire image area") was a dark mark on a dark ground
# with a dark letterbox — exactly the black-point case on the old single
# black-ground view.

_POL_SIZE = 400   # exceeds CompareView's (320, 240) minimum pane size, so a
                  # pane resized to match it is neither up- nor down-scaled —
                  # `_clip_qimage` hands `clip_overlay` back its own pixels
                  # 1:1, and sampled coordinates below mean exactly what they
                  # say instead of landing wherever a NN rescale moved them.


@pytest.fixture
def polarity_split():
    """Mid-grey background, never zeros (CLAUDE.md — black is itself
    shadow-clipped). Three patches, each of which clips only once a handle is
    actually dragged past it, so a test can isolate "the black handle was
    worked" from "the white handle was worked" rather than having both ends
    clip at once. Each patch is 60x60 and sampled at its centre, well clear of
    its edges, so it survives being carried through `to_rgb8`/`QImage` whole."""
    starless = np.full((_POL_SIZE, _POL_SIZE, 3), 0.5, np.float32)
    starless[20:80, 20:80] = 0.10                     # crushes in ALL THREE channels
    starless[20:80, 120:180] = (0.10, 0.5, 0.5)       # crushes in RED alone
    starless[320:380, 320:380] = 0.95                  # blows once the white point drops
    stars = np.zeros((_POL_SIZE, _POL_SIZE, 3), np.float32)
    return (AstroImage(starless, is_linear=False, metadata={}),
            AstroImage(stars, is_linear=False, metadata={}))


# Sample points, each at a patch centre or in plain background — see the
# fixture above for which is which.
_BG, _ALL3, _RED_ONLY, _HI = (200, 200), (50, 50), (50, 150), (350, 350)


def _open_polarity_dialog(qtbot, polarity_split):
    dlg = StarlessLevelsDialog(*polarity_split)
    qtbot.addWidget(dlg)
    dlg.handles.resize(400, 200)
    _size_preview(dlg, _POL_SIZE, _POL_SIZE)
    return dlg


def test_before_a_drag_the_view_is_the_current_black_ground_view(qtbot, polarity_split):
    """Nothing changes for someone who toggles clipping without dragging
    first — the brief's explicit requirement."""
    dlg = _open_polarity_dialog(qtbot, polarity_split)
    assert dlg._clip_end() is None
    dlg.clip_check.setChecked(True)
    rgb = qimage_to_rgb8(dlg.preview._after_pane.pixmap().toImage())
    assert tuple(rgb[_BG]) == (0, 0, 0), \
        "an unclipped pixel must sit on the black ground before any drag"


def test_dragging_the_black_handle_gives_a_white_ground_shadow_view(qtbot, polarity_split):
    dlg = _open_polarity_dialog(qtbot, polarity_split)
    _drag(dlg.handles, 0.0, 0.3)            # black point up past the 0.10 patches
    dlg.clip_check.setChecked(True)
    dlg._render_preview()

    assert dlg._clip_end() == "lo"
    rgb = qimage_to_rgb8(dlg.preview._after_pane.pixmap().toImage())
    assert tuple(rgb[_BG]) == (255, 255, 255), "an unclipped pixel must be the white ground"
    assert tuple(rgb[_HI]) == (255, 255, 255), \
        "highlight clipping must not show on the shadow-only view"


def test_all_three_crushed_renders_black_not_white_on_the_white_ground(qtbot, polarity_split):
    """The one collision the brief calls out: white would be invisible against
    a white ground, so the pixel that is most completely gone has to read
    black there instead."""
    dlg = _open_polarity_dialog(qtbot, polarity_split)
    _drag(dlg.handles, 0.0, 0.3)
    dlg.clip_check.setChecked(True)
    dlg._render_preview()

    rgb = qimage_to_rgb8(dlg.preview._after_pane.pixmap().toImage())
    assert tuple(rgb[_ALL3]) == (0, 0, 0), \
        "an all-three-channels-crushed pixel must render BLACK on the white ground"


def test_a_single_channel_crushed_pixel_keeps_its_channel_colour(qtbot, polarity_split):
    dlg = _open_polarity_dialog(qtbot, polarity_split)
    _drag(dlg.handles, 0.0, 0.3)
    dlg.clip_check.setChecked(True)
    dlg._render_preview()

    rgb = qimage_to_rgb8(dlg.preview._after_pane.pixmap().toImage())
    r, g, b = (int(v) for v in rgb[_RED_ONLY])
    assert (r, g, b) == (CLIP_MARK_ON, CLIP_MARK_OFF, CLIP_MARK_OFF), \
        "a single-channel-crushed pixel must keep its own channel colour"


def test_dragging_the_white_handle_gives_a_black_ground_highlight_view(qtbot, polarity_split):
    dlg = _open_polarity_dialog(qtbot, polarity_split)
    _drag(dlg.handles, 1.0, 0.85)           # white point down past the 0.95 patch
    dlg.clip_check.setChecked(True)
    dlg._render_preview()

    assert dlg._clip_end() == "hi"
    rgb = qimage_to_rgb8(dlg.preview._after_pane.pixmap().toImage())
    assert tuple(rgb[_BG]) == (0, 0, 0), "an unclipped pixel must be the black ground"
    assert tuple(rgb[_HI]) == CLIP_HIGHLIGHT, "the blown patch must still mark amber"
    assert tuple(rgb[_ALL3]) == (0, 0, 0), \
        "shadow clipping must not show on the highlight-only view"


def test_the_label_states_which_end_is_showing(qtbot, polarity_split):
    """The user must not have to infer which end they are looking at."""
    dlg = _open_polarity_dialog(qtbot, polarity_split)
    dlg.clip_check.setChecked(True)
    assert "together" in dlg.clip_line.text().lower(), dlg.clip_line.text()

    _drag(dlg.handles, 0.0, 0.3)
    dlg._render_preview()
    assert "shadow" in dlg.clip_line.text().lower(), dlg.clip_line.text()
    assert "highlight" not in dlg.clip_line.text().lower(), dlg.clip_line.text()

    _drag(dlg.handles, 1.0, 0.85)
    dlg._render_preview()
    assert "highlight" in dlg.clip_line.text().lower(), dlg.clip_line.text()
    assert "shadow" not in dlg.clip_line.text().lower(), dlg.clip_line.text()


def _dlg(qtbot):
    starless = np.full((64, 64, 3), 0.5, np.float32)
    stars = np.zeros((64, 64, 3), np.float32)
    d = StarlessLevelsDialog(AstroImage(starless, is_linear=False, metadata={}),
                             AstroImage(stars, is_linear=False, metadata={}))
    qtbot.addWidget(d)
    return d


def test_typing_a_black_value_flips_the_clipping_ground_like_dragging_does(qtbot):
    """The spin boxes are the same control as the handles, offered to someone who
    would rather type 0.154 than find it with a mouse — so they must choose the
    clipping ground the same way. `RangeHandles.last_handle` ignores `set_range`
    on purpose (so a preset cannot pose as a drag), which is why the dialog
    tracks a typed end itself."""
    d = _dlg(qtbot)
    assert d._clip_end() is None            # nothing worked yet
    d.black_val.setValue(0.2)
    assert d._clip_end() == "lo"
    d.white_val.setValue(0.8)
    assert d._clip_end() == "hi"


def test_a_handle_drag_supersedes_a_typed_end(qtbot):
    """Most recent wins. Without this the first typed value would pin the ground
    for the rest of the session and dragging a handle could not change it."""
    d = _dlg(qtbot)
    d.black_val.setValue(0.2)
    assert d._clip_end() == "lo"
    d.handles._last_handle = "hi"           # as a real drag leaves it
    d._on_range_changed(*d.handles.range())
    assert d._clip_end() == "hi"


def test_reset_forgets_which_end_was_being_worked(qtbot):
    d = _dlg(qtbot)
    d.black_val.setValue(0.2)
    assert d._clip_end() == "lo"
    d.reset()
    assert d._clip_end() is None


def test_side_by_side_panes_are_not_the_same_picture(qtbot):
    """Before is the untouched composite, After the current one — so with
    non-identity endpoints the two panes must differ.

    Andreas could not see a difference side by side and asked whether they were
    showing the same thing. They were not (measured: mean 88.8 against 98.8 at
    black 0.008 / white 0.887 — a 1.13x lift is simply hard to see across a gap).
    This pins it so they can never silently BECOME the same picture.
    """
    rng = np.random.default_rng(0)
    starless = np.clip(rng.normal(0.35, 0.12, (200, 200, 3)), 0, 1).astype(np.float32)
    stars = np.zeros((200, 200, 3), np.float32)
    dlg = StarlessLevelsDialog(AstroImage(starless, is_linear=False, metadata={}),
                               AstroImage(stars, is_linear=False, metadata={}))
    qtbot.addWidget(dlg)
    dlg.resize(900, 700)
    dlg.show()
    qtbot.waitExposed(dlg)
    dlg.preview.set_mode("side")
    dlg.black_val.setValue(0.10)
    dlg.white_val.setValue(0.70)
    dlg._render_preview()

    before = dlg.preview._before_pane.pixmap()
    after = dlg.preview._after_pane.pixmap()
    assert not before.isNull() and not after.isNull()
    b = qimage_to_rgb8(before.toImage().convertToFormat(QImage.Format.Format_RGB888))
    a = qimage_to_rgb8(after.toImage().convertToFormat(QImage.Format.Format_RGB888))
    assert b.shape == a.shape, "the two panes must be drawn at the same scale"
    assert not np.array_equal(a, b), "before and after are the same picture"
    assert a.mean() > b.mean(), "pulling the white point in must lighten the after"
