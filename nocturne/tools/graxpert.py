from __future__ import annotations

import os
import shutil
import tempfile

from ..core.image import AstroImage
from .base import read_fits_array, run_cli, write_temp_fits

_IMAGE_EXTS = (".fits", ".fit", ".tiff", ".tif", ".xisf")


class GraXpert:
    def __init__(self, binary_path: str) -> None:
        self.binary_path = binary_path

    def background_extraction(
        self, img: AstroImage, strength: float, *, runner=run_cli
    ) -> AstroImage:
        return self._run("background-extraction", img, strength, runner)

    def denoise(self, img: AstroImage, strength: float, *, runner=run_cli) -> AstroImage:
        return self._run("denoising", img, strength, runner)

    def _run(self, command: str, img: AstroImage, strength: float, runner) -> AstroImage:
        tmp = tempfile.mkdtemp(prefix="gx_")
        in_fits = os.path.join(tmp, "in.fits")
        out_fits = os.path.join(tmp, "out.fits")
        try:
            write_temp_fits(img, in_fits)
            # `-cli` is mandatory for command-line use; `-output` is the full
            # output filename; `-smoothing` is the 0..1 strength.
            runner([
                self.binary_path, "-cli", "-cmd", command,
                in_fits, "-output", out_fits, "-smoothing", str(strength),
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
        raise FileNotFoundError(f"GraXpert produced no output in {tmp}")
