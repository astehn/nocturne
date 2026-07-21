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


def test_make_step_saturation_has_rcastro():
    from nocturne.steps.factory import make_step
    from nocturne.steps.saturation_step import SaturationStep
    from nocturne.settings import Settings
    step = make_step("saturation", Settings())
    assert isinstance(step, SaturationStep)
    assert step._rc is not None            # constructed with an RCAstro


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
    out = step.apply(AstroImage(np.full((4, 4, 3), 0.5, np.float32)), 0.6).data
    assert np.allclose(out, remove_green_fringe(starless, stars, 0.6).data)
