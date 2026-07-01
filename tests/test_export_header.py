import numpy as np
from astropy.io import fits
from seestar_processor.core.image import AstroImage
from seestar_processor.core.export import save_fits


def test_save_fits_writes_header_keys(tmp_path):
    img = AstroImage(np.zeros((4, 5, 3), np.float32), is_linear=True)
    p = tmp_path / "m.fits"
    save_fits(img, str(p), header={"NSUBS": 12, "EXPTIME": 120.0})
    with fits.open(str(p)) as hdul:
        assert hdul[0].header["NSUBS"] == 12
        assert hdul[0].header["EXPTIME"] == 120.0
