import numpy as np
from seestar_processor.core.image import AstroImage
from seestar_processor.tools.base import write_temp_fits
from seestar_processor.tools.rcastro import RCAstro


def _capture_and_write(img, factor, captured):
    def fake_runner(args):
        captured["args"] = args
        out_path = args[args.index("-o") + 1]
        write_temp_fits(AstroImage(img.data * factor), out_path)
    return fake_runner


def test_deconvolve_invokes_bxt_with_sharpening():
    img = AstroImage(np.random.rand(8, 8, 3).astype(np.float32))
    captured = {}
    rc = RCAstro("/Applications/RC-Astro/CLI/rc-astro")
    out = rc.deconvolve(
        img, sharpen_stars=0.1, sharpen_nonstellar=0.75,
        runner=_capture_and_write(img, 1.0, captured),
    )
    args = captured["args"]
    assert "bxt" in args
    assert "--no-banner" in args
    assert "--overwrite" in args
    assert args[args.index("--sharpen-stars") + 1] == "0.1"
    assert args[args.index("--sharpen-nonstellar") + 1] == "0.75"
    assert out.data.shape == (8, 8, 3)


def test_denoise_invokes_nxt_with_strength():
    img = AstroImage(np.random.rand(8, 8, 3).astype(np.float32))
    captured = {}
    rc = RCAstro("/fake/rc-astro")
    out = rc.denoise(img, strength=0.8, runner=_capture_and_write(img, 1.0, captured))
    args = captured["args"]
    assert "nxt" in args
    assert args[args.index("--denoise") + 1] == "0.8"
    assert out.data.shape == (8, 8, 3)


def test_preserves_is_linear():
    img = AstroImage(np.random.rand(8, 8, 3).astype(np.float32), is_linear=True)
    rc = RCAstro("/fake/rc-astro")
    out = rc.denoise(img, 0.5, runner=_capture_and_write(img, 0.9, {}))
    assert out.is_linear is True
