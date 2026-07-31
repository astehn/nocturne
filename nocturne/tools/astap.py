"""ASTAP plate-solver wrapper (optional external tool, detect-and-shell-out).

Writes the given image to a temp FITS, runs ASTAP to solve it, and parses the
resulting `.wcs` sidecar into an astropy WCS. ASTAP returns a NON-ZERO exit code
when it cannot solve, so we use a returncode-returning runner (not run_cli, which
raises on nonzero) and treat the presence of a valid `.wcs`/PLTSOLVD=T as success.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass

import numpy as np

from ..core.image import AstroImage

# Whether projection (core/catalog, core/annotate) must flip y when turning a
# solved WCS position into a display-array row.
#
# CONFIRMED FALSE against a real ASTAP solve, 2026-07-31. It shipped True on the
# assumption that ASTAP returns bottom-up FITS rows while Nocturne's arrays are
# top-row-first — but astropy's world_to_pixel already returns rows in the same
# order as the array we hand it, so the extra flip mirrored EVERY annotation
# vertically.
#
# Why it survived so long: every test built its WCS synthetically, and a
# synthetic WCS is self-consistent under either convention, so the suite could
# never see it. And a mirrored overlay still looks plausible — a 2-degree nebula
# circle lands roughly over its nebula either way. It was caught only when a user
# measured two named stars' pixel positions in the running app (57 Cyg at
# 1086,1274 and 56 Cyg at 1713,1148) and every projected object turned out to sit
# at h - y instead of y.
FITS_Y_DOWN = False


@dataclass
class SolveResult:
    solved: bool
    wcs: object | None
    center_ra_deg: float
    center_dec_deg: float
    pixscale_arcsec: float
    message: str = ""            # ASTAP's own output on failure (diagnostics)


_OUT_FILE = "_astap_out.txt"


def _run_astap(args: list[str], cwd: str) -> int:
    p = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    try:                          # stash ASTAP's own words so a failure explains itself
        with open(os.path.join(cwd, _OUT_FILE), "w") as f:
            f.write((p.stdout or "") + "\n" + (p.stderr or ""))
    except OSError:
        pass
    return p.returncode


def _write_solve_fits(img: AstroImage, path: str, header_cards: dict | None) -> None:
    """Write a MONO FITS for ASTAP to solve, carrying the original pointing/scale
    header cards. ASTAP reads OBJCTRA/OBJCTDEC + FOCALLEN/XPIXSZ (etc.) from the
    header to seed the solve exactly as it does opening the original file, so a
    processed image still solves. Mono (luminance) avoids 3-plane-colour issues."""
    from astropy.io import fits
    d = np.clip(img.data.astype(np.float32), 0.0, None)
    if d.ndim == 3:
        d = d.mean(axis=2)        # luminance; ASTAP only needs star positions
    hdu = fits.PrimaryHDU(np.ascontiguousarray(d, dtype=np.float32))
    for key, value in (header_cards or {}).items():
        try:
            hdu.header[key] = value
        except Exception:
            continue              # skip any card astropy won't accept
    hdu.writeto(path, overwrite=True)


def hint_from_metadata(meta: dict) -> tuple[float, float] | None:
    """(ra_hours, dec_deg) from FITS pointing metadata, or None if absent or
    unparseable.

    The units are ambiguous by convention and must be inferred, not assumed.
    `fits_io` fills "ra" from OBJCTRA *or* RA, and those differ: OBJCTRA is
    sexagesimal HOURS ("20 56 30"), while a bare RA card is decimal DEGREES.
    Parsing a Seestar's `RA = 314.125` as hours yields 314 "hours" — a nonsense
    hint. It stayed dormant because those files also carry pointing in
    solve_cards, so the value never reached ASTAP; a file with RA but no usable
    solve_cards would have been handed a garbage search centre.

    Rule: a plain decimal above 24 can only be degrees. A sexagesimal string is
    hours, per the OBJCTRA convention."""
    ra, dec = meta.get("ra"), meta.get("dec")
    if ra in (None, "") or dec in (None, ""):
        return None
    try:
        from astropy.coordinates import Angle
        import astropy.units as u
        text = str(ra).strip()
        try:
            decimal = float(text)
        except ValueError:
            decimal = None
        if decimal is not None:
            # Decimal: degrees if it cannot be an hour angle, else trust hours.
            ra_h = decimal / 15.0 if abs(decimal) > 24.0 else decimal
        else:
            ra_h = Angle(text, unit=u.hourangle).hour
        dec_d = Angle(str(dec), unit=u.deg).deg
        return float(ra_h), float(dec_d)
    except Exception:
        return None


class ASTAP:
    def __init__(self, binary_path: str) -> None:
        self.binary_path = binary_path

    def solve(self, img: AstroImage, *, fov_deg: float | None = None,
              ra_hours: float | None = None, dec_deg: float | None = None,
              header_cards: dict | None = None, runner=None) -> SolveResult:
        runner = runner or _run_astap
        tmp = tempfile.mkdtemp(prefix="nocturne_astap_")
        try:
            in_fits = os.path.join(tmp, "solve.fits")
            base = os.path.join(tmp, "solve")
            _write_solve_fits(img, in_fits, header_cards)
            args = [self.binary_path, "-f", in_fits, "-o", base, "-wcs"]
            # Scale hint: pass -fov when we can compute it (harmless if the header
            # already carries FOCALLEN/XPIXSZ; the safety net when it doesn't).
            if fov_deg is not None:
                args += ["-fov", str(round(float(fov_deg), 4))]
            # Pointing hint: only pass RA/Dec flags when the header does NOT already
            # carry pointing — the header cards are authoritative, and our parsed
            # RA/Dec hint (degrees-vs-hours) is the fragile path best avoided.
            header_has_pointing = bool(header_cards) and any(
                k in header_cards for k in ("OBJCTRA", "RA"))
            if not header_has_pointing and ra_hours is not None and dec_deg is not None:
                args += ["-ra", str(round(float(ra_hours), 4)),
                         "-spd", str(round(float(dec_deg) + 90.0, 4))]  # south pole distance
            runner(args, tmp)
            self._last_errors = []
            res = self._read_solution(tmp, base, in_fits)
            if res is not None:
                return res
            msg = (self._output(tmp) + " | produced: " + self._listing(tmp)).strip(" |")
            if self._last_errors:
                msg += "\nparse error: " + "; ".join(self._last_errors)
            return SolveResult(False, None, 0.0, 0.0, 0.0, message=msg)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def _read_solution(self, tmp: str, base: str, in_fits: str):
        """Find ASTAP's solution wherever it landed: a `.wcs` sidecar (FITS
        cards), the `.ini` solution file (KEY=value), or the input FITS header
        ASTAP updates in place. Returns a solved SolveResult, or None (recording
        why each candidate failed in self._last_errors)."""
        import glob
        errors: list[str] = []

        def _try(header, label):
            try:
                return self._build(header)
            except Exception as e:                     # surface, don't swallow
                errors.append(f"{label}: {type(e).__name__}: {e}")
                return None

        for path in [base + ".wcs"] + sorted(glob.glob(os.path.join(tmp, "*.wcs"))):
            if os.path.isfile(path):
                r = _try(self._read_wcs_header(path), os.path.basename(path))
                if r is not None:
                    return r
        for path in [base + ".ini"] + sorted(glob.glob(os.path.join(tmp, "*.ini"))):
            if os.path.isfile(path):
                r = _try(self._read_ini_header(path), os.path.basename(path))
                if r is not None:
                    return r
        try:
            from astropy.io import fits
            r = _try(fits.getheader(in_fits), "in-fits header")
            if r is not None:
                return r
        except Exception:
            pass
        self._last_errors = errors
        return None

    @staticmethod
    def _read_ini_header(path: str):
        """ASTAP's `.ini` solution as a header: plain KEY=value lines (CRVAL1,
        CRPIX1, CD1_1…, PLTSOLVD). Not 80-col FITS, so parsed separately."""
        from astropy.io import fits
        header = fits.Header()
        try:
            with open(path, "r", errors="ignore") as f:
                for line in f:
                    if "=" not in line:
                        continue
                    key, val = line.split("=", 1)
                    key, val = key.strip().upper(), val.strip().strip("'\"").strip()
                    if not key or len(key) > 8:
                        continue
                    try:
                        header[key] = float(val)
                    except ValueError:
                        header[key] = val
        except OSError:
            return None
        return header

    @staticmethod
    def _output(tmp: str) -> str:
        """Last of ASTAP's own stdout/stderr, for surfacing why a solve failed."""
        try:
            with open(os.path.join(tmp, _OUT_FILE)) as f:
                return f.read().strip()[-400:]
        except OSError:
            return ""

    @staticmethod
    def _listing(tmp: str) -> str:
        try:
            return ", ".join(n for n in sorted(os.listdir(tmp)) if n != _OUT_FILE)
        except OSError:
            return ""

    @staticmethod
    def _read_wcs_header(wcs_path: str):
        """Tolerantly read ASTAP's `.wcs` sidecar into a header. ASTAP writes
        FITS-like cards but also long COMMENT/WARNING lines and CONTINUE cards
        that astropy's strict `Header.fromtextfile` rejects with 'CONTINUE cards
        must have string values'. Parse card-by-card, keep only the keyword cards
        that parse cleanly (CRVAL/CRPIX/CD/CTYPE/PLTSOLVD…), and drop anything
        else — so a stray comment can't sink an otherwise-valid solution."""
        from astropy.io import fits
        try:
            with open(wcs_path, "r", errors="ignore") as f:
                raw = f.read()
        except OSError:
            return None
        header = fits.Header()
        for line in raw.replace("\r", "").split("\n"):
            line = line.rstrip()
            key = line[:8].strip().upper()
            if not line or key in ("", "END", "COMMENT", "HISTORY", "CONTINUE"):
                continue
            if len(line) < 9 or line[8] != "=":            # not a FITS value card
                continue
            try:
                card = fits.Card.fromstring(line.ljust(80)[:80])
                if card.keyword and card.keyword not in ("COMMENT", "HISTORY", "CONTINUE"):
                    header[card.keyword] = card.value      # forces value parse
            except Exception:
                continue                                    # skip any card astropy chokes on
        return header

    @staticmethod
    def _build(header) -> "SolveResult | None":
        """Build a solved SolveResult from a parsed header (from any source), or
        None if it has no usable astrometric solution. Injects CTYPE if the source
        (e.g. an .ini) omitted it; raises if the WCS can't be built — callers
        record the reason."""
        if header is None or "CRVAL1" not in header or "CRVAL2" not in header:
            return None
        if str(header.get("PLTSOLVD", "T")).strip().upper() in ("F", "FALSE"):
            return None
        if "CTYPE1" not in header:            # .ini solutions omit CTYPE
            header["CTYPE1"] = "RA---TAN"
            header["CTYPE2"] = "DEC--TAN"
        from astropy.wcs import WCS
        wcs = WCS(header)
        cd = wcs.pixel_scale_matrix           # deg/px 2x2
        pixscale = float(np.sqrt(abs(cd[0, 0] * cd[1, 1] - cd[0, 1] * cd[1, 0])) * 3600.0)
        return SolveResult(True, wcs, float(header["CRVAL1"]),
                           float(header["CRVAL2"]), pixscale)

    def _parse(self, wcs_path: str) -> SolveResult:
        """Parse a `.wcs` sidecar into a SolveResult (used by tests + the reader)."""
        try:
            r = self._build(self._read_wcs_header(wcs_path))
        except Exception:
            r = None
        return r if r is not None else SolveResult(False, None, 0.0, 0.0, 0.0)
