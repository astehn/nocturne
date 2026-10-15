import pytest
import os
import sys
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
        with open(base + ".wcs", "w", encoding="utf-8") as f:
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
        open(base + ".wcs", "w", encoding="utf-8").write(_WCS_TEXT)
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


# A messy but realistic ASTAP .wcs: value-only cards we need, plus the long
# PLTSOLVD comment / COMMENT / CONTINUE lines that make astropy's strict reader
# choke ("CONTINUE cards must have string values"). The tolerant parser must
# still extract the WCS and never raise.
_MESSY_WCS = (
    "CTYPE1  = 'RA---TAN'\n"
    "CTYPE2  = 'DEC--TAN'\n"
    "CRPIX1  =           1920.00000\n"
    "CRPIX2  =           1080.00000\n"
    "CRVAL1  =        314.750000000\n"
    "CRVAL2  =         44.310000000\n"
    "CD1_1   =    -0.001038000000000\n"
    "CD1_2   =     0.000000000000000\n"
    "CD2_1   =     0.000000000000000\n"
    "CD2_2   =     0.001038000000000\n"
    "PLTSOLVD=                    T / Astrometric solution found by ASTAP using D05 with 312 stars matched over field\n"
    "COMMENT  Solved by ASTAP. FOV 4.0 x 2.2 deg. Camera IMX585. Nothing here should break the parse.\n"
    "CONTINUE  '' / a stray continue card\n"
    "END\n"
)


def _write(tmp_path, text, name="solve.wcs"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p)


def test_parse_tolerant_of_messy_astap_wcs(tmp_path):
    res = ASTAP("/x/astap")._parse(_write(tmp_path, _MESSY_WCS))
    assert res.solved is True
    assert abs(res.center_ra_deg - 314.75) < 1e-6
    assert abs(res.center_dec_deg - 44.31) < 1e-6
    assert abs(res.pixscale_arcsec - 3.7368) < 0.05          # 0.001038 deg/px * 3600
    assert res.wcs is not None


def test_parse_pltsolvd_false_is_unsolved(tmp_path):
    text = _MESSY_WCS.replace("PLTSOLVD=                    T", "PLTSOLVD=                    F")
    res = ASTAP("/x/astap")._parse(_write(tmp_path, text))
    assert res.solved is False


def test_parse_garbage_wcs_returns_unsolved_without_raising(tmp_path):
    res = ASTAP("/x/astap")._parse(_write(tmp_path, "not a fits header at all\njust junk\n"))
    assert res.solved is False                               # graceful, no exception


def test_write_solve_fits_is_mono_with_header_cards(tmp_path):
    from astropy.io import fits
    from nocturne.tools.astap import _write_solve_fits
    out = str(tmp_path / "s.fits")
    _write_solve_fits(_img(), out, {"OBJCTRA": "20 59 15", "FOCALLEN": 160.0})
    with fits.open(out) as hdul:
        assert hdul[0].data.ndim == 2                       # mono, not 3-plane
        assert hdul[0].header["OBJCTRA"] == "20 59 15"      # pointing card written
        assert float(hdul[0].header["FOCALLEN"]) == 160.0   # scale card written


def test_solve_with_header_pointing_omits_radec_flags():
    seen = {}
    def fake_runner(args, cwd):
        seen["args"] = args
        open(args[args.index("-o") + 1] + ".wcs", "w", encoding="utf-8").write(_WCS_TEXT)
        return 0
    ASTAP("/x/astap").solve(_img(), fov_deg=2.0, ra_hours=20.98, dec_deg=44.3,
                            header_cards={"OBJCTRA": "20 59 15", "FOCALLEN": 160.0},
                            runner=fake_runner)
    a = seen["args"]
    assert "-ra" not in a and "-spd" not in a    # header pointing is authoritative
    assert "-fov" in a                            # scale hint still passed as a safety net


def test_solve_failure_captures_astap_message(tmp_path):
    def fake_runner(args, cwd):
        import os
        with open(os.path.join(cwd, "_astap_out.txt"), "w", encoding="utf-8") as f:
            f.write("no star database found for this field of view\n")
        return 1                                            # no .wcs written
    res = ASTAP("/x/astap").solve(_img(), runner=fake_runner)
    assert res.solved is False
    assert "no star database" in res.message


