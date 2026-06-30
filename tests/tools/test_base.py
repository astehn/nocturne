import sys
import numpy as np
import pytest
from seestar_processor.core.image import AstroImage
from seestar_processor.tools.base import (
    write_temp_fits, read_fits_array, run_cli, ToolError,
)


def test_fits_roundtrip_color(tmp_path):
    img = AstroImage(np.random.rand(8, 8, 3).astype(np.float32))
    p = tmp_path / "t.fits"
    write_temp_fits(img, str(p))
    back = read_fits_array(str(p))
    assert back.data.shape == (8, 8, 3)
    assert np.allclose(back.data, img.data, atol=1e-5)


def test_run_cli_raises_on_failure():
    with pytest.raises(ToolError) as e:
        run_cli([sys.executable, "-c", "import sys; sys.exit(3)"])
    assert e.value.returncode == 3


def test_run_cli_succeeds():
    run_cli([sys.executable, "-c", "print('ok')"])  # no exception
