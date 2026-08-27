import numpy as np
import pytest

pytest.importorskip("PySide6")
from nocturne.core.image import AstroImage  # noqa: E402
from nocturne.ui.star_spikes_dialog import StarSpikesDialog  # noqa: E402


def _img():
    # a bright dot on a dark field so detection finds a star
    a = np.zeros((64, 64, 3), np.float32)
    a[20, 40] = 1.0
    a[19:22, 39:42] = 0.9
    return AstroImage(a, is_linear=False)


def test_dialog_builds_and_detects(qtbot):
    d = StarSpikesDialog(_img())
    qtbot.addWidget(d)
    assert d.length_slider.value() == 0
    assert d.intensity_slider.value() == 100  # full strength by default
    # bounded by what the image actually contains: this fixture holds one star,
    # so offering six would be promising five that do not exist
    assert d.stars_slider.value() == min(6, len(d._stars))
    assert len(d._stars) >= 1                 # detected on construction


def test_intensity_slider_dims_the_spikes(qtbot):
    d = StarSpikesDialog(_img())
    qtbot.addWidget(d)
    d.length_slider.setValue(80)
    d._render_preview()
    full = d.result().data.copy()
    d.intensity_slider.setValue(40)
    d._render_preview()
    dimmed = d.result().data
    # same spikes, fainter — less deviation from the base than at full strength
    base = d._base.data
    assert np.abs(dimmed - base).sum() < np.abs(full - base).sum()
    assert not np.allclose(dimmed, base)      # still visibly present


def test_slider_change_renders_preview(qtbot):
    d = StarSpikesDialog(_img())
    qtbot.addWidget(d)
    d.length_slider.setValue(60)
    d._render_preview()
    assert d.preview.has_image()
    # length 0 -> result is the untouched base; length > 0 -> changed
    changed = d.result().data
    assert not np.allclose(changed, d._base.data)


def test_preview_is_fitted_once_the_dialog_has_a_real_size(qtbot):
    """The preview is first fitted in __init__, against a viewport that has not
    been laid out yet — it used to open "zoomed out to looks empty".

    This was a showEvent workaround local to this dialog. It now falls out of
    ImageView re-fitting on resize, so the requirement is asserted here and the
    mechanism is tested in test_image_view. Deleting the workaround without
    keeping this would have removed the only check that the dialog opens usable."""
    d = StarSpikesDialog(_img())
    qtbot.addWidget(d)
    d.resize(900, 700)
    d.show()
    qtbot.waitExposed(d)
    view = d.preview.view
    assert view._fitted, "the preview must be fitted once it has a real size"
    # The image must FILL the viewport in its constraining dimension. Checking
    # only "the whole image is visible" would pass while it sat tiny in the
    # middle -- which IS the bug. A correct fit gives min(ratio) ~ 1.0; a fit
    # measured against the pre-layout viewport leaves both ratios far higher.
    pm = view._item.pixmap()
    vis = view.mapToScene(view.viewport().rect()).boundingRect()
    fill = min(vis.width() / pm.width(), vis.height() / pm.height())
    assert fill < 1.2, f"preview is only filling 1/{fill:.1f} of the viewport"


def test_apply_calls_back_with_result(qtbot):
    got = []
    d = StarSpikesDialog(_img(), on_apply=got.append)
    qtbot.addWidget(d)
    d.length_slider.setValue(50)
    d._render_preview()
    d.apply_btn.click()
    assert got and isinstance(got[0], AstroImage)
    assert got[0].data.shape == (64, 64, 3)


def _starless(h=120, w=120):
    """A smooth nebula with no stars in it — a completely ordinary input for
    anyone who exports Starless + Stars."""
    g = np.tile(np.linspace(0.15, 0.55, w), (h, 1)).astype(np.float32)
    return AstroImage(np.repeat(g[:, :, None], 3, axis=2), is_linear=False)


def test_a_starless_image_says_so_instead_of_doing_nothing(qtbot):
    """Measured on three plausible inputs — a smooth nebula, a starless export
    and pure noise — detection found 0 stars and every slider became a silent
    no-op. Nothing distinguished "this tool is broken" from "this image has no
    stars", which is the worst of both."""
    d = StarSpikesDialog(_starless())
    qtbot.addWidget(d)
    assert d._stars == []
    d.show()
    qtbot.waitExposed(d)
    assert d.preview.overlay.isVisible(), "it must SAY there are no stars"
    assert "star" in d.preview.overlay.text().lower()
    assert not d.length_slider.isEnabled(), "and not offer sliders that cannot work"


def test_the_star_count_cannot_exceed_the_stars_that_exist(qtbot):
    """Not 'however many stars are in the image' — SEP finds 4,887 objects on a
    30-minute NGC 281 master and 2,000 spikes costs 1.7 s per slider tick on a
    39.5 MP frame. The cap only ever LOWERS the maximum from its safe default.
    """
    from nocturne.core.star_spikes import _MAX_STARS
    d = StarSpikesDialog(_img())
    qtbot.addWidget(d)
    assert d.stars_slider.maximum() == min(_MAX_STARS, len(d._stars))
    assert d.stars_slider.maximum() <= _MAX_STARS, "the safety cap must still hold"
    assert d.stars_slider.value() <= d.stars_slider.maximum()


def test_the_new_sliders_are_wired_and_default_to_something_visible(qtbot):
    """Both default non-zero: white, identical spikes are the thing being fixed,
    and Star Spikes stores a finished image rather than parameters, so no
    existing project can be disturbed by changing them."""
    from nocturne.core.star_spikes import _COLOUR_MAX_BOOST
    d = StarSpikesDialog(_img())
    qtbot.addWidget(d)
    assert d.colour_slider.value() > 0 and d.variation_slider.value() > 0
    length, count, angle, intensity, variation, colour = d._params()
    assert 0.0 < colour <= _COLOUR_MAX_BOOST
    assert 0.0 < variation <= 1.0


def _many_stars(h=160, w=160):
    """Several stars, because the jitter is seeded per star: with only ONE, its
    single draw can land near zero and the test proves nothing."""
    yy, xx = np.mgrid[0:h, 0:w]
    lum = np.full((h, w), 0.02, np.float32)
    rng = np.random.default_rng(5)
    for cy, cx in zip(rng.integers(10, h - 10, 12), rng.integers(10, w - 10, 12)):
        lum += 0.9 * np.exp(-(((yy - cy) ** 2 + (xx - cx) ** 2) / (2 * 1.7 ** 2)))
    lum = np.clip(lum + 0.004 * rng.standard_normal((h, w)), 0, 1).astype(np.float32)
    return AstroImage(np.repeat(lum[:, :, None], 3, axis=2), is_linear=False)


def test_variation_changes_the_picture_and_stays_put(qtbot):
    """Deterministic: nudging ANOTHER slider must not restyle every spike."""
    d = StarSpikesDialog(_many_stars())
    qtbot.addWidget(d)
    d.length_slider.setValue(70)
    d._render_preview()
    a = d.result().data.copy()
    d._render_preview()
    assert np.array_equal(a, d.result().data), "a re-render must be identical"
    d.variation_slider.setValue(0)
    d._render_preview()
    assert not np.array_equal(a, d.result().data), "variation must do something"
