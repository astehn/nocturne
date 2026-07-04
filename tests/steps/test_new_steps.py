import numpy as np
from seestar_processor.core.image import AstroImage
from seestar_processor.tools.base import write_temp_fits
from seestar_processor.tools.graxpert import GraXpert
from seestar_processor.tools.rcastro import RCAstro
from seestar_processor.steps.background import BackgroundStep
from seestar_processor.steps.crop import CropStep
from seestar_processor.core.crop import CropParams
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


def test_crop_step_applies_params():
    data = np.zeros((40, 50, 3), np.float32)
    data[5:35, 8:45] = 0.4
    out = CropStep().apply(AstroImage(data), CropParams(bounds=(5, 35, 8, 45)))
    assert out.data.shape == (30, 37, 3)


def test_crop_step_none_option_is_identity():
    data = np.random.rand(8, 8, 3).astype(np.float32)
    out = CropStep().apply(AstroImage(data), None)
    assert out.data.shape == (8, 8, 3)


def test_saturation_step_increases_chroma():
    data = np.tile(np.array([0.6, 0.4, 0.2], np.float32), (8, 8, 1))
    out = SaturationStep().apply(AstroImage(data), 1.0)
    assert out.data[0, 0].max() - out.data[0, 0].min() > 0.4


def test_saturation_step_falsy_option_is_native_noop():
    # A falsy option must mean "no change" (native), not greyscale.
    data = np.tile(np.array([0.6, 0.4, 0.2], np.float32), (8, 8, 1))
    for falsy in (None, "", 0):
        out = SaturationStep().apply(AstroImage(data), falsy)
        assert np.allclose(out.data, data, atol=1e-6)


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


def test_remove_green_step_clamps_green():
    import numpy as np
    from seestar_processor.core.image import AstroImage
    from seestar_processor.steps.remove_green_step import RemoveGreenStep
    data = np.full((4, 4, 3), 0.3, dtype=np.float32)
    data[..., 1] = 0.9
    out = RemoveGreenStep().apply(AstroImage(data))
    assert out.data[..., 1].max() <= 0.3 + 1e-6
