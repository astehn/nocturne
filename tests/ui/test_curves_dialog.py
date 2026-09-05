"""The large curve editor.

Exists because the inline one is 336 x 240 in the real app and the right pane is
a fixed 400 px, so it cannot be made wider — Andreas: "small and fiddly ...
difficult to see and control what you are actually doing."
"""
import numpy as np
import pytest
from PySide6.QtGui import qGray

pytest.importorskip("PySide6")
from nocturne.core.curves import apply_curve, apply_curves  # noqa: E402
from nocturne.core.image import AstroImage  # noqa: E402
from nocturne.ui.curves_dialog import PRESETS, CurvesDialog, _downscale  # noqa: E402


def _base(h=400, w=600):
    rng = np.random.default_rng(0)
    a = (rng.random((h, w, 3)).astype(np.float32) * 0.3 + 0.12)
    a[:20] = 0.85                       # something bright, so presets have a top end
    return AstroImage(np.clip(a, 0, 1), is_linear=False, metadata={})


def test_the_preview_equals_what_apply_commits(qtbot):
    """The project's central rule. compose() is the ONE path, so a preview can
    never show something Apply would not produce."""
    dlg = CurvesDialog(_base()); qtbot.addWidget(dlg)
    dlg.editor.set_points([(0.0, 0.0), (0.4, 0.28), (1.0, 1.0)])
    committed = []
    dlg._on_apply = committed.append
    shown = dlg.compose(dlg._base)
    dlg._apply()
    assert committed, "Apply did not hand the curves back"
    # apply_curveS: since 2026-09-05 the dialog commits the whole MATRIX of
    # curves (channel x hue range), not one list of points. The rule under test
    # is unchanged — the preview must equal what Apply produces.
    assert np.array_equal(apply_curves(dlg._base, committed[0]).data, shown.data)


def test_every_preset_reaches_the_editor(qtbot):
    """Buttons wired to nothing are a classic silent failure — the curve simply
    does not move and the user assumes the preset does nothing."""
    dlg = CurvesDialog(_base()); qtbot.addWidget(dlg)
    for label, _fn in PRESETS:
        dlg.editor.set_points([(0.0, 0.0), (1.0, 1.0)])
        dlg.preset_buttons[label].click()
        pts = dlg.points()
        assert pts != [(0.0, 0.0), (1.0, 1.0)], f"{label} left the curve unchanged"


def test_presets_are_measured_from_the_full_image_not_the_preview(qtbot):
    """The presets read percentiles. A decimated copy has different statistics,
    so a preset computed from the preview would commit a curve the user never
    saw derived."""
    big = _base(h=1200, w=1600)
    dlg = CurvesDialog(big); qtbot.addWidget(dlg)
    assert dlg._small.data.shape != big.data.shape, "fixture too small to decimate"
    from nocturne.core.curves import lift_faint_points
    dlg.preset_buttons["Lift faint detail"].click()
    assert dlg.points() == lift_faint_points(big.data)


def test_reset_returns_the_identity_curve(qtbot):
    dlg = CurvesDialog(_base()); qtbot.addWidget(dlg)
    dlg.preset_buttons["Add contrast"].click()
    assert dlg.points() != [(0.0, 0.0), (1.0, 1.0)]
    dlg.reset_btn.click()
    assert dlg.points() == [(0.0, 0.0), (1.0, 1.0)]


def test_it_opens_on_the_curve_the_inline_editor_already_had(qtbot):
    """Two surfaces, one state. Opening the dialog must not silently discard a
    curve the user had already shaped in the pane."""
    pts = [(0.0, 0.0), (0.3, 0.42), (1.0, 1.0)]
    dlg = CurvesDialog(_base(), points=pts); qtbot.addWidget(dlg)
    assert dlg.points() == pts