_INI = (
    "PLTSOLVD=T\n"
    "CRPIX1=792\n" "CRPIX2=1772\n"
    "CRVAL1=313.9\n" "CRVAL2=43.9\n"
    "CD1_1=-0.001038\n" "CD1_2=0\n" "CD2_1=0\n" "CD2_2=0.001038\n"
)


def test_solve_reads_solution_from_ini_when_no_wcs():
    # ASTAP wrote its .ini solution (KEY=value) but no .wcs — must still be read.
    def fake_runner(args, cwd):
        base = args[args.index("-o") + 1]
        open(base + ".ini", "w", encoding="utf-8").write(_INI)
        return 0
    res = ASTAP("/x/astap").solve(_img(), runner=fake_runner)
    assert res.solved is True
    assert abs(res.center_ra_deg - 313.9) < 1e-6
    assert res.wcs is not None                              # CTYPE injected, WCS built


def test_solve_reads_solution_from_updated_input_header():
    # ASTAP wrote the solution back into the input FITS header (no sidecar).
    from astropy.io import fits
    def fake_runner(args, cwd):
        in_fits = args[args.index("-f") + 1]
        with fits.open(in_fits, mode="update") as h:
            hdr = h[0].header
            hdr["CRPIX1"] = 792; hdr["CRPIX2"] = 1772
            hdr["CRVAL1"] = 313.9; hdr["CRVAL2"] = 43.9
            hdr["CD1_1"] = -0.001038; hdr["CD1_2"] = 0.0
            hdr["CD2_1"] = 0.0; hdr["CD2_2"] = 0.001038
            hdr["CTYPE1"] = "RA---TAN"; hdr["CTYPE2"] = "DEC--TAN"; hdr["PLTSOLVD"] = "T"
        return 0
    res = ASTAP("/x/astap").solve(_img(), runner=fake_runner)
    assert res.solved is True
    assert abs(res.center_ra_deg - 313.9) < 1e-6


def test_solve_failure_message_lists_produced_files():
    def fake_runner(args, cwd):
        import os
        open(os.path.join(cwd, "solve.001"), "w", encoding="utf-8").write("junk")   # not a solution
        return 1
    res = ASTAP("/x/astap").solve(_img(), runner=fake_runner)
    assert res.solved is False
    assert "produced:" in res.message                       # diagnostic lists what ASTAP wrote


def test_solve_surfaces_swallowed_parse_error(monkeypatch):
    # A valid .wcs is produced, but building the WCS raises (as it apparently does
    # in the packaged app). The failure message must NAME the real exception.
    monkeypatch.setattr("astropy.wcs.WCS",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("wcslib exploded")))

    def fake_runner(args, cwd):
        base = args[args.index("-o") + 1]
        with open(base + ".wcs", "w", encoding="utf-8") as f:
            f.write(_WCS_TEXT)
        return 0

    res = ASTAP("/x/astap").solve(_img(), runner=fake_runner)
    assert res.solved is False
    assert "RuntimeError" in res.message
    assert "wcslib exploded" in res.message


def test_hint_infers_ra_units_rather_than_assuming_hours():
    """fits_io fills "ra" from OBJCTRA *or* RA, and they differ: OBJCTRA is
    sexagesimal hours, a bare RA card is decimal degrees. Parsing a Seestar's
    RA = 314.125 as hours gave 314 "hours" — a nonsense search centre. Dormant
    only because those files also carry pointing in solve_cards.
    """
    from nocturne.tools.astap import hint_from_metadata

    # NGC 7000 is RA 20.94 h == 314.1 deg; every spelling must agree.
    deg = hint_from_metadata({"ra": 314.125005, "dec": 43.9825})
    sexagesimal = hint_from_metadata({"ra": "20 56 30", "dec": "+44 20 00"})
    hours = hint_from_metadata({"ra": 20.94, "dec": 44.33})
    for got in (deg, sexagesimal, hours):
        assert got is not None
        assert 20.8 < got[0] < 21.1, got

    assert hint_from_metadata({"ra": "", "dec": ""}) is None
    assert hint_from_metadata({"ra": "rubbish", "dec": "rubbish"}) is None


