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
from .base import write_temp_fits

# ASTAP's solved WCS follows the FITS bottom-up pixel convention; Nocturne display
# arrays are top-row-first. Projection (core/catalog) flips y when this is True.
# CONFIRM against a real ASTAP solve (see the verification spike).
FITS_Y_DOWN = True


@dataclass
class SolveResult:
    solved: bool
    wcs: object | None
    center_ra_deg: float
    center_dec_deg: float
    pixscale_arcsec: float


def _run_astap(args: list[str], cwd: str) -> int:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True).returncode


def hint_from_metadata(meta: dict) -> tuple[float, float] | None:
    """(ra_hours, dec_deg) from a FITS OBJCTRA/OBJCTDEC-style metadata pair, or
    None if absent/unparseable. Accepts sexagesimal or decimal strings."""
    ra, dec = meta.get("ra"), meta.get("dec")
    if not ra or not dec:
        return None
    try:
        from astropy.coordinates import Angle
        import astropy.units as u
        ra_h = Angle(str(ra), unit=u.hourangle).hour
        dec_d = Angle(str(dec), unit=u.deg).deg
        return float(ra_h), float(dec_d)
    except Exception:
        return None


class ASTAP:
    def __init__(self, binary_path: str) -> None:
        self.binary_path = binary_path

    def solve(self, img: AstroImage, *, fov_deg: float | None = None,
              ra_hours: float | None = None, dec_deg: float | None = None,
              runner=None) -> SolveResult:
        runner = runner or _run_astap
        tmp = tempfile.mkdtemp(prefix="nocturne_astap_")
        try:
            in_fits = os.path.join(tmp, "solve.fits")
            base = os.path.join(tmp, "solve")
            write_temp_fits(img, in_fits)
            args = [self.binary_path, "-f", in_fits, "-o", base, "-wcs"]
            if fov_deg is not None:
                args += ["-fov", str(round(float(fov_deg), 4))]
            if ra_hours is not None and dec_deg is not None:
                args += ["-ra", str(round(float(ra_hours), 4)),
                         "-spd", str(round(float(dec_deg) + 90.0, 4))]  # south pole distance
            runner(args, tmp)
            wcs_path = base + ".wcs"
            if not os.path.isfile(wcs_path):
                return SolveResult(False, None, 0.0, 0.0, 0.0)
            return self._parse(wcs_path)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

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

    def _parse(self, wcs_path: str) -> SolveResult:
        from astropy.wcs import WCS
        header = self._read_wcs_header(wcs_path)
        if header is None or "CRVAL1" not in header:
            return SolveResult(False, None, 0.0, 0.0, 0.0)
        if str(header.get("PLTSOLVD", "T")).strip().upper() in ("F", "FALSE"):
            return SolveResult(False, None, 0.0, 0.0, 0.0)
        try:
            wcs = WCS(header)
            cd = wcs.pixel_scale_matrix       # deg/px 2x2
            pixscale = float(np.sqrt(abs(cd[0, 0] * cd[1, 1] - cd[0, 1] * cd[1, 0])) * 3600.0)
            return SolveResult(True, wcs, float(header["CRVAL1"]),
                               float(header["CRVAL2"]), pixscale)
        except Exception:
            return SolveResult(False, None, 0.0, 0.0, 0.0)  # never crash the UI on a bad .wcs
