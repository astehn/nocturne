from nocturne.settings import Settings
from nocturne.steps.factory import make_step
from nocturne.steps.crop import CropStep
from nocturne.steps.stretch_step import StretchStep
from nocturne.steps.color import ColorStep
from nocturne.steps.levels import LevelsStep
from nocturne.steps.local_contrast import LocalContrastStep
from nocturne.steps.star_reduction import StarReductionStep
from nocturne.steps.remove_green_step import RemoveGreenStep


def test_make_step_types():
    s = Settings()
    assert isinstance(make_step("crop", s), CropStep)
    assert isinstance(make_step("stretch", s), StretchStep)
    assert isinstance(make_step("color", s), ColorStep)
    assert isinstance(make_step("levels", s), LevelsStep)
    assert isinstance(make_step("local_contrast", s), LocalContrastStep)
    assert isinstance(make_step("star_reduction", s), StarReductionStep)
    assert isinstance(make_step("remove_green", s), RemoveGreenStep)
    assert isinstance(make_step("rotate", s), CropStep)
    assert isinstance(make_step("flip_h", s), CropStep)
    assert isinstance(make_step("flip_v", s), CropStep)
    from nocturne.steps.deconvolution_step import DeconvolutionStep
    assert isinstance(make_step("deconvolution", s), DeconvolutionStep)


def test_make_step_recover_core():
    from nocturne.steps.factory import make_step
    from nocturne.steps.recover_core import RecoverCoreStep
    from nocturne.settings import Settings
    step = make_step("recover_core", Settings())
    assert isinstance(step, RecoverCoreStep)
    assert step.name == "Recover Core"


def test_recover_core_step_applies_amount():
    import numpy as np
    from nocturne.core.image import AstroImage
    from nocturne.core.hdr import recover_core
    from nocturne.steps.recover_core import RecoverCoreStep
    img = AstroImage(np.full((32, 32, 3), 0.9, np.float32), is_linear=False)
    got = RecoverCoreStep().apply(img, 0.6).data
    assert np.allclose(got, recover_core(img, 0.6).data)
    # empty option -> no-op amount 0
    assert np.allclose(RecoverCoreStep().apply(img, "").data, img.data, atol=1e-6)


def test_make_step_curves():
    from nocturne.steps.factory import make_step
    from nocturne.steps.curves import CurvesStep
    from nocturne.settings import Settings
    assert isinstance(make_step("curves", Settings()), CurvesStep)


def test_curves_step_applies_points():
    import numpy as np
    from nocturne.core.image import AstroImage
    from nocturne.core.curves import apply_curve
    from nocturne.steps.curves import CurvesStep
    img = AstroImage(np.full((16, 16, 3), 0.5, np.float32), is_linear=False)
    pts = [(0.0, 0.0), (0.5, 0.7), (1.0, 1.0)]
    assert np.allclose(CurvesStep().apply(img, pts).data, apply_curve(img, pts).data)
    # empty option -> identity no-op
    assert np.allclose(CurvesStep().apply(img, "").data, img.data, atol=1e-4)


def test_make_step_saturation_rc_or_none():
    from nocturne.steps.factory import make_step
    from nocturne.steps.saturation_step import SaturationStep
    from nocturne.settings import Settings
    # No RC-Astro path (default) -> rc is None so the step uses the free star split;
    # this mirrors the deconvolution/noise_sharpen rc-or-None wiring.
    step = make_step("saturation", Settings())
    assert isinstance(step, SaturationStep)
    assert step._rc is None


def test_make_step_green_fringe():
    from nocturne.steps.factory import make_step
    from nocturne.steps.green_fringe import GreenFringeStep
    from nocturne.settings import Settings
    assert isinstance(make_step("green_fringe", Settings()), GreenFringeStep)


def test_green_fringe_step_splits_then_degreens():
    import numpy as np
    from nocturne.core.image import AstroImage
    from nocturne.core.color import remove_green_fringe
    from nocturne.steps.green_fringe import GreenFringeStep

    starless = AstroImage(np.full((4, 4, 3), 0.3, np.float32), is_linear=False)
    stars = np.zeros((4, 4, 3), np.float32); stars[2, 2] = (0.2, 0.9, 0.3)
    stars = AstroImage(stars, is_linear=False)

    class _FakeRC:
        def remove_stars(self, img, runner=None):
            return starless, stars

    step = GreenFringeStep(_FakeRC())
    img = AstroImage(np.full((4, 4, 3), 0.5, np.float32))
    out = step.apply(img, 0.6).data
    expected = remove_green_fringe(starless, stars, 0.6).data
    assert np.allclose(out, expected)