def test_the_preview_is_area_averaged_not_strided(qtbot):
    """Striding throws stars away: measured on three hundred synthetic stars, a
    strided preview lost two hundred and fifty-three of them. A curves preview
    that loses the stars is showing the wrong picture.

    The stars are placed OFF the stride phase deliberately. A first version put
    them every 7 px against a stride of 4, which by coincidence sampled about
    the same FRACTION of stars as of pixels — so the mean barely moved and the
    test passed with striding in place. Verified by mutation: at this offset a
    strided preview contains no stars at all.
    """
    a = np.zeros((400, 400, 3), np.float32)
    a[2::4, 2::4] = 1.0                    # stride 4 samples 0,4,8… — never these
    img = AstroImage(a, is_linear=False, metadata={})
    small = _downscale(img, max_edge=100)  # 400 // 100 -> step 4
    assert small.data.shape[0] < 400
    assert small.data.mean() > 0, "every star was thrown away — this is striding"
    assert abs(small.data.mean() - a.mean()) < a.mean() * 0.1, (
        f"flux not preserved: {small.data.mean():.5f} vs {a.mean():.5f}")


def test_the_editor_gets_the_larger_share_of_the_dialog(qtbot):
    """The entire point of the dialog is working area, so the curve must get the
    bulk of it rather than being squeezed by the preview.

    Asserted as a RATIO, not as pixels: the dialog now shrinks to fit small
    screens, so an absolute size is only true on a big display. An earlier
    version asserted >= 500 px and broke the moment the minimums came down for
    the laptop case.
    """
    dlg = CurvesDialog(_base()); qtbot.addWidget(dlg)
    dlg.show(); qtbot.waitExposed(dlg)
    assert dlg.editor.width() > dlg.preview_label.width(), (
        dlg.editor.width(), dlg.preview_label.width())


def test_fit_to_screen_clamps_to_a_small_display():
    """Unit-test the clamp directly, with the sizes a MacBook Air reports.

    The composed dialog cannot be measured for this in the suite: it runs
    headless, where Qt substitutes fonts and reports different size hints than
    the real app — the same trap that let a pane-width bug survive three
    measurements. So assert the arithmetic, and keep the cocoa-measured figure
    in the docstring: with these minimums the real dialog's minimum is 765 x 568,
    inside the ~1280 x 750 an Air leaves after the menu bar.
    """
    from nocturne.ui import curves_dialog as cd

    class _Screen:
        def __init__(self, w, h): self._w, self._h = w, h
        def availableGeometry(self):
            class G:
                def __init__(s, w, h): s._w, s._h = w, h
                def width(s): return s._w
                def height(s): return s._h
            return G(self._w, self._h)

    import unittest.mock as mock
    with mock.patch.object(cd.QApplication, "primaryScreen",
                           staticmethod(lambda: _Screen(1280, 800))):
        w, h = cd._fit_to_screen(1180, 760)
    assert w <= 1280 and h <= 750, (w, h)

    with mock.patch.object(cd.QApplication, "primaryScreen",
                           staticmethod(lambda: _Screen(3840, 2160))):
        assert cd._fit_to_screen(1180, 760) == (1180, 760), "a big screen must not shrink it"


# Everything around the editor: labels, the preset grid, the button box and the
# window frame. MEASURED under cocoa, which is the only place the real figure
# exists — with _EDITOR_MIN at 360 the dialog's minimum came to 765 x 568, so the
# chrome is 208 px tall and 405 px wide beside the editor. Rounded up for
# headroom, because a font change moves it.
_CHROME_H = 230
_CHROME_W = 430


