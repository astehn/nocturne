import numpy as np
from seestar_processor.core.image import AstroImage
from seestar_processor.tools.base import write_temp_fits
from seestar_processor.tools.rcastro import RCAstro
from seestar_processor.steps.deconvolution import DeconvolutionStep
from seestar_processor.steps.noise import NoiseStep


def _echo_runner(img):
    def fake(args):
        out_path = args[args.index("-o") + 1]
        write_temp_fits(img, out_path)
    return fake


def test_decon_fallback_when_no_rcastro():
    data = np.random.rand(16, 16, 3).astype(np.float32)
    img = AstroImage(data)
    out = DeconvolutionStep(rcastro=None).apply(img, "Medium")
    assert out.data.shape == (16, 16, 3)
    assert not np.allclose(out.data, data)  # fallback sharpen changed it


def test_decon_uses_bxt_when_rcastro_present():
    img = AstroImage(np.random.rand(8, 8, 3).astype(np.float32))
    captured = {}

    def fake(args):
        captured["args"] = args
        write_temp_fits(img, args[args.index("-o") + 1])

    step = DeconvolutionStep(rcastro=RCAstro("/fake/rc-astro"))
    step._runner = fake
    step.apply(img, "Large")
    assert "bxt" in captured["args"]
    assert captured["args"][captured["args"].index("--sharpen-nonstellar") + 1] == "0.9"


def test_noise_fallback_when_no_rcastro():
    rng = np.random.default_rng(0)
    data = np.clip(0.5 + rng.normal(0, 0.15, (32, 32, 3)), 0, 1).astype(np.float32)
    img = AstroImage(data)
    out = NoiseStep(rcastro=None).apply(img, "Large")
    assert out.data.std() < data.std()  # fallback denoise reduced noise


def test_noise_uses_nxt_when_rcastro_present():
    img = AstroImage(np.random.rand(8, 8, 3).astype(np.float32))
    captured = {}

    def fake(args):
        captured["args"] = args
        write_temp_fits(img, args[args.index("-o") + 1])

    step = NoiseStep(rcastro=RCAstro("/fake/rc-astro"))
    step._runner = fake
    step.apply(img, "Medium")
    assert "nxt" in captured["args"]
    assert captured["args"][captured["args"].index("--denoise") + 1] == "0.8"
