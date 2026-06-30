from __future__ import annotations

import os
import shutil
import tempfile

import numpy as np

from ..core.image import AstroImage
from .base import read_fits_array, run_cli, write_temp_fits

_IMAGE_EXTS = (".fits", ".fit", ".fts", ".tiff", ".tif", ".xisf", ".png")


def _read_corrected(path: str, is_linear: bool) -> AstroImage:
    """Read an RC-Astro FITS output and correct its orientation. RC-Astro uses
    the FITS bottom-row-first convention, so its output comes back vertically
    flipped relative to our top-row-first arrays — flip it back."""
    img = read_fits_array(path)
    return AstroImage(
        np.ascontiguousarray(img.data[::-1]), is_linear=is_linear, metadata=dict(img.metadata)
    )


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
        self, img: AstroImage, *, unscreen: bool = False, runner=run_cli
    ) -> tuple[AstroImage, AstroImage]:
        """Run StarXTerminator; return (starless, stars_only)."""
        tmp = tempfile.mkdtemp(prefix="rc_")
        in_fits = os.path.join(tmp, "in.fits")
        out_fits = os.path.join(tmp, "starless.fits")
        try:
            write_temp_fits(img, in_fits)
            args = [
                self.binary_path, "--no-banner", "sxt",
                in_fits, "-o", out_fits, "--overwrite", "--depth", "32F", "--stars",
            ]
            if unscreen:
                args.append("--unscreen")
            runner(args)
            starless = _read_corrected(out_fits, img.is_linear)
            stars_path = self._find_other(tmp, {in_fits, out_fits})
            stars = _read_corrected(stars_path, img.is_linear)
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
            runner([
                self.binary_path, "--no-banner", product,
                in_fits, "-o", out_fits, "--overwrite", "--depth", "32F",
                *extra,
            ])
            produced = out_fits if os.path.exists(out_fits) else self._find_output(tmp, in_fits)
            return _read_corrected(produced, img.is_linear)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    @staticmethod
    def _find_output(tmp: str, in_fits: str) -> str:
        for name in sorted(os.listdir(tmp)):
            path = os.path.join(tmp, name)
            if path != in_fits and name.lower().endswith(_IMAGE_EXTS):
                return path
        raise FileNotFoundError(f"RC-Astro produced no output in {tmp}")
