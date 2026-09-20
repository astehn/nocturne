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
    average. Selecting by hue is self-aiming, so the guarantee is no longer
    spatial ("only near stars") but chromatic.

    REWRITTEN 2026-09-19 when the band widened from green to green-through-cyan.
    The old swatches were chosen to sit on the OLD edges, so after the widening
    four of them landed inside the new plateau together and the test stopped
    distinguishing anything — it still passed on three of the four mechanisms
    by accident. These sit on the new boundaries instead.

    Three separate things have to hold, and each swatch is chosen so that
    exactly ONE of them protects it:

      * `g >= r`, which protects WARM stars  (orange, magenta — inside no band
                                              because red is their largest
                                              channel, and that is the only
                                              thing saving them)
      * the cool edge at 190-214 deg         (202 half in; 220 just outside —
                                              this is what keeps blue stars)
      * the HSL-lightness landing            (the green swatch's exact value)

    The TEAL swatch is the point of the whole change: it scored 0.0 before
    2026-09-19 and must score 1.0. Andreas, after three passes at this tool:
    *"the tool still does nothing for my images"* — teal is what his stars
    actually are, and the band did not reach it.
    """
    import numpy as np
    from nocturne.core.image import AstroImage
    from nocturne.core.color import remove_green_fringe

    # (name, rgb, expected weight). Deliberately asymmetric channel values: a
    # fixture whose numbers commute cannot tell a correct hue rule from one
    # with red and blue swapped.
    swatches = [
        ("green    hue 120", (0.21, 0.83, 0.21), 1.0),   # dead centre
        ("yel-grn  hue  90", (0.40, 0.75, 0.05), 1.0),   # warm end of the plateau
        ("TEAL     hue 185", (0.05, 0.69, 0.75), 1.0),   # THE defect: 0.0 before this change
        ("cool ramp hue 202", (0.10, 0.48, 0.70), 0.5),  # half in, on the cool ramp
        ("just out hue 220", (0.10, 0.30, 0.70), 0.0),   # outside: blue stars start here
        ("blue     hue 229", (0.18, 0.31, 0.88), 0.0),   # a real blue star, untouched
        ("magenta  hue 330", (0.90, 0.50, 0.70), 0.0),   # red is max -> the warm guard
        ("orange   hue  26", (0.92, 0.46, 0.12), 0.0),   # red is max -> the warm guard
    ]
    stars = np.zeros((1, len(swatches), 3), np.float32)
    for i, (_n, rgb, _w) in enumerate(swatches):
        stars[0, i] = rgb
    starless = AstroImage(np.zeros((1, len(swatches), 3), np.float32), is_linear=False)

    out = remove_green_fringe(starless, AstroImage(stars, is_linear=False), 1.0).data
    for i, (name, rgb, weight) in enumerate(swatches):
        px = np.asarray(rgb, np.float32)
        # HSL lightness, which is what the step desaturates toward — Rec.709
        # luma until 2026-09-19, and that inflated red on teal pixels.
        mid = float((px.max() + px.min()) / 2)
        want = (1.0 - weight) * px + weight * mid
        assert np.allclose(out[0, i], want, atol=1e-5), \
            f"{name}: expected {want} at weight {weight}, got {out[0, i]}"


def test_degreening_a_star_lands_on_its_LIGHTNESS_and_invents_no_red():
    """Green becomes GREY, not white, and above all not red.

    This test used to assert that Rec.709 luma is preserved, on the stated
    grounds that *"Andreas asked for the Photoshop move (select greens, drop
    saturation to zero), and keeping luma is what makes it that move."* **That
    was wrong about Photoshop**, and he proved it on 2026-09-19 by doing the job
    there in thirty seconds with a Hue/Saturation layer and getting no red at
    all. Photoshop desaturates toward HSL LIGHTNESS, (max + min) / 2.

    The difference is not cosmetic. Luma weights green at 0.7152, so a teal
    pixel's luma is dominated by its green channel and neutralising toward it
    RAISES RED — measured across his NGC 281 master the background gained +0.71
    levels of red and net light, where Photoshop's move removes light. That was
    the "background moves towards red" he reported three times.

    So the property worth pinning is not "brightness is unchanged". It is
    "nothing is invented": the pixel lands neutral, at the lightness it had, and
    red does not rise to meet an inflated luma.
    """
    import numpy as np
    from nocturne.core.image import AstroImage
    from nocturne.core.color import remove_green_fringe, _LUM_WEIGHTS

    px = np.array([0.05, 0.69, 0.75], np.float32)       # a teal star
    stars = np.zeros((1, 1, 3), np.float32)
    stars[0, 0] = px
    starless = AstroImage(np.zeros((1, 1, 3), np.float32), is_linear=False)
    out = remove_green_fringe(starless, AstroImage(stars, is_linear=False), 1.0).data
    r, g, b = (float(c) for c in out[0, 0])

    assert abs(r - g) < 1e-5 and abs(g - b) < 1e-5, "it should land neutral"

    lightness = float((px.max() + px.min()) / 2)
    assert abs(r - lightness) < 1e-5, \
        f"it should land on HSL lightness {lightness}, not on {r}"

    luma = float(px @ _LUM_WEIGHTS.astype(np.float32))
    assert r < luma - 0.1, (
        "landing on luma would raise red from 0.05 to 0.558 — inventing red "
        "light to hold brightness constant is exactly the defect")
    assert r > float(px.min()) + 0.05, (
        "and it must not collapse to the minimum channel either, which would "
        "delete a faint teal star rather than neutralise it")