def test_the_minimums_leave_room_on_a_1280x800_laptop():
    """Guards the SIZE CONSTANTS, not the composed size hint.

    The composed hint cannot be trusted here: the suite runs headless, where Qt
    substitutes fonts and reported a passing figure while cocoa measured 768 —
    a dialog whose minimum was TALLER than an Air's screen, so it could not be
    resized to fit at all. A test that reads the hint therefore proves nothing,
    and a mutation putting the oversized minimum back sailed through it.

    So do the arithmetic on the constants instead, with a measured allowance for
    the chrome. This DOES fail when the minimum goes back up.
    """
    from nocturne.ui import curves_dialog as cd
    assert cd._EDITOR_MIN + _CHROME_H <= 750, (
        f"editor minimum {cd._EDITOR_MIN} + chrome {_CHROME_H} exceeds the 750 px "
        "a 1280x800 laptop leaves after the menu bar")
    assert cd._EDITOR_MIN + cd._PREVIEW_MIN_W + _CHROME_W <= 1280, (
        f"{cd._EDITOR_MIN} + {cd._PREVIEW_MIN_W} + {_CHROME_W} exceeds 1280 px")


def test_it_fits_a_1280x800_laptop(qtbot):
    """The floor from the small-screen work: a 1280 x 800 MacBook Air, which
    leaves roughly 1280 x 750 usable after the menu bar.

    The first version's MINIMUM was 1118 x 768 — taller than the screen, so it
    could not even be resized to fit. A dialog that cannot open on the machine
    it is aimed at is worse than no dialog. Andreas raised this while it was
    being built; it would otherwise have shipped and been discovered on the Air.
    """
    dlg = CurvesDialog(_base()); qtbot.addWidget(dlg)
    h = dlg.minimumSizeHint()
    assert h.width() <= 1280, f"minimum width {h.width()} exceeds a 1280 px screen"
    assert h.height() <= 750, f"minimum height {h.height()} exceeds 750 usable px"


def test_it_opens_no_larger_than_the_screen_it_is_on(qtbot):
    """Opening bigger than the display puts the buttons off the bottom edge,
    where the primary action lives."""
    from PySide6.QtWidgets import QApplication
    dlg = CurvesDialog(_base()); qtbot.addWidget(dlg)
    screen = QApplication.primaryScreen()
    if screen is None:
        pytest.skip("no screen")
    avail = screen.availableGeometry()
    assert dlg.width() <= avail.width(), (dlg.width(), avail.width())
    assert dlg.height() <= avail.height(), (dlg.height(), avail.height())


def test_the_editor_stays_usefully_bigger_than_the_inline_one_even_when_small(qtbot):
    """Shrinking to fit a laptop must not shrink it to pointlessness — the
    inline plot is 304 px square, so the dialog has to beat that clearly or
    there is no reason to open it."""
    dlg = CurvesDialog(_base()); qtbot.addWidget(dlg)
    assert dlg.editor.minimumWidth() >= 340, dlg.editor.minimumWidth()
    assert dlg.editor.minimumHeight() >= 340, dlg.editor.minimumHeight()


def test_the_dialog_shows_the_data_behind_the_curve(qtbot):
    """It opened as an unlabelled black box: the inline editor has always been
    fed a histogram and the dialog simply never was."""
    dlg = CurvesDialog(_base()); qtbot.addWidget(dlg)
    assert dlg.editor._hist is not None, "no histogram behind the curve"
    assert float(np.max(dlg.editor._hist)) > 0, "the histogram is empty"


# --- the curve matrix in the dialog ------------------------------------------

_BOOST = [(0.0, 0.0), (0.5, 0.7), (1.0, 1.0)]
_DIP = [(0.0, 0.0), (0.5, 0.3), (1.0, 1.0)]


def test_switching_channel_keeps_the_curve_you_just_drew(qtbot):
    """The first thing anyone does with two selectors is change one. If the edit
    lived only in the editor widget it would evaporate at that moment, and the
    user would have no way to know it had."""
    from nocturne.core.curves import curve_key
    dlg = CurvesDialog(_base()); qtbot.addWidget(dlg)
    dlg.editor.set_points(_BOOST)
    dlg._set_channel("r")
    dlg.editor.set_points(_DIP)
    dlg._set_channel("rgb")
    assert list(dlg.editor.points()) == _BOOST, "the RGB curve came back wrong"
    curves = dlg.curves()
    assert curves[curve_key("rgb", "all")] == _BOOST
    assert curves[curve_key("r", "all")] == _DIP


