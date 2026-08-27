import numpy as np
import pytest

pytest.importorskip("PySide6")
from nocturne.core.image import AstroImage           # noqa: E402
from nocturne.settings import Settings               # noqa: E402
from nocturne.core.narrowband import NarrowbandParams  # noqa: E402
from nocturne.ui.narrowband_dialog import NarrowbandDialog, PALETTES  # noqa: E402


def _img():
    ha = np.full((40, 40), 0.5, np.float32)
    oiii = np.full((40, 40), 0.2, np.float32)
    oiii[10:30, 10:30] = 0.6
    return AstroImage(np.stack([ha, oiii, oiii], axis=2), is_linear=False)


def _dialog(qtbot, **kw):
    d = NarrowbandDialog(Settings(), _img(), **kw)
    qtbot.addWidget(d)
    return d


def test_palettes_are_the_three_expected():
    assert list(PALETTES) == ["HOO", "Pseudo-SHO", "Pseudo-bicolor"]


def test_dialog_builds_with_seeded_layers(qtbot):
    d = _dialog(qtbot, starless=_img(), stars=None)
    d._on_starless((d._base, None))          # simulate showEvent seeding
    d._do_render()
    assert d.preview.has_image()


def _img_varied_ha():
    # Same shape/intent as _img(), but Ha has realistic per-pixel noise instead
    # of a perfectly flat 0.5. normalize_to_reference() intentionally treats a
    # zero-variance reference channel as degenerate (identity, see
    # tests/core/test_narrowband.py::test_normalize_degenerate_channel_is_identity_no_nan),
    # which would make oiii_boost inert end-to-end against a flat Ha.
    rng = np.random.default_rng(3)
    ha = np.clip(0.5 + 0.03 * rng.standard_normal((40, 40)), 0, 1).astype(np.float32)
    oiii = np.full((40, 40), 0.2, np.float32)
    oiii[10:30, 10:30] = 0.6
    return AstroImage(np.stack([ha, oiii, oiii], axis=2), is_linear=False)


def test_oiii_slider_changes_the_render(qtbot):
    img = _img_varied_ha()
    d = NarrowbandDialog(Settings(), img, starless=img, stars=None)
    qtbot.addWidget(d)
    d._on_starless((d._base, None))
    d.oiii_slider.setValue(50)
    d._do_render()
    low = d.preview_result().data.copy()
    d.oiii_slider.setValue(90)               # push OIII harder
    d._do_render()
    high = d.preview_result().data
    assert not np.allclose(low, high)


def test_value_labels_and_default_preserve_off(qtbot):
    d = _dialog(qtbot, starless=_img(), stars=None)
    assert d.lightness_check.isChecked() is False          # brighter combine is the default
    assert d.oiii_val.text().startswith("×")               # OIII boost shown as a multiplier
    d.oiii_slider.setValue(75)                              # 75/50 = 1.5
    assert d.oiii_val.text() == "×1.50"
    d.protect_slider.setValue(30)
    assert d.protect_val.text() == "30%"


def test_apply_screens_stars_back_and_calls_on_apply(qtbot):
    got = []
    stars = AstroImage(np.zeros((40, 40, 3), np.float32), is_linear=False)
    stars.data[5, 5] = [0.95, 0.95, 0.95]
    d = _dialog(qtbot, starless=_img(), stars=stars, on_apply=lambda r, p: got.append((r, p)))
    d._on_starless((d._base, stars))
    d.apply()
    qtbot.waitUntil(lambda: bool(got), timeout=8000)   # Apply is async since it
    #                                                    renders at full resolution
    assert got and isinstance(got[0][0], AstroImage)
    assert got[0][0].data[5, 5].max() > 0.5          # star screened back
    assert got[0][1].palette == "HOO"                # params passed through


def _with_stars(h=64, w=64):
    """(base, starless, stars) for a dualband frame — the starless layer must
    genuinely differ from the base and the stars must be real, or neither of the
    faults below has anything to damage."""
    from nocturne.core.narrowband import screen
    rng = np.random.default_rng(5)
    ha = np.clip(0.5 + 0.03 * rng.standard_normal((h, w)), 0, 1).astype(np.float32)
    oiii = np.full((h, w), 0.2, np.float32)
    oiii[16:48, 16:48] = 0.6
    starless = AstroImage(np.stack([ha, oiii, oiii], axis=2), is_linear=False)
    stars_data = np.zeros_like(starless.data)
    for y, x in zip(rng.integers(3, h - 3, 12), rng.integers(3, w - 3, 12)):
        stars_data[y - 1:y + 2, x - 1:x + 2] = 0.85
    stars = AstroImage(stars_data, is_linear=False)
    return AstroImage(screen(starless.data, stars_data), is_linear=False), starless, stars


