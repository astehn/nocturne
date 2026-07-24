from __future__ import annotations

import subprocess
import time

import numpy as np
from astropy.io import fits

from ..core.image import AstroImage
from ..core.tasks import Cancelled, current


class ToolError(Exception):
    def __init__(self, command, returncode: int, stdout: str, stderr: str, elapsed: float) -> None:
        super().__init__(f"CLI failed ({returncode}): {stderr}")
        self.command = list(command)
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.elapsed = elapsed


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


def run_cli(args: list[str], cancel=None) -> None:
    token = cancel if cancel is not None else current()
    start = time.monotonic()
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, start_new_session=True)
    if token is not None:
        token.bind_process(proc)
    out, err = proc.communicate()             # returns when the child exits (incl. after a kill)
    elapsed = time.monotonic() - start
    if token is not None and token.cancelled:
        raise Cancelled()
    if proc.returncode != 0:
        raise ToolError(args, proc.returncode, out or "", err or "", elapsed)
