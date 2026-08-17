import numpy as np
import pytest

pytest.importorskip("PySide6")
from nocturne.core.image import AstroImage  # noqa: E402
from nocturne.settings import Settings  # noqa: E402
from nocturne.ui.color_balance_dialog import ColorBalanceDialog  # noqa: E402


def _img(h=64, w=64):
    """A galaxy-ish frame: dark sky with noise, mid-bright arms, a bright core —
    a flat fixture would make every band preset land in the same place."""
    rng = np.random.default_rng(0)
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    r = np.hypot(y - h / 2, x - w / 2) / (h / 2)
    lum = np.clip(rng.normal(0.20, 0.03, (h, w)).astype(np.float32)
                  + 0.75 * np.exp(-6.0 * r * r), 0.0, 1.0)
    return AstroImage(np.repeat(lum[:, :, None], 3, axis=2).astype(np.float32),
                      is_linear=False)


def _layers(h=64, w=64):
    """(base, starless, stars) where base is the screened recombination.

    The starless layer must genuinely DIFFER from the base and the stars must be
    real, or the fixture cannot express the faults these tests exist to catch: a
    mutation that adjusts the base instead of the starless layer, and one that
    drops the stars from the preview, both passed against an earlier fixture
    that set starless = base and stars = zeros.
    """
    from nocturne.core.narrowband import screen
    starless = _img(h, w)
    stars_data = np.zeros_like(starless.data)
    rng = np.random.default_rng(1)
    for _ in range(12):
        y, x = int(rng.integers(4, h - 4)), int(rng.integers(4, w - 4))
        stars_data[y - 2:y + 2, x - 2:x + 2] = 0.85
    stars = AstroImage(stars_data, is_linear=False)
    base = AstroImage(screen(starless.data, stars_data), is_linear=False)
    return base, starless, stars


def _dlg(qtbot, on_apply=None):
    base, starless, stars = _layers()
    d = ColorBalanceDialog(Settings(), base, on_apply=on_apply,
                           starless=starless, stars=stars)
    qtbot.addWidget(d)
    d.show()                        # showEvent seeds the split and the band
    return d


def test_opens_with_a_neutral_adjustment(qtbot):
    d = _dlg(qtbot)
    b = d.balance()
    assert b.is_neutral(), f"opened with an adjustment already set: {b}"
    assert b.preserve_lum is True and b.strength == 1.0


def test_a_neutral_adjustment_leaves_the_image_UNCHANGED(qtbot):
    """Opening the tool and applying without touching a slider must not alter
    the picture. Captured before, compared after.

    Not bit-exact, and deliberately so: recombining the layers goes through the
    screen blend, and 1-(1-x)*(1-0) is not exactly x in float32 — measured drift
    is 3e-8, about a ten-thousandth of one 8-bit level. apply_balance itself IS
    bit-exact for a neutral balance; that is asserted in test_color_balance.py.
    """
    d = _dlg(qtbot)
    before = d._base.data.copy()          # the recombined original, not the starless layer
    after = d.compose().data
    assert np.allclose(after, before, atol=1e-6), (
        f"max change {np.max(np.abs(after - before)):.2e}")


def test_a_preset_moves_the_handles_off_the_default(qtbot):
    d = _dlg(qtbot)
    d.preset_box.setCurrentText("Object, not the core")
    lo, hi = d.handles.range()
    assert lo > 0.0 and hi < 1.0, f"band ({lo}, {hi}) is still the whole range"


def test_a_preset_sits_above_the_sky(qtbot):
    """The failure that was found by rendering the real M 31: fixed bounds put
    the band under the sky and selected everything but the core."""
    d = _dlg(qtbot)
    d.preset_box.setCurrentText("Object, not the core")
    lo, _hi = d.handles.range()
    lum = d._starless.data.mean(axis=2)
    assert lo > float(np.median(lum)), "the band starts at or below the sky"


