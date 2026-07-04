from seestar_processor.settings import Settings
from seestar_processor.steps.factory import make_step
from seestar_processor.steps.crop import CropStep
from seestar_processor.steps.stretch_step import StretchStep
from seestar_processor.steps.color import ColorStep
from seestar_processor.steps.levels import LevelsStep
from seestar_processor.steps.local_contrast import LocalContrastStep
from seestar_processor.steps.star_reduction import StarReductionStep
from seestar_processor.steps.remove_green_step import RemoveGreenStep


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
