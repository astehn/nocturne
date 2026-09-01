"""What the app drags in before it has opened anything.

Andreas, 2026-09-01: launching is fine on the fast machine but "on my M1 and M2
loading the application actually takes a considerable amount of time". Measured:
importing main_window took 1.01 s, and almost none of it was our code —
colour_demosaicing alone is 478 ms, pulled in at module level even though the
function wrapping it was written to be lazy.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[2]

# Heavy third-party modules that are NOT needed to show a window, with what each
# one measured and what actually needs it.
DEFERRED = {
    "colour_demosaicing": "478 ms — only needed to debayer a CFA frame",
    "skimage.restoration": "pulls scipy.stats — only needed by TV denoise",
}


def _imported_by(module: str) -> set:
    """Every module present after importing `module`, in a fresh interpreter."""
    code = (f"import sys; import {module}; "
            "print('\\n'.join(sorted(sys.modules)))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                         text=True, cwd=str(ROOT), timeout=180)
    assert out.returncode == 0, out.stderr[-2000:]
    return set(out.stdout.split())


def test_opening_the_app_does_not_load_what_it_may_never_use():
    """These load on FIRST USE now. A launch that never opens an image should
    not pay for a debayer library, and one that never denoises should not pay
    for scipy.stats."""
    loaded = _imported_by("nocturne.ui.main_window")
    early = {m: why for m, why in DEFERRED.items() if m in loaded}
    assert not early, (
        "loaded at startup though not needed to show a window: "
        + "; ".join(f"{m} ({why})" for m, why in early.items()))


def test_debayering_still_works_when_the_import_is_deferred():
    """The lazy path must actually resolve — a deferred import that raises on
    first use is worse than an eager one that works."""
    import numpy as np
    from astropy.io import fits
    import tempfile, os
    from nocturne.core.fits_io import load_fits
    d = tempfile.mkdtemp()
    p = os.path.join(d, "cfa.fits")
    hdu = fits.PrimaryHDU((np.random.rand(64, 64) * 1000).astype(np.uint16))
    hdu.header["BAYERPAT"] = "GRBG"
    hdu.writeto(p)
    img = load_fits(p)
    assert img.data.shape == (64, 64, 3), "CFA frame did not debayer"
    assert np.isfinite(img.data).all()
