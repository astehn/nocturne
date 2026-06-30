import numpy as np
from seestar_processor.core.image import AstroImage
from seestar_processor.tools.base import write_temp_fits
from seestar_processor.tools.graxpert import GraXpert


def test_background_extraction_invokes_cli_and_reads_output(tmp_path):
    img = AstroImage(np.random.rand(8, 8, 3).astype(np.float32))
    captured = {}

    def fake_runner(args):
        # GraXpert command shape: -output gives a stem; tool writes <stem>.fits
        captured["args"] = args
        out_stem = args[args.index("-output") + 1]
        # Simulate GraXpert producing a darker background-removed file.
        write_temp_fits(AstroImage(img.data * 0.5), out_stem + ".fits")

    gx = GraXpert(binary_path="/fake/graxpert")
    result = gx.background_extraction(img, strength=0.5, runner=fake_runner)

    assert "background-extraction" in captured["args"]
    assert captured["args"][0] == "/fake/graxpert"
    assert result.data.shape == (8, 8, 3)
    assert np.allclose(result.data, img.data * 0.5, atol=1e-5)
