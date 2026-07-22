import os
import numpy as np
from nocturne.core.image import AstroImage
from nocturne.tools.astap import ASTAP, SolveResult, hint_from_metadata

# A minimal but real ASTAP .wcs sidecar (FITS-keyword ASCII, 80-char cards).
_WCS_TEXT = (
    "CTYPE1  = 'RA---TAN'\n"
    "CTYPE2  = 'DEC--TAN'\n"
    "CRPIX1  =                960.0\n"
    "CRPIX2  =                540.0\n"
    "CRVAL1  =              314.75\n"
    "CRVAL2  =               44.31\n"
    "CD1_1   =           -0.0005556\n"
    "CD1_2   =                  0.0\n"
    "CD2_1   =                  0.0\n"
    "CD2_2   =            0.0005556\n"
    "PLTSOLVD=                    T\n"
)


def _img():
    return AstroImage(np.zeros((1080, 1920, 3), np.float32), is_linear=False)


def test_solve_parses_wcs_on_success():
    def fake_runner(args, cwd):
        # ASTAP writes <base>.wcs next to the input; find the -o base.
        base = args[args.index("-o") + 1]
        with open(base + ".wcs", "w") as f:
            f.write(_WCS_TEXT)
        return 0
    res = ASTAP("/x/astap").solve(_img(), fov_deg=2.0, runner=fake_runner)
    assert res.solved is True
    assert abs(res.center_ra_deg - 314.75) < 1e-6
    assert abs(res.center_dec_deg - 44.31) < 1e-6
    assert abs(res.pixscale_arcsec - 2.0) < 0.05          # 0.0005556 deg/px * 3600
    assert res.wcs is not None


def test_solve_no_solution_returns_unsolved():
    def fake_runner(args, cwd):
        return 1                                           # no .wcs written, nonzero exit
    res = ASTAP("/x/astap").solve(_img(), runner=fake_runner)
    assert res.solved is False
    assert res.wcs is None


def test_solve_passes_fov_and_hint_flags():
    seen = {}
    def fake_runner(args, cwd):
        seen["args"] = args
        base = args[args.index("-o") + 1]
        open(base + ".wcs", "w").write(_WCS_TEXT)
        return 0
    ASTAP("/x/astap").solve(_img(), fov_deg=2.0, ra_hours=20.98, dec_deg=44.3, runner=fake_runner)
    a = seen["args"]
    assert a[0] == "/x/astap"
    assert "-fov" in a and a[a.index("-fov") + 1] == "2.0"
    assert "-ra" in a and a[a.index("-ra") + 1] == "20.98"
    assert "-spd" in a and a[a.index("-spd") + 1] == "134.3"   # dec + 90


def test_hint_from_metadata_parses_sexagesimal():
    ra_h, dec_d = hint_from_metadata({"ra": "20 58 47", "dec": "+44 18 36"})
    assert abs(ra_h - 20.9797) < 1e-3
    assert abs(dec_d - 44.31) < 1e-2
    assert hint_from_metadata({}) is None