def test_the_target_selects_a_separate_slot_from_the_same_channel(qtbot):
    from nocturne.core.curves import curve_key
    dlg = CurvesDialog(_base()); qtbot.addWidget(dlg)
    dlg._set_channel("s")
    dlg.editor.set_points(_BOOST)                     # S / all colours
    dlg.target_box.setCurrentIndex(list(range(dlg.target_box.count()))[
        [dlg.target_box.itemData(i) for i in range(dlg.target_box.count())].index("reds")])
    assert list(dlg.editor.points()) == [(0.0, 0.0), (1.0, 1.0)], \
        "a fresh slot must start at identity, not inherit the last one"
    dlg.editor.set_points(_DIP)                       # S / reds
    curves = dlg.curves()
    assert curves[curve_key("s", "all")] == _BOOST
    assert curves[curve_key("s", "reds")] == _DIP


def test_the_active_line_names_what_is_actually_shaping_the_picture(qtbot):
    dlg = CurvesDialog(_base()); qtbot.addWidget(dlg)
    assert "none" in dlg.active_label.text().lower()
    dlg.editor.set_points(_BOOST)
    dlg._set_channel("b")
    dlg.editor.set_points(_DIP)
    text = dlg.active_label.text()
    assert "RGB" in text and "B" in text, text


def test_reset_this_curve_leaves_the_others_alone(qtbot):
    from nocturne.core.curves import curve_key
    dlg = CurvesDialog(_base()); qtbot.addWidget(dlg)
    dlg.editor.set_points(_BOOST)
    dlg._set_channel("g")
    dlg.editor.set_points(_DIP)
    dlg._reset_slot()
    curves = dlg.curves()
    assert curve_key("g", "all") not in curves
    assert curves[curve_key("rgb", "all")] == _BOOST, "Reset hit the wrong curve"
    dlg._reset_all()
    assert dlg.curves() == {}


def test_the_dialog_opens_on_a_matrix_it_was_given(qtbot):
    """It is handed the whole matrix by main_window, and must not drop the slots
    it is not currently showing."""
    from nocturne.core.curves import curve_key
    given = {curve_key("rgb", "all"): _BOOST, curve_key("s", "reds"): _DIP}
    dlg = CurvesDialog(_base(), curves=given); qtbot.addWidget(dlg)
    assert list(dlg.editor.points()) == _BOOST
    assert dlg.curves() == given


def test_the_large_editor_is_a_movable_window_not_a_sheet(qtbot, tmp_path):
    """macOS draws a WINDOW-modal dialog with a parent as a sheet: glued to the
    parent's title bar and immovable. That is right for a file picker and wrong
    for an editor you work in — Andreas could resize this one but not place it
    (2026-09-05, while grading a 14004 px mosaic)."""
    from PySide6.QtCore import Qt
    from nocturne.ui import curves_dialog as cd
    seen = {}

    class _Stub:
        def __init__(self, *a, **k): pass
        def setWindowModality(self, m): seen["mode"] = m
        def exec(self): return 0

    import tests.ui.test_main_window as tmw
    monkey = pytest.MonkeyPatch()
    monkey.setattr("nocturne.ui.curves_dialog.CurvesDialog", _Stub)
    win = tmw._window(qtbot, tmp_path)
    win.open_fits(tmw._make_fits(tmp_path))
    for _ in range(20):
        if win.current_stage_id() == "curves":
            break
        win.go_next()
    win._panel.expand_btn.click()
    monkey.undo()
    assert seen.get("mode") == Qt.WindowModality.ApplicationModal, seen


# --- the zoomable preview ----------------------------------------------------

def _detailed_base(side=1400):
    """A dark frame with a few single-pixel stars. At fit these are averaged
    away; at 1:1 they are the whole point."""
    data = np.full((side, side, 3), 0.10, np.float32)
    for y, x in ((700, 700), (702, 706), (698, 694)):
        data[y, x] = 0.95
    return AstroImage(data, is_linear=False, metadata={})


