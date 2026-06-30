import numpy as np
from seestar_processor.core.image import AstroImage
from seestar_processor.steps.stretch_step import StretchStep

# BackgroundStep is covered by tests/steps/test_new_steps.py (off/light/strong).


def test_stretch_step_marks_nonlinear():
    step = StretchStep()
    out = step.apply(AstroImage(np.full((4, 4), 0.05, np.float32)), "Medium")
    assert out.is_linear is False
    assert step.options() == ["Small", "Medium", "Large"]
