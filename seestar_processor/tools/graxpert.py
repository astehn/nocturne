from __future__ import annotations

import os
import tempfile

from ..core.image import AstroImage
from .base import read_fits_array, run_cli, write_temp_fits


class GraXpert:
    def __init__(self, binary_path: str) -> None:
        self.binary_path = binary_path

    def background_extraction(
        self, img: AstroImage, strength: float, *, runner=run_cli
    ) -> AstroImage:
        tmp = tempfile.mkdtemp(prefix="gx_")
        in_fits = os.path.join(tmp, "in.fits")
        out_stem = os.path.join(tmp, "out")
        out_fits = out_stem + ".fits"
        try:
            write_temp_fits(img, in_fits)
            runner([
                self.binary_path, "-cmd", "background-extraction",
                in_fits, "-output", out_stem, "-smoothing", str(strength),
            ])
            result = read_fits_array(out_fits)
            result.is_linear = img.is_linear
            return result
        finally:
            for f in (in_fits, out_fits):
                if os.path.exists(f):
                    os.remove(f)
            if os.path.isdir(tmp):
                os.rmdir(tmp)