def test_the_handles_stay_adjustable_after_a_preset(qtbot):
    """A preset is a starting point, not a mode — the Stretch idiom."""
    d = _dlg(qtbot)
    d.preset_box.setCurrentText("Bright areas")
    d.handles.set_range(0.11, 0.93)
    assert d.handles.range() == (pytest.approx(0.11), pytest.approx(0.93))


def test_whole_image_covers_the_whole_range(qtbot):
    d = _dlg(qtbot)
    d.preset_box.setCurrentText("Whole image")
    assert d.handles.range() == (0.0, 1.0)


def test_the_stars_layer_is_returned_UNCHANGED(qtbot):
    """The tool works on the starless layer and screens the untouched stars back.
    The fixture carries a real star, or the mutation that adjusts the whole image
    would have nothing to damage and the guard would prove nothing."""
    base, starless, stars = _layers()
    before = stars.data.copy()
    d = ColorBalanceDialog(Settings(), base, starless=starless, stars=stars)
    qtbot.addWidget(d)
    d.show()
    d.set_balance_for_test(blue=1.0, red=-1.0, strength=1.0)
    d.preset_box.setCurrentText("Whole image")
    d.compose()
    assert np.array_equal(stars.data, before), "the stars layer was mutated"


def test_the_stars_are_screened_back_not_adjusted(qtbot):
    """Stronger than 'the array was not mutated': the star's colour in the RESULT
    must match what screening an untouched star gives, not a shifted one."""
    from nocturne.core.narrowband import screen
    base, starless, stars = _layers()
    stars_data = stars.data.copy()
    d = ColorBalanceDialog(Settings(), base, starless=starless, stars=stars)
    qtbot.addWidget(d)
    d.show()
    d.set_balance_for_test(blue=1.0, red=-1.0, strength=1.0)
    d.preset_box.setCurrentText("Whole image")
    out = d.compose().data
    # what the result MUST be: the starless layer adjusted, with the stars
    # exactly as they arrived screened on top. Computed from the core functions
    # rather than a test-only method on the dialog.
    from nocturne.core.color_balance import apply_balance
    adjusted = apply_balance(starless, d.balance(), d.mask_for(starless)).data
    expected = screen(adjusted, np.clip(stars_data, 0, 1))
    assert np.allclose(out, expected, atol=1e-6)


def test_showing_the_mask_puts_the_mask_on_the_preview(qtbot):
    """The background-gradient-view lesson: a mask you cannot see is a mask you
    cannot trust, and inspecting it is part of the workflow this replaces."""
    d = _dlg(qtbot)
    d.preset_box.setCurrentText("Object, not the core")
    d.show_mask_check.setChecked(True)
    shown = d.preview_image().data
    assert shown.min() >= 0.0 and shown.max() <= 1.0
    assert shown.std() > 0.01, "the mask preview is flat"
    assert np.allclose(shown[..., 0], shown[..., 1]), "the mask should be greyscale"


def test_unticking_show_the_mask_returns_to_the_picture(qtbot):
    d = _dlg(qtbot)
    d.show_mask_check.setChecked(True)
    d.show_mask_check.setChecked(False)
    shown = d.preview_image().data
    assert not np.allclose(shown, d.mask_for(d._prev_starless)[:, :, None])


def test_the_option_dict_round_trips_every_field(qtbot):
    seen = {}
    d = _dlg(qtbot, on_apply=lambda result, opts: seen.update(opts))
    d.set_balance_for_test(blue=0.5, tone="highlights", strength=0.8)
    d.handles.set_range(0.2, 0.9)
    d._apply()
    qtbot.waitUntil(lambda: bool(seen), timeout=5000)   # Apply composes off-thread
    for key in ("shadows", "midtones", "highlights", "preserve_lum",
                "strength", "lo", "hi", "feather", "invert"):
        assert key in seen, f"{key} missing from the recorded option"
    assert seen["highlights"] == pytest.approx([0.0, 0.0, 0.5])
    assert seen["lo"] == pytest.approx(0.2)
    assert seen["hi"] == pytest.approx(0.9)
    assert seen["strength"] == pytest.approx(0.8)