def test_solve_is_cancellable_and_binds_the_process(tmp_path):
    """The Cancel button set the token, the UI said "Cancelling...", and ASTAP
    ran to completion regardless: the runner used subprocess.run, which cannot
    be interrupted. It now binds the child to the ambient token like every other
    external tool."""
    import subprocess
    from nocturne.core.tasks import CancelToken, Cancelled, clear_ambient, set_ambient
    from nocturne.tools.astap import _run_astap

    token = CancelToken()
    bound = []
    real_popen = subprocess.Popen

    class _Spy(real_popen):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)

    def _bind(proc):
        bound.append(proc)
        CancelToken.bind_process(token, proc)

    token.bind_process = _bind          # observe that the child is registered
    set_ambient(token)
    try:
        token.cancel()                  # already cancelled before the run starts
        with pytest.raises(Cancelled):
            # cwd must be a tmp dir, never ".": _run_astap writes _astap_out.txt
            # into cwd, so "." dropped a stray file in the repo root on every run
            _run_astap([sys.executable, "-c", "import time; time.sleep(5)"],
                       cwd=str(tmp_path), timeout=30)
    finally:
        clear_ambient()
    assert bound, "the solver process must be bound to the cancel token"


def test_solve_times_out_rather_than_hanging_forever(tmp_path):
    """A solver still grinding after minutes has effectively failed, and leaving
    it running holds the worker thread forever."""
    from nocturne.tools.astap import _run_astap
    from nocturne.tools.base import ToolError

    with pytest.raises(ToolError) as e:
        _run_astap([sys.executable, "-c", "import time; time.sleep(10)"],
                   cwd=str(tmp_path), timeout=0.5)
    assert "did not finish" in str(e.value) or "0 s" in str(e.value)


# --- scale-hint fallback -----------------------------------------------------

class _Recorder:
    """Records every solve attempt; succeeds only when told to."""
    def __init__(self, succeed_on=None):
        self.calls = []
        self._succeed_on = succeed_on          # index of the call that solves
        self.images = []                       # the pixels each attempt was handed
    def solve(self, img, fov_deg=None, ra_hours=None, dec_deg=None, header_cards=None):
        self.calls.append(fov_deg)
        self.images.append(np.array(img.data, copy=True))
        ok = self._succeed_on is not None and len(self.calls) - 1 == self._succeed_on
        return SolveResult(ok, object() if ok else None, 0.0, 0.0, 3.6)


_SEESTAR_META = {}                              # no optics -> profile fallback
_HEADER_META = {"focal_length": 400.0, "pixel_size": 3.76}


def test_a_header_scale_is_used_and_never_retried_blind():
    """A measured scale is not a guess, so a blind retry would only waste
    seconds. (A flat frame has no noise floor to restore, so this is also the
    one-attempt case.)"""
    from nocturne.tools.astap import solve_with_scale_fallback
    rec = _Recorder(succeed_on=None)            # never solves
    res, source = solve_with_scale_fallback(rec, _img(), _HEADER_META, 2000)
    assert not res.solved
    assert source == "header"
    assert len(rec.calls) == 1, "nothing to retry on a frame with no stars"
    assert None not in rec.calls, "a header scale is never dropped"


def test_an_assumed_scale_that_fails_is_dropped_and_retried_blind():
    """The Seestar profile is right for a Seestar and wrong for anything else —
    a rig at 0.05\"/px handed 3.66\"/px searches 70x off and fails. Without this
    the fallback turns slow successes into fast failures on other people's data."""
    from nocturne.tools.astap import solve_with_scale_fallback
    rec = _Recorder(succeed_on=1)               # fails with a hint, solves without
    res, source = solve_with_scale_fallback(rec, _img(), _SEESTAR_META, 2000)
    assert res.solved
    assert source == "blind"
    assert len(rec.calls) == 2
    assert rec.calls[0] is not None, "first attempt uses the profile scale"
    assert rec.calls[1] is None, "the retry drops the scale entirely"


