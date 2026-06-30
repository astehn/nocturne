import numpy as np
from seestar_processor.core.image import AstroImage
from seestar_processor.steps.levels import LevelsStep


def test_levels_step_applies_tuple():
    out = LevelsStep().apply(AstroImage(np.full((8, 8), 0.3, np.float32)), (0.2, 1.0, 1.0))
    assert np.median(out.data) < 0.3


def test_levels_step_empty_is_identity():
    d = np.full((8, 8), 0.3, np.float32)
    out = LevelsStep().apply(AstroImage(d), "")
    assert np.allclose(out.data, d, atol=1e-6)
