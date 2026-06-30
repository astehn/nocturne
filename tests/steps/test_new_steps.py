import numpy as np
from seestar_processor.core.image import AstroImage
from seestar_processor.tools.base import write_temp_fits
from seestar_processor.tools.graxpert import GraXpert
from seestar_processor.tools.rcastro import RCAstro
from seestar_processor.steps.background import BackgroundStep
from seestar_processor.steps.crop_auto import CropAutoStep
from seestar_processor.steps.saturation_step import SaturationStep
from seestar_processor.steps.noise_sharpen import NoiseSharpenStep


def test_background_off_is_noop():
    img = AstroImage(np.random.rand(8, 8, 3).astype(np.float32))
    out = BackgroundStep(GraXpert("/fake")).apply(img, "off")
    assert np.allclose(out.data, img.data)


def test_background_light_calls_graxpert():
    img = AstroImage(np.random.rand(8, 8, 3).astype(np.float32))
    captured = {}

    def fake(args):
        captured["args"] = args
        write_temp_fits(img, args[args.index("-output") + 1])

    step = BackgroundStep(GraXpert("/fake"))
    step._runner = fake
    step.apply(img, "light")
    assert captured["args"][captured["args"].index("-smoothing") + 1] == "0.3"


def test_crop_auto_step_removes_border():
    data = np.zeros((40, 50, 3), np.float32)
    data[5:35, 8:45] = 0.4
    out = CropAutoStep().apply(AstroImage(data), 0.0)
    assert out.data.shape == (30, 37, 3)


def test_saturation_step_increases_chroma():
    data = np.tile(np.array([0.6, 0.4, 0.2], np.float32), (8, 8, 1))
    out = SaturationStep().apply(AstroImage(data), 1.0)
    assert out.data[0, 0].max() - out.data[0, 0].min() > 0.4


def test_noise_sharpen_fallback_changes_image():
    rng = np.random.default_rng(0)
    img = AstroImage(np.clip(0.5 + rng.normal(0, 0.1, (24, 24, 3)), 0, 1).astype(np.float32))
    out = NoiseSharpenStep(rcastro=None).apply(img, "medium")
    assert out.data.shape == img.data.shape
    assert not np.allclose(out.data, img.data)


def test_noise_sharpen_uses_rcastro_when_present():
    img = AstroImage(np.random.rand(8, 8, 3).astype(np.float32))
    calls = []

    def fake(args):
        calls.append(args)
        write_temp_fits(img, args[args.index("-o") + 1])

    step = NoiseSharpenStep(rcastro=RCAstro("/fake/rc-astro"))
    step._runner = fake
    step.apply(img, "strong")
    products = [a[a.index("--no-banner") + 1] for a in calls]
    assert products == ["nxt", "bxt"]  # denoise then sharpen