def test_an_assumed_scale_that_works_does_not_retry():
    """The common case — a Seestar master. One attempt, and it says so."""
    from nocturne.tools.astap import solve_with_scale_fallback
    rec = _Recorder(succeed_on=0)
    res, source = solve_with_scale_fallback(rec, _img(), _SEESTAR_META, 2000)
    assert res.solved and source == "profile"
    assert len(rec.calls) == 1


def test_both_attempts_failing_reports_the_original_result():
    """Not the blind one: the first attempt's ASTAP message is the more useful
    diagnostic, and 'profile' is what was actually assumed."""
    from nocturne.tools.astap import solve_with_scale_fallback
    rec = _Recorder(succeed_on=None)
    res, source = solve_with_scale_fallback(rec, _img(), _SEESTAR_META, 2000)
    assert not res.solved
    assert source == "profile"
    assert len(rec.calls) == 2, "it still tried blind before giving up"


# --- noise-floor retry ---------------------------------------------------------
#
# ASTAP picks the ~500 stars it matches by SNR. Strong noise reduction strips the
# noise floor unevenly, so on a finished picture SNR stops ranking stars by
# brightness and the picked stars no longer overlap the catalogue's brightest.
# Measured on his IC 1805 (2026-10-15): 77% of ASTAP's picks were among the
# field's 649 brightest Gaia stars before Noise Reduction, 57% after, and the
# solve failed from that step on at the correct header scale.

def _star_field(noise_sigma: float, seed: int = 1) -> AstroImage:
    """A finished-looking frame: flat sky, 60 stars, and as much pixel noise as
    asked for — ~0 is what a strong denoise leaves."""
    rng = np.random.default_rng(seed)
    h, w = 400, 400
    yy, xx = np.mgrid[0:h, 0:w]
    lum = np.full((h, w), 0.10, np.float32)
    for _ in range(60):
        cy, cx = rng.uniform(10, h - 10), rng.uniform(10, w - 10)
        peak = rng.uniform(0.2, 0.9)
        lum += (peak * np.exp(-((yy - cy) ** 2 + (xx - cx) ** 2) / (2 * 2.0 ** 2))).astype(np.float32)
    lum += rng.normal(0, noise_sigma, lum.shape).astype(np.float32)
    return AstroImage(np.repeat(lum[..., None], 3, axis=2), is_linear=False)


def _pixel_noise(a: np.ndarray) -> float:
    lum = a.mean(axis=2) if a.ndim == 3 else a
    d = lum[:, 1:] - lum[:, :-1]
    return float(1.4826 * np.median(np.abs(d - np.median(d))) / np.sqrt(2))


def _span(a: np.ndarray) -> float:
    lum = a.mean(axis=2) if a.ndim == 3 else a
    return float(np.percentile(lum, 99.9) - np.median(lum))


def test_a_denoised_frame_that_fails_is_retried_with_its_noise_floor_restored():
    """His IC 1805: correct header scale, ASTAP 'No solution found', solved at
    once with a noise floor put back. A header scale must not stop the retry —
    the scale was never the problem."""
    from nocturne.tools.astap import solve_with_scale_fallback
    img = _star_field(noise_sigma=0.0005)
    before = img.data.copy()
    rec = _Recorder(succeed_on=1)
    res, source = solve_with_scale_fallback(rec, img, _HEADER_META, 400)
    assert res.solved
    assert source == "header", "the scale used was still the header's"
    assert len(rec.calls) == 2
    assert rec.calls[0] == rec.calls[1] and rec.calls[1] is not None, \
        "the retry keeps the measured scale"
    assert _pixel_noise(rec.images[0]) < 0.002, "first attempt: the frame as it is"
    floor = _pixel_noise(rec.images[1]) / _span(rec.images[1])
    assert 0.015 < floor < 0.03, f"retry noise floor {floor:.4f} of the star range"
    np.testing.assert_array_equal(img.data, before)   # the user's image is untouched


