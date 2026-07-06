from __future__ import annotations

import subprocess

import numpy as np
from astropy.io import fits

from ..core.image import AstroImage


class ToolError(Exception):
    def __init__(self, returncode: int, stderr: str) -> None:
        super().__init__(f"CLI failed ({returncode}): {stderr}")
        self.returncode = returncode
        self.stderr = stderr


def write_temp_fits(img: AstroImage, path: str) -> None:
    data = img.data.astype(np.float32)
    if data.ndim == 3:
        data = np.transpose(data, (2, 0, 1))  # (3, H, W)
    fits.PrimaryHDU(data).writeto(path, overwrite=True)


def read_fits_array(path: str) -> AstroImage:
    with fits.open(path) as hdul:
        data = np.asarray(hdul[0].data, dtype=np.float32)
    if data.ndim == 3 and data.shape[0] == 3:
        data = np.transpose(data, (1, 2, 0))
    return AstroImage(data, is_linear=True)


def run_cli(args: list[str]) -> None:
    proc = subprocess.run(args, capture_output=True, text=True)
    if proc.returncode != 0:
        raise ToolError(proc.returncode, proc.stderr)