def test_fit_shows_the_whole_image_and_zoom_shows_a_part_of_it(qtbot):
    dlg = CurvesDialog(_detailed_base()); qtbot.addWidget(dlg)
    dlg.resize(1100, 700)
    view = dlg.preview_label
    shape = dlg._base.data.shape
    assert view.visible_rect(shape) == (0, 0, shape[1], shape[0]), "fit must show it all"
    view.set_zoom(8.0)
    x0, y0, x1, y1 = view.visible_rect(shape)
    assert (x1 - x0) < shape[1] and (y1 - y0) < shape[0], "zoom must narrow the view"
    assert 0 <= x0 and x1 <= shape[1] and 0 <= y0 and y1 <= shape[0], "stay inside"


def test_panning_to_a_corner_cannot_walk_off_the_image(qtbot):
    dlg = CurvesDialog(_detailed_base()); qtbot.addWidget(dlg)
    dlg.resize(1100, 700)
    view = dlg.preview_label
    view.set_zoom(6.0)
    # Deliberately NOT calling _clamp here: visible_rect is what actually keeps
    # the crop inside the array, and a test that clamps first cannot tell
    # whether it does. _clamp is belt and braces, covered separately below.
    view._centre = [-5.0, 9.0]          # as if dragged far past the edge
    x0, y0, x1, y1 = view.visible_rect(dlg._base.data.shape)
    h, w = dlg._base.data.shape[:2]
    assert 0 <= x0 < x1 <= w and 0 <= y0 < y1 <= h, (x0, y0, x1, y1)


def test_zooming_in_reaches_the_full_resolution_pixels(qtbot):
    """The whole reason this exists. The decimated copy averages a single-pixel
    star down to near the background; the base still has it. If a zoomed render
    still came from `_small`, the star would stay washed out however far you
    zoomed — which is the state Andreas reported on his 14004 px mosaic.
    """
    dlg = CurvesDialog(_detailed_base()); qtbot.addWidget(dlg)
    dlg.resize(1100, 700)
    assert float(dlg._small.data.max()) < 0.9, (
        "fixture is wrong: the decimated copy must LOSE the star, or this "
        "test cannot tell the two sources apart")

    dlg.preview_label.set_zoom(12.0)
    dlg.preview_label._centre = [0.5, 0.5]
    dlg._render()

    # Look at what is actually ON SCREEN, not at what the source could have
    # been. The first version of this test asserted only that a crop of the base
    # contained the star and that _render did not raise — both true even when
    # the render still came from the decimated copy, so it proved nothing.
    img = dlg.preview_label.pixmap().toImage()
    brightest = max(qGray(img.pixel(x, y))
                    for y in range(0, img.height(), 2)
                    for x in range(0, img.width(), 2))
    assert brightest > 200, (
        f"brightest pixel on screen is {brightest}: the zoomed preview is still "
        "being rendered from the decimated copy")
    assert dlg.zoom_label.text().startswith("12"), dlg.zoom_label.text()


def test_the_zoom_buttons_and_fit_agree_with_the_view(qtbot):
    dlg = CurvesDialog(_detailed_base()); qtbot.addWidget(dlg)
    dlg.zoom_in_btn.click()
    assert dlg.preview_label.zoom_level() > 1.0
    dlg.fit_btn.click()
    assert dlg.preview_label.zoom_level() == 1.0
    dlg.zoom_out_btn.click()
    assert dlg.preview_label.zoom_level() == 1.0, "fit is the floor; never smaller"


def test_the_centre_clamp_keeps_the_view_anchor_on_the_image(qtbot):
    """Belt and braces beside visible_rect's own clamping: a centre outside
    [0,1] is meaningless, and letting it drift means a later drag starts from
    somewhere the image is not."""
    dlg = CurvesDialog(_detailed_base()); qtbot.addWidget(dlg)
    view = dlg.preview_label
    view._centre = [-3.0, 7.5]
    view._clamp()
    assert view._centre == [0.0, 1.0], view._centre