def test_apply_hands_over_the_same_image_the_preview_showed(qtbot):
    """WYSIWYG. Preview and Apply differ only in resolution, so compare the
    preview against compose() on the SAME input — one code path or neither."""
    got = {}
    d = _dlg(qtbot, on_apply=lambda result, opts: got.update(result=result))
    d.set_balance_for_test(blue=0.4, red=-0.3, strength=0.9)
    d.preset_box.setCurrentText("Object, not the core")
    shown = d.preview_image().data
    d._apply()
    qtbot.waitUntil(lambda: "result" in got, timeout=5000)
    expected = d.compose(d._prev_starless, d._prev_stars).data
    assert np.allclose(shown, expected, atol=1e-6)
    assert got["result"].data.shape == d._starless.data.shape


def test_reset_returns_every_control_to_neutral(qtbot):
    d = _dlg(qtbot)
    d.set_balance_for_test(blue=0.9, red=-0.9, tone="shadows", strength=0.3)
    d.preset_box.setCurrentText("Bright areas")
    d.show_mask_check.setChecked(True)
    d.reset()
    b = d.balance()
    assert b.is_neutral(), f"reset left an adjustment behind: {b}"
    assert b.strength == 1.0
    assert not d.show_mask_check.isChecked()
    assert d.handles.range() == (0.0, 1.0)


def test_the_band_actually_limits_where_the_colour_moves(qtbot):
    """The mask has to reach compose(), not merely be computed.

    This test did not exist at first, and its absence let a mutation that
    dropped the mask from compose() pass the ENTIRE dialog suite — the tool
    would have recoloured the sky along with the object and nothing would have
    said so.
    """
    d = _dlg(qtbot)
    d.preset_box.setCurrentText("Object, not the core")
    before = d._base.data.copy()
    d.set_balance_for_test(blue=1.0, red=-1.0, strength=1.0)
    after = d.compose().data

    # Asserted against the MASK, not against raw luminance. The mask blurs the
    # luminance by design, so it bleeds a pixel or two past the object — picking
    # "sky" from the unblurred values flags that bleed as a fault when it is the
    # feature working.
    mask = d.mask_for(d._starless)
    untouched, selected = mask < 1e-6, mask > 0.9
    assert untouched.any() and selected.any(), "the fixture exercises only one side"
    assert np.allclose(after[untouched], before[untouched], atol=1e-6), (
        "pixels the mask excluded were recoloured")
    assert not np.allclose(after[selected], before[selected], atol=1e-4), (
        "pixels the mask selected did not move")


def test_apply_does_not_block_the_ui_thread(qtbot):
    """Apply on the 39.5 Mpx mosaic takes 3.4 s with a real mask and 7.8 s with
    the whole frame selected. Running that on the UI thread freezes the window
    with no feedback — which in this app has previously been indistinguishable
    from the hang that cost a session.

    Asserted structurally: the heavy work goes through the dialog's thread pool,
    and the button is disabled meanwhile so it cannot be pressed twice.
    """
    calls = []
    d = _dlg(qtbot, on_apply=lambda result, opts: calls.append(opts))
    d.set_balance_for_test(blue=0.5)

    submitted = []
    d._pool = type("P", (), {"start": lambda _self, w: submitted.append(w)})()
    d._apply()

    assert submitted, "Apply ran the composition on the UI thread"
    assert not d.apply_btn.isEnabled(), "Apply stayed clickable while working"
    assert calls == [], "on_apply fired before the work finished"


