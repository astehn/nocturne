from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile

import numpy as np

from ..core.image import AstroImage
from ..core.tasks import report_progress
from .base import read_fits_array, run_cli, write_temp_fits

_IMAGE_EXTS = (".fits", ".fit", ".fts", ".tiff", ".tif", ".xisf", ".png")


def _read_corrected(path: str, is_linear: bool, metadata: dict | None = None) -> AstroImage:
    """Read an RC-Astro FITS output and correct its orientation. RC-Astro uses
    the FITS bottom-row-first convention, so its output comes back vertically
    flipped relative to our top-row-first arrays — flip it back. `metadata` is the
    INPUT image's metadata, carried through (the tool changes pixels, not headers);
    the output file itself has none, so without this it would be lost."""
    img = read_fits_array(path)
    return AstroImage(
        np.ascontiguousarray(img.data[::-1]), is_linear=is_linear,
        metadata=dict(metadata or {}),
    )


# RC-Astro's default output draws a progress bar with CARRIAGE RETURNS — the
# whole thing is one line, so line-based streaming sees nothing until the run
# ends. `--json` is newline-delimited instead, and carries more: a percentage, an
# ETA, phase names and a schemaVersion, i.e. a contract rather than a scrape.
# Measured on 2.6.6, 2026-09-11:
#     {"event":"progress","done":11.1,"mpPerSec":0.6,"eta":1.1}
_JSON_SUPPORT: dict[str, bool] = {}


def parse_rc_event(line: str):
    """(kind, value) for one JSON line, or None if it says nothing useful.

    Never raises: a tool's chatter must not be able to take down the operation
    it is reporting on.
    """
    line = (line or "").strip()
    if not line.startswith("{"):
        return None
    try:
        obj = json.loads(line)
    except (ValueError, TypeError):
        return None
    if not isinstance(obj, dict):
        return None
    event = obj.get("event")
    if event == "progress":
        done = obj.get("done")
        if isinstance(done, (int, float)):
            return ("progress", int(round(done)))
        return None
    if event in ("status", "error", "warning"):
        msg = obj.get("message")
        return (event, msg) if msg else None
    return None


def _supports_json(binary_path: str) -> bool:
    """Whether this RC-Astro understands `--json`, asked once per binary.

    An older install must keep working — without progress, not broken — so the
    flag is only added when the help text advertises it.
    """
    if binary_path not in _JSON_SUPPORT:
        ok = False
        try:
            proc = subprocess.run([binary_path, "--help"], capture_output=True,
                                  text=True, timeout=30)
            ok = "--json" in (proc.stdout or "") + (proc.stderr or "")
        except (OSError, subprocess.SubprocessError):
            ok = False
        _JSON_SUPPORT[binary_path] = ok
    return _JSON_SUPPORT[binary_path]



def _progress_args(binary_path: str):
    """(extra argv, on_line) for a run that should report progress, or ([], None).

    Shared by both call sites: StarXTerminator does NOT go through `_run`, and it
    is the slow one — the split every star-based tool waits on — so leaving it out
    would have missed the wait people actually feel.
    """
    if not _supports_json(binary_path):
        return [], None

    def on_line(text: str) -> None:
        parsed = parse_rc_event(text)
        if parsed and parsed[0] == "progress":
            report_progress(parsed[1], 100)

    return ["--json"], on_line


class RCAstro:
    """Adapter for the RC-Astro standalone CLI (bxt / sxt / nxt)."""

    def __init__(self, binary_path: str) -> None:
        self.binary_path = binary_path

    def deconvolve(
        self,
        img: AstroImage,
        *,
        sharpen_stars: float,
        sharpen_nonstellar: float,
        runner=run_cli,
    ) -> AstroImage:
        return self._run(
            "bxt",
            img,
            ["--sharpen-stars", str(sharpen_stars),
             "--sharpen-nonstellar", str(sharpen_nonstellar)],
            runner,
        )

    def denoise(self, img: AstroImage, strength: float, *, runner=run_cli) -> AstroImage:
        return self._run("nxt", img, ["--denoise", str(strength)], runner)

    def remove_stars(
        self, img: AstroImage, *, unscreen: bool = True, runner=run_cli
    ) -> tuple[AstroImage, AstroImage]:
        """Run StarXTerminator; return (starless, stars_only).

        `unscreen` defaults True: the stars image is prepared for SCREEN
        recombine — `1-(1-starless)*(1-stars)` reconstructs the original exactly.
        Every caller here screen-recombines (Star Reduction, De-green Stars,
        Nebula Saturation, Narrowband), so this is required — the un-`--unscreen`
        (subtractive/additive) stars screen-recombine WRONG, dimming and puffing
        the stars even at zero reduction."""
        tmp = tempfile.mkdtemp(prefix="rc_")
        in_fits = os.path.join(tmp, "in.fits")
        out_fits = os.path.join(tmp, "starless.fits")
        try:
            write_temp_fits(img, in_fits)
            extra_args, on_line = _progress_args(self.binary_path)
            args = [
                self.binary_path, "--no-banner", *extra_args, "sxt",
                in_fits, "-o", out_fits, "--overwrite", "--depth", "32F", "--stars",
            ]
            if unscreen:
                args.append("--unscreen")
            runner(args, **({"on_line": on_line} if on_line is not None else {}))
            starless = _read_corrected(out_fits, img.is_linear, img.metadata)
            stars_path = self._find_other(tmp, {in_fits, out_fits})
            stars = _read_corrected(stars_path, img.is_linear, img.metadata)
            return starless, stars
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    @staticmethod
    def _find_other(tmp: str, exclude: set[str]) -> str:
        for name in sorted(os.listdir(tmp)):
            path = os.path.join(tmp, name)
            if path not in exclude and name.lower().endswith(_IMAGE_EXTS):
                return path
        raise FileNotFoundError(f"StarXTerminator produced no stars image in {tmp}")

    def _run(self, product: str, img: AstroImage, extra: list[str], runner) -> AstroImage:
        tmp = tempfile.mkdtemp(prefix="rc_")
        in_fits = os.path.join(tmp, "in.fits")
        out_fits = os.path.join(tmp, "out.fits")
        try:
            write_temp_fits(img, in_fits)
            # `--no-banner` is a top-level option (before the subcommand). Keep
            # 32-bit float output to preserve linear precision.
            extra_args, on_line = _progress_args(self.binary_path)
            args = [self.binary_path, "--no-banner", *extra_args, product,
                    in_fits, "-o", out_fits, "--overwrite", "--depth", "32F", *extra]
            runner(args, **({"on_line": on_line} if on_line is not None else {}))
            produced = out_fits if os.path.exists(out_fits) else self._find_output(tmp, in_fits)
            return _read_corrected(produced, img.is_linear, img.metadata)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    @staticmethod
    def _find_output(tmp: str, in_fits: str) -> str:
        for name in sorted(os.listdir(tmp)):
            path = os.path.join(tmp, name)
            if path != in_fits and name.lower().endswith(_IMAGE_EXTS):
                return path
        raise FileNotFoundError(f"RC-Astro produced no output in {tmp}")
