import numpy as np
from seestar_processor.core.image import AstroImage
from seestar_processor.tools.graxpert import GraXpert
from seestar_processor.steps.background import BackgroundStep
from seestar_processor.steps.stretch_step import StretchStep


def test_background_step_maps_option_to_strength(monkeypatch):
    img = AstroImage(np.ones((4, 4, 3), np.float32))
    seen = {}

    def fake_runner(args):
        from seestar_processor.tools.base import write_temp_fits
        seen["strength"] = args[args.index("-smoothing") + 1]
        out_stem = args[args.index("-output") + 1]
        write_temp_fits(img, out_stem + ".fits")

    step = BackgroundStep(GraXpert("/fake"))
    step._runner = fake_runner  # injected for test
    step.apply(img, "Medium")
    assert seen["strength"] == "0.5"


def test_stretch_step_marks_nonlinear():
    step = StretchStep()
    out = step.apply(AstroImage(np.full((4, 4), 0.05, np.float32)), "Medium")
    assert out.is_linear is False
    assert step.options() == ["Small", "Medium", "Large"]