def test_the_preview_shows_the_stars(qtbot):
    """The preview rendered the STARLESS layer and screened the stars back only
    on Apply, so what you tuned against was never what you got. That breaks the
    project's central rule — the preview at any step must equal what export would
    produce — and it hides the tool's own promise: you cannot watch the stars
    stay unaltered if they are not on screen."""
    base, starless, stars = _with_stars()
    d = NarrowbandDialog(Settings(), base, starless=starless, stars=stars)
    qtbot.addWidget(d)
    d._on_starless((starless, stars))
    d._do_render()
    shown = d.preview_result().data
    bright = shown.max(axis=2) > 0.8
    assert bright.sum() >= 20, f"only {bright.sum()} bright pixels — the stars are missing"


def test_the_preview_equals_what_apply_produces(qtbot):
    """WYSIWYG, at matched resolution: preview and Apply must run the same
    composition, differing only in which pixels were drawn."""
    from nocturne.core.narrowband import render, screen
    base, starless, stars = _with_stars()
    d = NarrowbandDialog(Settings(), base, starless=starless, stars=stars)
    qtbot.addWidget(d)
    d._on_starless((starless, stars))
    d.oiii_slider.setValue(70)
    d._do_render()
    shown = d.preview_result().data
    expect = screen(render(d._prev_starless, d._params()).data,
                    np.clip(d._prev_stars.data, 0, 1))
    assert np.allclose(shown, expect, atol=1e-6)


def test_the_preview_downscale_conserves_the_stars(qtbot):
    """Same defect Colour Balance had: strided sampling dropped 253 of 300
    synthetic stars. Flux, because it is the property that can be stated
    numerically."""
    from nocturne.ui.narrowband_dialog import _downscale
    bg = 0.05
    data = np.full((512, 512, 3), bg, np.float32)
    rng = np.random.default_rng(1)
    for y, x in zip(rng.integers(3, 509, 200), rng.integers(3, 509, 200)):
        data[y - 1:y + 2, x - 1:x + 2] = 0.9
    small = _downscale(AstroImage(data, is_linear=False), max_edge=64).data
    step = 512 // 64
    before = float(np.clip(data - bg, 0, None).sum())
    after = float(np.clip(small - bg, 0, None).sum()) * step * step
    assert after == pytest.approx(before, rel=0.02), (
        f"star flux {after:.0f} against {before:.0f} — the preview is losing stars")


def test_a_missing_stars_layer_still_renders(qtbot):
    """Without RC-Astro there is no split, and the dialog falls back to the whole
    image with stars=None. That path must not crash on the new screen step."""
    img = _img_varied_ha()
    d = NarrowbandDialog(Settings(), img, starless=img, stars=None)
    qtbot.addWidget(d)
    d._on_starless((img, None))
    d._do_render()
    assert d.preview.has_image()


def test_apply_does_not_block_the_ui_thread(qtbot, monkeypatch):
    """Apply renders at FULL resolution — measured at 8.4 s on a 39.5 MP master
    with Preserve lightness on, 2.9 s without. Doing that on the UI thread
    freezes the window with nothing on screen to say why. Star removal in this
    same dialog already runs through run_async; Apply must too.
    """
    import time
    import nocturne.ui.narrowband_dialog as nd
    got = []
    d = _dialog(qtbot, starless=_img(), stars=None, on_apply=lambda r, p: got.append(r))
    d._on_starless((d._base, None))          # preview renders with the REAL function

    real = nd.render
    monkeypatch.setattr(nd, "render",
                        lambda img, p, **kw: (time.sleep(0.5), real(img, p, **kw))[1])

    t0 = time.perf_counter()
    d.apply()
    elapsed = time.perf_counter() - t0
    assert elapsed < 0.25, f"apply() blocked the UI thread for {elapsed:.2f}s"
    assert not d.apply_btn.isEnabled(), "Apply must disable itself while it runs"
    assert d.status.text(), "and say that something is happening"

    qtbot.waitUntil(lambda: bool(got), timeout=8000)
    assert isinstance(got[0], AstroImage)


def test_the_dialog_defaults_are_the_engine_defaults(qtbot):
    """One source of truth. The dataclass, the constructor and reset() each
    declared these separately, and lightness_preserve had already drifted: the
    dialog shipped False ("the better default") while NarrowbandParams said
    True — so a recipe or batch run with no explicit option produced a DIFFERENT
    image from the same tool used interactively.
    """
    d = _dialog(qtbot, starless=_img(), stars=None)
    assert d._params() == NarrowbandParams()


def test_preserve_lightness_ships_OFF(qtbot):
    """Pins the VALUE, not merely that the two agree.

    test_the_dialog_defaults_are_the_engine_defaults cannot catch this: the
    dialog now DERIVES its controls from NarrowbandParams, so flipping the
    engine default flips the dialog with it and they still agree. Proven by
    mutation — that test passed with the default put back to True. This one
    fails, which is the whole point of writing it.

    OFF is deliberate: the brighter combine is the better default, and the Lab
    round-trip that Preserve lightness needs is also what makes Apply three
    times slower.
    """
    assert NarrowbandParams().lightness_preserve is False
    d = _dialog(qtbot, starless=_img(), stars=None)
    assert d.lightness_check.isChecked() is False


