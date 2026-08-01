import pytest
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
    p.write_text(text)
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
        open(args[args.index("-o") + 1] + ".wcs", "w").write(_WCS_TEXT)
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
        with open(os.path.join(cwd, "_astap_out.txt"), "w") as f:
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
        open(base + ".ini", "w").write(_INI)
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
        open(os.path.join(cwd, "solve.001"), "w").write("junk")   # not a solution
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
        with open(base + ".wcs", "w") as f:
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
            _run_astap(["/bin/sleep", "5"], cwd=str(tmp_path), timeout=30)
    finally:
        clear_ambient()
    assert bound, "the solver process must be bound to the cancel token"


def test_solve_times_out_rather_than_hanging_forever(tmp_path):
    """A solver still grinding after minutes has effectively failed, and leaving
    it running holds the worker thread forever."""
    from nocturne.tools.astap import _run_astap
    from nocturne.tools.base import ToolError

    with pytest.raises(ToolError) as e:
        _run_astap(["/bin/sleep", "10"], cwd=str(tmp_path), timeout=0.5)
    assert "did not finish" in str(e.value) or "0 s" in str(e.value)


# --- scale-hint fallback -----------------------------------------------------

class _Recorder:
    """Records every solve attempt; succeeds only when told to."""
    def __init__(self, succeed_on=None):
        self.calls = []
        self._succeed_on = succeed_on          # index of the call that solves
    def solve(self, img, fov_deg=None, ra_hours=None, dec_deg=None, header_cards=None):
        self.calls.append(fov_deg)
        ok = self._succeed_on is not None and len(self.calls) - 1 == self._succeed_on
        return SolveResult(ok, object() if ok else None, 0.0, 0.0, 3.6)


_SEESTAR_META = {}                              # no optics -> profile fallback
_HEADER_META = {"focal_length": 400.0, "pixel_size": 3.76}


def test_a_header_scale_is_used_and_never_retried_blind():
    """A measured scale is not a guess. Failing with it means something else is
    wrong, so a blind retry would only waste seconds."""
    from nocturne.tools.astap import solve_with_scale_fallback
    rec = _Recorder(succeed_on=None)            # never solves
    res, source = solve_with_scale_fallback(rec, _img(), _HEADER_META, 2000)
    assert not res.solved
    assert source == "header"
    assert len(rec.calls) == 1, "no retry when the scale came from the header"
    assert rec.calls[0] is not None


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
