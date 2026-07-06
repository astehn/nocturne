import numpy as np
from nocturne.core.image import AstroImage
from nocturne.tools.base import write_temp_fits
from nocturne.tools.rcastro import RCAstro


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


def test_remove_stars_returns_starless_and_stars():
    import os
    img = AstroImage(np.random.rand(8, 8, 3).astype(np.float32), is_linear=False)
    captured = {}

    def fake_runner(args):
        captured["args"] = args
        out_path = args[args.index("-o") + 1]                 # starless
        write_temp_fits(AstroImage(img.data * 0.6), out_path)
        stars_path = os.path.join(os.path.dirname(out_path), "starless-sxt.fits")
        write_temp_fits(AstroImage(img.data * 0.4), stars_path)  # stars-only, beside

    rc = RCAstro("/Applications/RC-Astro/CLI/rc-astro")
    starless, stars = rc.remove_stars(img, unscreen=True, runner=fake_runner)
    assert "sxt" in captured["args"]
    assert "--stars" in captured["args"]
    assert "--unscreen" in captured["args"]
    assert starless.data.shape == (8, 8, 3)
    assert stars.data.shape == (8, 8, 3)
    assert starless.is_linear is False and stars.is_linear is False
    # RC-Astro output is flipped back to top-row-first on read.
    assert np.allclose(starless.data, (img.data * 0.6)[::-1], atol=1e-5)
    assert np.allclose(stars.data, (img.data * 0.4)[::-1], atol=1e-5)


def test_rcastro_corrects_vertical_flip():
    # The adapter flips RC-Astro's FITS output vertically (bottom-row-first ->
    # top-row-first), so the returned array is the disk content reversed.
    img = AstroImage(np.random.rand(6, 6, 3).astype(np.float32))
    disk = np.zeros((6, 6, 3), np.float32)
    disk[0] = 1.0  # bright row at index 0 on disk

    def fake(args):
        write_temp_fits(AstroImage(disk.copy()), args[args.index("-o") + 1])

    out = RCAstro("/fake").deconvolve(
        img, sharpen_stars=0.0, sharpen_nonstellar=0.5, runner=fake
    )
    assert np.allclose(out.data, disk[::-1], atol=1e-5)


def test_remove_stars_omits_unscreen_by_default():
    img = AstroImage(np.random.rand(8, 8, 3).astype(np.float32))
    captured = {}

    def fake_runner(args):
        import os
        captured["args"] = args
        out_path = args[args.index("-o") + 1]
        write_temp_fits(img, out_path)
        write_temp_fits(img, os.path.join(os.path.dirname(out_path), "s-sxt.fits"))

    RCAstro("/fake").remove_stars(img, runner=fake_runner)
    assert "--unscreen" not in captured["args"]
