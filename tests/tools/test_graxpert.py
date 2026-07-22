import os

import numpy as np
from nocturne.core.image import AstroImage
from nocturne.tools.base import write_temp_fits
from nocturne.tools.graxpert import GraXpert


def _writes_output(img, factor):
    def fake_runner(args):
        out_path = args[args.index("-output") + 1]
        write_temp_fits(AstroImage(img.data * factor), out_path)
    return fake_runner


def test_background_extraction_invokes_cli_and_reads_output(tmp_path):
    img = AstroImage(np.random.rand(8, 8, 3).astype(np.float32))
    captured = {}

    def fake_runner(args):
        captured["args"] = args
        out_path = args[args.index("-output") + 1]
        write_temp_fits(AstroImage(img.data * 0.5), out_path)

    gx = GraXpert(binary_path="/fake/graxpert")
    result = gx.background_extraction(img, strength=0.5, runner=fake_runner)

    assert captured["args"][0] == "/fake/graxpert"
    assert "-cli" in captured["args"]                       # mandatory for CLI use
    assert "background-extraction" in captured["args"]
    assert result.data.shape == (8, 8, 3)
    assert np.allclose(result.data, img.data * 0.5, atol=1e-5)


def test_denoise_uses_denoising_command():
    img = AstroImage(np.random.rand(8, 8, 3).astype(np.float32))
    captured = {}

    def fake_runner(args):
        captured["args"] = args
        out_path = args[args.index("-output") + 1]
        write_temp_fits(AstroImage(img.data * 0.9), out_path)

    gx = GraXpert(binary_path="/fake/graxpert")
    result = gx.denoise(img, strength=0.5, runner=fake_runner)

    assert "-cli" in captured["args"]
    assert "denoising" in captured["args"]
    assert result.data.shape == (8, 8, 3)


def test_finds_output_with_unexpected_name():
    img = AstroImage(np.random.rand(8, 8, 3).astype(np.float32))

    def fake_runner(args):
        # GraXpert writes a differently-named file (not the requested -output).
        out_path = args[args.index("-output") + 1]
        alt = os.path.join(os.path.dirname(out_path), "in_GraXpert.fits")
        write_temp_fits(AstroImage(img.data * 0.3), alt)

    gx = GraXpert(binary_path="/fake/graxpert")
    result = gx.background_extraction(img, strength=0.2, runner=fake_runner)
    assert result.data.shape == (8, 8, 3)
    assert np.allclose(result.data, img.data * 0.3, atol=1e-5)


def test_preserves_is_linear():
    img = AstroImage(np.random.rand(8, 8, 3).astype(np.float32), is_linear=True)
    gx = GraXpert(binary_path="/fake/graxpert")
    out = gx.background_extraction(img, 0.5, runner=_writes_output(img.copy(), 0.7))
    assert out.is_linear is True


def _capture():
    calls = []

    def fake(args):
        calls.append(args)
        # write an output file where GraXpert would (out + ".fits") so _find_output succeeds
        out = args[args.index("-output") + 1]
        write_temp_fits(AstroImage(np.zeros((4, 4), np.float32)), out + ".fits")
    return calls, fake


def test_denoise_uses_strength_not_smoothing():
    img = AstroImage(np.random.rand(4, 4).astype(np.float32))
    calls, fake = _capture()
    GraXpert("/fake/graxpert").denoise(img, 0.7, runner=fake)
    args = calls[0]
    assert args[args.index("-cmd") + 1] == "denoising"
    assert "-strength" in args and args[args.index("-strength") + 1] == "0.7"
    assert "-smoothing" not in args


def test_background_extraction_still_uses_smoothing():
    img = AstroImage(np.random.rand(4, 4).astype(np.float32))
    calls, fake = _capture()
    GraXpert("/fake/graxpert").background_extraction(img, 0.3, runner=fake)
    args = calls[0]
    assert args[args.index("-cmd") + 1] == "background-extraction"
    assert "-smoothing" in args and args[args.index("-smoothing") + 1] == "0.3"
    assert "-strength" not in args


def test_graxpert_preserves_input_metadata():
    # GraXpert changes pixels, not headers — the plate-solve hint cards (and
    # target/exposure) must survive the round-trip. Regression: read_fits_array
    # returned empty metadata, silently dropping solve_cards after Background.
    img = AstroImage(np.random.rand(8, 8, 3).astype(np.float32), is_linear=True,
                     metadata={"target": "NGC 281",
                               "solve_cards": {"OBJCTRA": "00 53 06", "FOCALLEN": 160.0}})

    def fake_runner(args):
        write_temp_fits(AstroImage(img.data * 0.5), args[args.index("-output") + 1])

    out = GraXpert("/fake/graxpert").background_extraction(img, 0.5, runner=fake_runner)
    assert out.metadata["target"] == "NGC 281"
    assert out.metadata["solve_cards"]["OBJCTRA"] == "00 53 06"
    assert out.is_linear is True