def test_a_frame_that_already_has_its_noise_is_not_retried():
    """Nothing to restore, so a second attempt would be the first one again."""
    from nocturne.tools.astap import solve_with_scale_fallback
    img = _star_field(noise_sigma=0.03)               # ~3.5% of the range
    rec = _Recorder(succeed_on=None)
    res, source = solve_with_scale_fallback(rec, img, _HEADER_META, 400)
    assert not res.solved and source == "header"
    assert len(rec.calls) == 1


def test_a_solved_frame_is_never_handed_noise():
    from nocturne.tools.astap import solve_with_scale_fallback
    img = _star_field(noise_sigma=0.0005)
    rec = _Recorder(succeed_on=0)
    res, _source = solve_with_scale_fallback(rec, img, _HEADER_META, 400)
    assert res.solved and len(rec.calls) == 1
    np.testing.assert_array_equal(rec.images[0], img.data)


def test_an_assumed_scale_tries_the_noise_floor_before_going_blind():
    """The noise retry is cheap and keeps the hint; blind is the last resort."""
    from nocturne.tools.astap import solve_with_scale_fallback
    img = _star_field(noise_sigma=0.0005)
    rec = _Recorder(succeed_on=2)
    res, source = solve_with_scale_fallback(rec, img, _SEESTAR_META, 400)
    assert res.solved and source == "blind"
    assert len(rec.calls) == 3
    assert rec.calls[0] is not None and rec.calls[1] == rec.calls[0]
    assert rec.calls[2] is None


def test_a_retry_that_also_fails_reports_the_first_attempt():
    """The caller gets the frame as the user made it, not the noisy copy:
    the first attempt's ASTAP message is the honest diagnostic."""
    from nocturne.tools.astap import solve_with_scale_fallback

    class _Messages(_Recorder):
        def solve(self, img, **kw):
            super().solve(img, **kw)
            return SolveResult(False, None, 0.0, 0.0, 0.0,
                               message=f"attempt {len(self.calls) - 1}")

    rec = _Messages()
    res, source = solve_with_scale_fallback(rec, _star_field(0.0005), _HEADER_META, 400)
    assert len(rec.calls) == 2, "the noise retry ran"
    assert not res.solved and source == "header"
    assert res.message == "attempt 0"


def test_a_crushed_black_sky_still_reaches_astap_with_the_whole_floor(tmp_path):
    """_write_solve_fits clips at zero. On a sky crushed to black, half of
    zero-mean noise is negative and would be clipped away — measured on a
    dark sky: a 0.0060 target arrived as 0.0025-0.0029, ~1% of the range,
    below M 16's 1.4% rescue level."""
    from astropy.io import fits
    from nocturne.tools.astap import _NOISE_FLOOR, _write_solve_fits, with_noise_floor
    img = _star_field(noise_sigma=0.0)
    img = AstroImage(np.clip(img.data - 0.10, 0.0, None), is_linear=False)  # sky at 0
    floored = with_noise_floor(img)
    assert floored is not None
    path = str(tmp_path / "s.fits")
    _write_solve_fits(floored, path, None)
    handed = fits.getdata(path).astype(np.float32)
    target = _NOISE_FLOOR * _span(img.data)
    assert _pixel_noise(handed) >= 0.9 * target, \
        f"ASTAP got {_pixel_noise(handed):.5f} of a {target:.5f} floor"


@pytest.mark.parametrize("data", [
    np.full((1, 1), 0.5, np.float32),
    np.full((5, 1), 0.5, np.float32),
    np.full((1, 5), 0.5, np.float32),
    np.where(np.eye(50, dtype=bool), np.nan, 0.2).astype(np.float32),
], ids=["1x1", "5x1", "1x5", "nan"])
def test_degenerate_frames_get_no_retry_and_no_warnings(data):
    import warnings
    from nocturne.tools.astap import with_noise_floor
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert with_noise_floor(AstroImage(data, is_linear=False)) is None


def test_the_retry_copy_is_reproducible():
    from nocturne.tools.astap import with_noise_floor
    img = _star_field(noise_sigma=0.0005)
    a, b = with_noise_floor(img), with_noise_floor(img)
    assert a.data.tobytes() == b.data.tobytes()
