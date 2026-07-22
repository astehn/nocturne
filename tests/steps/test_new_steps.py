import numpy as np
from nocturne.core.image import AstroImage
from nocturne.tools.base import write_temp_fits
from nocturne.tools.graxpert import GraXpert
from nocturne.tools.rcastro import RCAstro
from nocturne.steps.background import BackgroundStep
from nocturne.steps.crop import CropStep
from nocturne.core.crop import CropParams
from nocturne.steps.saturation_step import SaturationStep
from nocturne.steps.noise_sharpen import NoiseSharpenStep


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
    out = SaturationStep(None).apply(AstroImage(data), 1.0)
    assert out.data[0, 0].max() - out.data[0, 0].min() > 0.4


def test_saturation_step_unset_option_is_native_but_zero_is_grey():
    # An UNSET option (None / "") means "no change" (native). An EXPLICIT 0 means
    # full desaturation (greyscale) — the slider's left endpoint — so the live
    # commit and a recipe replay of the same option agree.
    data = np.tile(np.array([0.6, 0.4, 0.2], np.float32), (8, 8, 1))
    for unset in (None, ""):
        out = SaturationStep(None).apply(AstroImage(data), unset)
        assert np.allclose(out.data, data, atol=1e-6)          # native = no change
    grey = SaturationStep(None).apply(AstroImage(data), 0.0).data
    assert np.allclose(grey[..., 0], grey[..., 1])             # explicit 0 -> greyscale
    assert np.allclose(grey[..., 1], grey[..., 2])


def test_noise_sharpen_fallback_changes_image():
    rng = np.random.default_rng(0)
    img = AstroImage(np.clip(0.5 + rng.normal(0, 0.1, (24, 24, 3)), 0, 1).astype(np.float32))
    out = NoiseSharpenStep(rcastro=None).apply(img, "medium")
    assert out.data.shape == img.data.shape
    assert not np.allclose(out.data, img.data)


def test_noise_sharpen_rcastro_strength_per_preset():
    img = AstroImage(np.random.rand(8, 8, 3).astype(np.float32))
    calls = []

    def fake(args):
        calls.append(args)
        write_temp_fits(img, args[args.index("-o") + 1])

    def denoise_strength(option):
        calls.clear()
        step = NoiseSharpenStep(rcastro=RCAstro("/fake/rc-astro"))
        step._runner = fake
        step.apply(img, option)
        args = calls[0]
        assert args[args.index("--no-banner") + 1] == "nxt"   # denoise product
        return float(args[args.index("--denoise") + 1])

    assert denoise_strength("light") == 0.75
    assert denoise_strength("medium") == 0.90
    assert denoise_strength("strong") == 0.95


def test_noise_sharpen_fallback_strength_unchanged():
    from nocturne.steps import noise_sharpen as ns
    assert ns._TV_LEVELS == {"light": 0.4, "medium": 0.7, "strong": 0.9}


def test_noise_engine_resolution_matrix():
    import numpy as np
    from nocturne.core.image import AstroImage
    from nocturne.steps.noise_sharpen import NoiseSharpenStep

    img = AstroImage(np.random.rand(8, 8, 3).astype(np.float32))

    class FakeRC:
        def __init__(self): self.called = False
        def denoise(self, image, strength, runner=None):
            self.called = True; return image

    class FakeGX:
        def __init__(self): self.called = False
        def denoise(self, image, strength, runner=None):
            self.called = True; return image

    def run(option, rc, gx):
        r, g = (FakeRC() if rc else None), (FakeGX() if gx else None)
        NoiseSharpenStep(r, g).apply(img, option)
        return (r.called if r else False), (g.called if g else False)

    # both installed -> honour the chosen engine
    assert run({"engine": "rcastro", "level": "medium"}, True, True) == (True, False)
    assert run({"engine": "graxpert", "level": "medium"}, True, True) == (False, True)
    # legacy bare string / no engine -> prefer RC-Astro
    assert run("medium", True, True) == (True, False)
    # only the OTHER engine installed -> fall back to it
    assert run({"engine": "rcastro", "level": "medium"}, False, True) == (False, True)
    assert run({"engine": "graxpert", "level": "medium"}, True, False) == (True, False)


def test_noise_neither_engine_falls_back_to_tv():
    import numpy as np
    from nocturne.core.image import AstroImage
    from nocturne.steps.noise_sharpen import NoiseSharpenStep
    rng = np.random.default_rng(0)
    img = AstroImage(np.clip(0.5 + rng.normal(0, 0.1, (24, 24, 3)), 0, 1).astype(np.float32))
    out = NoiseSharpenStep(None, None).apply(img, {"engine": "graxpert", "level": "strong"})
    assert out.data.shape == img.data.shape
    assert not np.allclose(out.data, img.data)          # TV changed the image


