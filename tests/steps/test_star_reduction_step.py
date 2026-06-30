import os

import numpy as np
from seestar_processor.core.image import AstroImage
from seestar_processor.tools.base import write_temp_fits
from seestar_processor.tools.rcastro import RCAstro
from seestar_processor.steps.star_reduction import StarReductionStep


def test_uses_starx_and_recombines():
    img = AstroImage(np.full((16, 16, 3), 0.2, np.float32), is_linear=False)
    calls = {}

    def fake(args):
        calls["args"] = args
        out = args[args.index("-o") + 1]
        write_temp_fits(AstroImage(img.data * 0.5), out)  # starless
        write_temp_fits(AstroImage(img.data * 0.5),
                        os.path.join(os.path.dirname(out), "s-sxt.fits"))  # stars

    step = StarReductionStep(RCAstro("/fake"))
    step._runner = fake
    out = step.apply(img, "medium")
    assert "sxt" in calls["args"]
    assert out.data.shape == (16, 16, 3)
    assert out.is_linear is False