def test_apply_still_delivers_the_result_when_the_work_finishes(qtbot):
    """The async path must end where the synchronous one did: on_apply gets the
    full-resolution image, and the dialog closes."""
    got = {}
    d = _dlg(qtbot, on_apply=lambda result, opts: got.update(result=result, opts=opts))
    d.set_balance_for_test(blue=0.5, strength=0.9)
    d._apply()
    qtbot.waitUntil(lambda: "result" in got, timeout=5000)
    assert got["result"].data.shape == d._starless.data.shape
    assert got["opts"]["midtones"] == pytest.approx([0.0, 0.0, 0.5])


def test_the_panel_states_the_mask_convention_correctly(qtbot):
    """White reveals, black conceals — the Photoshop convention, and what
    range_mask actually does: out = data + (shifted - data) * mask, so 1 is
    fully adjusted and 0 is untouched.

    Reported 2026-08-17. The panel said "mid-grey in the mask means untouched",
    which is the BACKGROUND GRADIENT VIEW's convention — that image is a signed
    difference, so its zero point sits in the middle. Two greyscale overlays in
    one app with opposite meanings, and the label had them crossed while the
    help topic had them right.
    """
    from PySide6.QtWidgets import QLabel
    d = _dlg(qtbot)
    text = " ".join(lbl.text().lower() for lbl in d.findChildren(QLabel))
    assert "mid-grey" not in text, "the mask's zero point is black, not mid-grey"
    assert "white" in text and "black" in text, "the convention is not stated"


def test_the_mask_can_be_inverted(qtbot):
    """Requested 2026-08-17. Selecting the complement of a band — everything
    EXCEPT the object, say — is otherwise unreachable: the handles can only
    describe one contiguous range."""
    d = _dlg(qtbot)
    d.preset_box.setCurrentText("Object, not the core")
    normal = d.mask_for(d._starless).copy()
    d.invert_check.setChecked(True)
    inverted = d.mask_for(d._starless)
    assert np.allclose(inverted, 1.0 - normal, atol=1e-6)


def test_inverting_moves_the_other_pixels(qtbot):
    """Not just the mask array — the composed RESULT must change the complement.
    An invert that never reached compose() would pass the test above."""
    d = _dlg(qtbot)
    d.preset_box.setCurrentText("Object, not the core")
    d.set_balance_for_test(blue=1.0, red=-1.0, strength=1.0)
    before = d._base.data.copy()
    normal_mask = d.mask_for(d._starless)
    d.invert_check.setChecked(True)
    after = d.compose().data
    # FULLY inside only: a pixel at 0.9 inverts to 0.1, so a tenth of the
    # adjustment legitimately still lands on it. Only mask == 1 inverts to
    # exactly zero, and the band reaches exactly 1 by construction.
    inside_band = normal_mask >= 1.0 - 1e-6
    outside_band = normal_mask < 1e-6
    assert inside_band.any() and outside_band.any()
    assert np.allclose(after[inside_band], before[inside_band], atol=1e-6), (
        "the band was still adjusted after inverting")
    assert not np.allclose(after[outside_band], before[outside_band], atol=1e-4), (
        "the complement was not adjusted")


def test_invert_is_recorded_in_the_option(qtbot):
    seen = {}
    d = _dlg(qtbot, on_apply=lambda result, opts: seen.update(opts))
    d.invert_check.setChecked(True)
    d.set_balance_for_test(blue=0.5)
    d._apply()
    qtbot.waitUntil(lambda: bool(seen), timeout=5000)
    assert seen["invert"] is True


def test_the_description_label_wraps(qtbot):
    """Seen in a screenshot 2026-08-17: the description was truncated because it
    had no word wrap, unlike the status label beside it — so it either clips or
    forces the panel wider than its 380 px cap."""
    from PySide6.QtWidgets import QLabel
    d = _dlg(qtbot)
    described = [lbl for lbl in d.findChildren(QLabel)
                 if "shift the colour" in lbl.text().lower()]
    assert described, "the description label is gone"
    assert described[0].wordWrap(), "the description label does not wrap"