def test_noise_graxpert_strength_per_preset():
    import numpy as np
    from nocturne.core.image import AstroImage
    from nocturne.steps.noise_sharpen import NoiseSharpenStep
    img = AstroImage(np.random.rand(8, 8, 3).astype(np.float32))
    seen = {}

    class FakeGX:
        def denoise(self, image, strength, runner=None):
            seen["s"] = strength; return image

    for level, expected in (("light", 0.5), ("medium", 0.7), ("strong", 0.9)):
        NoiseSharpenStep(None, FakeGX()).apply(img, {"engine": "graxpert", "level": level})
        assert seen["s"] == expected


def test_noise_dict_unknown_level_coerces_to_medium():
    # A hand-edited / corrupted recipe with a bad level must degrade to "medium",
    # not raise KeyError (symmetry with the legacy bare-string path).
    from nocturne.steps.noise_sharpen import parse_noise_option
    assert parse_noise_option({"engine": "graxpert", "level": "ludicrous"}) == ("graxpert", "medium")
    assert parse_noise_option({"engine": "rcastro", "level": ""}) == ("rcastro", "medium")
    assert parse_noise_option({"engine": "graxpert", "level": "strong"}) == ("graxpert", "strong")


def test_noise_recipe_option_round_trips():
    from nocturne.recipe import serialize_option, deserialize_option
    opt = {"engine": "graxpert", "level": "strong"}
    back = deserialize_option("noise_sharpen", serialize_option("noise_sharpen", opt))
    assert back == opt
    assert deserialize_option("noise_sharpen", serialize_option("noise_sharpen", "medium")) == "medium"


def test_remove_green_step_clamps_green():
    import numpy as np
    from nocturne.core.image import AstroImage
    from nocturne.steps.remove_green_step import RemoveGreenStep
    data = np.full((4, 4, 3), 0.3, dtype=np.float32)
    data[..., 1] = 0.9
    out = RemoveGreenStep().apply(AstroImage(data))   # no option -> full strength (legacy)
    assert out.data[..., 1].max() <= 0.3 + 1e-6


def test_remove_green_strength_is_a_dial():
    import numpy as np
    from nocturne.core.image import AstroImage
    from nocturne.core.color import remove_green
    data = np.full((4, 4, 3), 0.3, dtype=np.float32)
    data[..., 1] = 0.9                                  # green excess of 0.6 over avg_rb 0.3
    full = remove_green(AstroImage(data), 1.0).data[..., 1].max()
    half = remove_green(AstroImage(data), 0.5).data[..., 1].max()
    none = remove_green(AstroImage(data), 0.0).data[..., 1].max()
    assert abs(full - 0.3) < 1e-6                       # 1.0 == classic clamp to avg
    assert abs(half - 0.6) < 1e-6                       # 0.5 removes half the excess
    assert abs(none - 0.9) < 1e-6                       # 0.0 leaves green untouched
    # red/blue never touched
    assert np.allclose(remove_green(AstroImage(data), 1.0).data[..., 0], 0.3)


def test_remove_green_step_parses_float_and_legacy_option():
    import numpy as np
    from nocturne.core.image import AstroImage
    from nocturne.steps.remove_green_step import RemoveGreenStep
    data = np.full((4, 4, 3), 0.3, dtype=np.float32)
    data[..., 1] = 0.9
    img = AstroImage(data)
    assert abs(RemoveGreenStep().apply(img, 0.5).data[..., 1].max() - 0.6) < 1e-6
    assert abs(RemoveGreenStep().apply(img, "").data[..., 1].max() - 0.3) < 1e-6   # legacy full
    # recipe round-trip of the float strength
    from nocturne.recipe import serialize_option, deserialize_option
    assert deserialize_option("remove_green", serialize_option("remove_green", 0.5)) == 0.5


def test_deconvolution_free_fallback_sharpens():
    from nocturne.steps.deconvolution_step import DeconvolutionStep
    img = AstroImage(np.random.rand(20, 20, 3).astype(np.float32), is_linear=True)
    out = DeconvolutionStep().apply(img, "medium")        # no RC-Astro -> free unsharp
    assert out.data.shape == img.data.shape
    assert not np.allclose(out.data, img.data)            # sharpening changed the image


def test_deconvolution_uses_bxt_and_sharpens_stars():
    from nocturne.steps.deconvolution_step import DeconvolutionStep
    img = AstroImage(np.random.rand(8, 8, 3).astype(np.float32), is_linear=True)
    calls = []
    def fake(args):
        calls.append(args)
        write_temp_fits(img, args[args.index("-o") + 1])
    step = DeconvolutionStep(rcastro=RCAstro("/fake/rc-astro"))
    step._runner = fake
    step.apply(img, "medium")
    products = [a[a.index("--no-banner") + 1] for a in calls]
    assert products == ["bxt"]                            # BXT deconvolution
    bxt = calls[0]
    assert float(bxt[bxt.index("--sharpen-stars") + 1]) > 0   # tightens stars on linear
