import numpy as np
from astropy.io import fits


def make_star_field(shape=(80, 80), n_stars=30, seed=0, bg=0.02):
    """A float32 image (0..1) with gaussian 'stars' on a flat background."""
    rng = np.random.default_rng(seed)
    img = np.full(shape, bg, dtype=np.float32)
    ys = rng.integers(8, shape[0] - 8, n_stars)
    xs = rng.integers(8, shape[1] - 8, n_stars)
    yy, xx = np.mgrid[0:shape[0], 0:shape[1]]
    for y, x in zip(ys, xs):
        img = img + 0.8 * np.exp(-(((xx - x) ** 2 + (yy - y) ** 2) / (2 * 1.5 ** 2)))
    return np.clip(img, 0.0, 1.0).astype(np.float32)


def write_color_fits(path, lum2d, exptime=10.0):
    """Write a (3, H, W) FITS the loader reads as color (no debayer)."""
    cube = np.stack([lum2d, lum2d, lum2d], axis=0).astype(np.float32)
    hdu = fits.PrimaryHDU(cube)
    hdu.header["EXPTIME"] = exptime
    hdu.writeto(str(path), overwrite=True)


def write_cfa_fits(path, base, exptime=10.0):
    """Write a 2D GRBG mono CFA FITS from a full-res `base` (H, W) star field.
    GRBG tile: G R / B R? no -> G R (row0), B G (row1). Strong signal on the RED
    sites so extracted Ha carries the stars; weaker green/blue."""
    import numpy as np
    from astropy.io import fits
    h, w = base.shape
    cfa = np.zeros((h, w), np.float32)
    cfa[0::2, 1::2] = base[0::2, 1::2]          # R (Ha)
    cfa[0::2, 0::2] = base[0::2, 0::2] * 0.3    # G
    cfa[1::2, 1::2] = base[1::2, 1::2] * 0.3    # G
    cfa[1::2, 0::2] = base[1::2, 0::2] * 0.2    # B
    hdu = fits.PrimaryHDU((cfa * 1000).astype(np.uint16))
    hdu.header["BAYERPAT"] = "GRBG"
    hdu.header["EXPTIME"] = exptime
    hdu.writeto(str(path), overwrite=True)
