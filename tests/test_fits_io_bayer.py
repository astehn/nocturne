import numpy as np
from astropy.io import fits
from seestar_processor.core.fits_io import _bayer_pattern, load_fits


def test_bayer_pattern_reads_header():
    hdr = fits.Header()
    hdr["BAYERPAT"] = "GRBG"
    assert _bayer_pattern(hdr) == "GRBG"


def test_bayer_pattern_falls_back_when_missing_or_invalid():
    assert _bayer_pattern(fits.Header()) == "GRBG"          # instrument default
    bad = fits.Header()
    bad["BAYERPAT"] = "XYZW"
    assert _bayer_pattern(bad) == "GRBG"


def test_load_fits_debayers_with_header_pattern(tmp_path):
    # Construct a raw CFA frame where only the GREEN sites of a GRBG mosaic are
    # bright. GRBG layout (top-left origin): [0,0]=G [0,1]=R [1,0]=B [1,1]=G.
    cfa = np.zeros((8, 8), np.float32)
    cfa[0::2, 0::2] = 1000.0   # G
    cfa[1::2, 1::2] = 1000.0   # G
    p = tmp_path / "grbg.fit"
    hdr = fits.Header()
    hdr["BAYERPAT"] = "GRBG"
    fits.PrimaryHDU(cfa.astype(np.uint16), header=hdr).writeto(str(p))

    img = load_fits(str(p), normalize=False).data
    r, g, b = img[..., 0].mean(), img[..., 1].mean(), img[..., 2].mean()
    # Correct GRBG demosaic -> green dominates; red/blue interpolate to ~0.
    assert g > 500.0
    assert r < 100.0 and b < 100.0
