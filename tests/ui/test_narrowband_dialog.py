import numpy as np
import pytest

pytest.importorskip("PySide6")
from nocturne.core.image import AstroImage           # noqa: E402
from nocturne.settings import Settings               # noqa: E402
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