def test_reset_restores_the_engine_defaults(qtbot):
    d = _dialog(qtbot, starless=_img(), stars=None)
    d.palette_box.setCurrentText("Pseudo-SHO")
    d.oiii_slider.setValue(90)
    d.sat_slider.setValue(10)
    d.protect_slider.setValue(5)
    d.lightness_check.setChecked(True)
    d.reset()
    assert d._params() == NarrowbandParams()


def test_the_dialog_tells_the_engine_whether_the_layer_is_starless(qtbot, monkeypatch):
    """The engine cannot work this out for itself. With a real StarX split the
    taper must come off or the Saturation slider does nothing on the nebula
    core; WITHOUT StarX the dialog recolours the whole frame, stars included,
    and the taper is still protecting real star colour."""
    import nocturne.ui.narrowband_dialog as nd
    seen = []
    real = nd.render
    monkeypatch.setattr(nd, "render",
                        lambda img, p, **kw: (seen.append(kw.get("has_stars")),
                                              real(img, p, **kw))[1])
    stars = AstroImage(np.zeros((40, 40, 3), np.float32), is_linear=False)
    d = _dialog(qtbot, starless=_img(), stars=stars)
    d._on_starless((d._base, stars))
    assert seen[-1] is False, "a real split means the layer is starless"

    d2 = _dialog(qtbot, starless=_img(), stars=None)
    d2._on_starless((d2._base, None))
    assert seen[-1] is True, "no split means the stars are still in the frame"


def test_green_blend_is_disabled_where_it_does_nothing(qtbot):
    """A slider that moves and changes nothing reads as a broken app in the
    moment, and the help text saying so does not undo that. Greyed rather than
    hidden, so the capability stays discoverable."""
    from nocturne.core.narrowband import PALETTES_USING_BLEND
    d = _dialog(qtbot, starless=_img(), stars=None)
    d._on_starless((d._base, None))
    for palette in PALETTES:
        d.palette_box.setCurrentText(palette)
        expected = palette in PALETTES_USING_BLEND
        assert d.blend_slider.isEnabled() is expected, f"{palette}: slider"
        assert d.blend_val.isEnabled() is expected, f"{palette}: value label"
    d.palette_box.setCurrentText("Pseudo-SHO")
    assert d.blend_slider.toolTip(), "and it must say WHY it is greyed"


def test_a_disabled_green_blend_keeps_its_value(qtbot):
    """The setting is preserved and bites again the moment you return to HOO;
    blanking it would suggest it had been lost."""
    d = _dialog(qtbot, starless=_img(), stars=None)
    d._on_starless((d._base, None))
    d.blend_slider.setValue(85)
    d.palette_box.setCurrentText("Pseudo-SHO")
    assert d.blend_val.text() == "0.85"
    d.palette_box.setCurrentText("HOO")
    assert d.blend_slider.isEnabled() and d._params().blend_amount == 0.85


def test_tame_core_is_off_by_default_and_renders_identically(qtbot):
    """The reproducibility guard. A new control must not change what the tool
    already produces, or every saved recipe and project quietly renders
    differently the day it ships."""
    from nocturne.core.narrowband import NarrowbandParams, render
    d = _dialog(qtbot, starless=_img(), stars=None)
    assert d.tame_slider.value() == 0
    assert d.tame_val.text() == "off"
    assert d._params().highlight_reduction == 1.0
    a = render(_img(), d._params(), has_stars=False).data
    b = render(_img(), NarrowbandParams(), has_stars=False).data
    assert np.array_equal(a, b), "off must be bit-identical to the old default"


def test_tame_core_actually_pulls_the_blown_core_down(qtbot):
    """Measured on a real NGC 281 render: near-white core pixels fall from 6.2%
    at 1.0 to 2.1% at 5.0. This is the control for the white core, and it was
    sitting in the engine at identity where nobody could reach it."""
    from nocturne.core.narrowband import render
    d = _dialog(qtbot, starless=_img(), stars=None)
    bright = AstroImage(np.stack([np.full((40, 40), 0.97, np.float32),
                                  np.full((40, 40), 0.93, np.float32),
                                  np.full((40, 40), 0.93, np.float32)], axis=2),
                        is_linear=False)
    off = render(bright, d._params(), has_stars=False).data.mean()
    d.tame_slider.setValue(d.tame_slider.maximum())
    assert d._params().highlight_reduction > 1.0
    on = render(bright, d._params(), has_stars=False).data.mean()
    assert on < off * 0.95, f"Tame core must darken the highlights: {on:.3f} vs {off:.3f}"
    assert d.tame_val.text() != "off"


def test_tame_core_resets_and_stays_inside_the_defaults_guard(qtbot):
    from nocturne.core.narrowband import NarrowbandParams
    d = _dialog(qtbot, starless=_img(), stars=None)
    d.tame_slider.setValue(70)
    d.reset()
    assert d.tame_slider.value() == 0
    assert d._params() == NarrowbandParams(), "the new field must round-trip too"