def test_the_stars_layer_degreen_touches_only_pixels_that_READ_green():
    """What replaced the star mask, and the reason it could go.

    The step used to confine itself to a star-neighbourhood mask because its
    operator was SCNR, which removes green wherever green exceeds the red/blue
    average — true of cyan and yellow-green too. Measured on two real drizzled
    masters (2026-09-13), only 4.0% (NGC 281) and 5.6% (IC 1396A) of the green
    SCNR removed came from pixels whose hue actually reads green; on NGC 281
    49.5% of it came from CYAN. So the mask was fencing off a badly aimed
    operator rather than aiming a good one.

    Selecting by hue is self-aiming, so the guarantee is no longer spatial
    ("only near stars") but chromatic. Three separate things have to hold and
    each swatch below is chosen so that exactly ONE of them protects it:

      * the green-is-max gate      (magenta, violet — inside the |t| band, but
                                    green is not their largest channel)
      * the band edges             (hue 170 just outside; hue 150 half in)
      * Rec.709 luma preservation  (the green swatch's exact landing value)

    Picked that way on purpose. A first version used a plain cyan and a plain
    yellow, and BOTH mechanisms rejected each of them — so widening the band
    and deleting the gate were each invisible, and two of three mutations
    passed against a test that looked thorough.
    """
    import numpy as np
    from nocturne.core.image import AstroImage
    from nocturne.core.color import remove_green_fringe, _LUM_WEIGHTS

    # (name, rgb, expected weight). Deliberately asymmetric channel values: a
    # fixture whose numbers commute cannot tell a correct hue rule from one
    # with red and blue swapped.
    swatches = [
        ("green   hue 120", (0.21, 0.83, 0.21), 1.0),    # dead centre of the band
        ("grn-cyan hue 150", (0.05, 0.75, 0.40), 0.5),   # t=+0.5, half weight
        ("grn-cyan hue 170", (0.05, 0.75, 0.633), 0.0),  # t=+0.833, just outside
        ("yel-grn hue  90", (0.40, 0.75, 0.05), 0.5),    # t=-0.5, the mirror
        ("magenta hue 330", (0.90, 0.50, 0.70), 0.0),    # |t|=0.5 but red is max
        ("violet  hue 260", (0.70, 0.60, 0.90), 0.0),    # |t|=0.667 but blue is max
        ("cyan    hue 180", (0.11, 0.80, 0.80), 0.0),
        ("blue    hue 240", (0.18, 0.31, 0.88), 0.0),
    ]
    stars = np.zeros((1, len(swatches), 3), np.float32)
    for i, (_n, rgb, _w) in enumerate(swatches):
        stars[0, i] = rgb
    starless = AstroImage(np.zeros((1, len(swatches), 3), np.float32), is_linear=False)

    out = remove_green_fringe(starless, AstroImage(stars, is_linear=False), 1.0).data
    for i, (name, rgb, weight) in enumerate(swatches):
        px = np.asarray(rgb, np.float32)
        lum = float(px @ _LUM_WEIGHTS.astype(np.float32))
        want = (1.0 - weight) * px + weight * lum
        assert np.allclose(out[0, i], want, atol=1e-5), \
            f"{name}: expected {want} at weight {weight}, got {out[0, i]}"


def test_degreening_a_star_preserves_its_brightness():
    """Green becomes WHITE, not gone.

    SCNR clamps green to the red/blue average, which on a green-dominant pixel
    deletes the light rather than neutralising it — a de-greened star gets
    dimmer and smaller. Andreas asked for the Photoshop move (select greens,
    drop saturation to zero), and keeping luma is what makes it that move.
    """
    import numpy as np
    from nocturne.core.image import AstroImage
    from nocturne.core.color import remove_green_fringe, _LUM_WEIGHTS

    stars = np.zeros((1, 1, 3), np.float32)
    stars[0, 0] = (0.21, 0.83, 0.21)
    starless = AstroImage(np.zeros((1, 1, 3), np.float32), is_linear=False)
    out = remove_green_fringe(starless, AstroImage(stars, is_linear=False), 1.0).data

    w = _LUM_WEIGHTS.astype(np.float32)
    before = float(stars[0, 0] @ w)
    after = float(out[0, 0] @ w)
    assert abs(after - before) < 1e-5, \
        f"de-greening changed the star's brightness: {before} -> {after}"
    r, g, b = out[0, 0]
    assert abs(r - g) < 1e-5 and abs(g - b) < 1e-5, "and it should land neutral"
