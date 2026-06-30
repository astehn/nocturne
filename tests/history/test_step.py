import numpy as np
import pytest
from seestar_processor.core.image import AstroImage
from seestar_processor.history.step import Step


class _Double(Step):
    name = "double"

    def options(self):
        return ["x1", "x2"]

    def default_option(self):
        return "x1"

    def apply(self, img, option):
        factor = 2.0 if option == "x2" else 1.0
        return AstroImage(img.data * factor, img.is_linear)


def test_step_apply_uses_option():
    s = _Double()
    img = AstroImage(np.ones((2, 2), np.float32))
    assert s.apply(img, "x2").data[0, 0] == 2.0
    assert s.default_option() == "x1"


def test_abstract_step_cannot_instantiate():
    with pytest.raises(TypeError):
        Step()
