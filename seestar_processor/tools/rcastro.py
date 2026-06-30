from __future__ import annotations

import os
import shutil
import tempfile

from ..core.image import AstroImage
from .base import read_fits_array, run_cli, write_temp_fits

_IMAGE_EXTS = (".fits", ".fit", ".fts", ".tiff", ".tif", ".xisf", ".png")


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
            result = read_fits_array(produced)
            result.is_linear = img.is_linear
            return result
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    @staticmethod
    def _find_output(tmp: str, in_fits: str) -> str:
        for name in sorted(os.listdir(tmp)):
            path = os.path.join(tmp, name)
            if path != in_fits and name.lower().endswith(_IMAGE_EXTS):
                return path
        raise FileNotFoundError(f"RC-Astro produced no output in {tmp}")