def test_every_checkbox_label_fits_the_panel(qtbot):
    """Seen in screenshots twice on 2026-08-17. The side panel is capped at
    380 px and the form's label column eats roughly 130 of it, so a checkbox
    wider than ~250 px is silently CLIPPED — QCheckBox neither wraps nor elides,
    it just loses the end of its own text. Long explanations belong in the
    tooltip and the help, not in the label."""
    from PySide6.QtWidgets import QCheckBox
    d = _dlg(qtbot)
    for box in d.findChildren(QCheckBox):
        width = box.sizeHint().width()
        assert width <= 250, (
            f"{box.text()!r} needs {width} px and will be cut off; "
            f"shorten it and put the detail in the tooltip")
        assert box.toolTip(), f"{box.text()!r} has no tooltip to carry the detail"


# --- independent amounts per tonal range (2026-08-17) ------------------------

def test_switching_tone_leaves_the_other_ranges_UNCHANGED(qtbot):
    """The fiddly half of per-tone amounts, and the one worth an assert-unchanged
    test: set midtones, switch to highlights, come back — the midtone values must
    be exactly as left, not merely 'not zero'."""
    d = _dlg(qtbot)
    d.tone_box.setCurrentText("Midtones")
    d.sliders["red"].setValue(-18)
    d.sliders["blue"].setValue(20)
    before = (d.sliders["red"].value(), d.sliders["green"].value(),
              d.sliders["blue"].value())

    d.tone_box.setCurrentText("Highlights")
    assert (d.sliders["red"].value(), d.sliders["green"].value(),
            d.sliders["blue"].value()) == (0, 0, 0), "highlights inherited the midtones"
    d.sliders["blue"].setValue(40)

    d.tone_box.setCurrentText("Midtones")
    after = (d.sliders["red"].value(), d.sliders["green"].value(),
             d.sliders["blue"].value())
    assert after == before, f"midtones changed on the round trip: {before} -> {after}"


def test_both_ranges_reach_the_balance_at_once(qtbot):
    """Not just remembered in the widgets — both must be in the Balance that
    compose() uses, or the tool still applies one range at a time."""
    d = _dlg(qtbot)
    d.tone_box.setCurrentText("Midtones")
    d.sliders["red"].setValue(100)
    d.tone_box.setCurrentText("Highlights")
    d.sliders["blue"].setValue(100)

    b = d.balance()
    assert b.midtones == pytest.approx((1.0, 0.0, 0.0))
    assert b.highlights == pytest.approx((0.0, 0.0, 1.0))
    assert b.shadows == pytest.approx((0.0, 0.0, 0.0))


def test_the_option_records_all_three_ranges(qtbot):
    seen = {}
    d = _dlg(qtbot, on_apply=lambda result, opts: seen.update(opts))
    d.tone_box.setCurrentText("Shadows")
    d.sliders["green"].setValue(-30)
    d.tone_box.setCurrentText("Highlights")
    d.sliders["blue"].setValue(60)
    d._apply()
    qtbot.waitUntil(lambda: bool(seen), timeout=5000)
    assert seen["shadows"] == pytest.approx([0.0, -0.30, 0.0])
    assert seen["highlights"] == pytest.approx([0.0, 0.0, 0.60])
    assert seen["midtones"] == pytest.approx([0.0, 0.0, 0.0])


def test_reset_clears_every_range_not_just_the_visible_one(qtbot):
    """Reset with Highlights showing must not leave a midtone adjustment behind
    where the user cannot see it."""
    d = _dlg(qtbot)
    d.tone_box.setCurrentText("Midtones")
    d.sliders["red"].setValue(80)
    d.tone_box.setCurrentText("Highlights")
    d.sliders["blue"].setValue(80)
    d.reset()
    b = d.balance()
    assert b.midtones == (0.0, 0.0, 0.0) and b.highlights == (0.0, 0.0, 0.0)
    assert b.shadows == (0.0, 0.0, 0.0)
