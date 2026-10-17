from __future__ import annotations

import subprocess
import time

import numpy as np
from astropy.io import fits

from ..core.image import AstroImage
from ..core.tasks import Cancelled, child_process_kwargs, current
from ..core import sessionlog


class ToolError(Exception):
    def __init__(self, command, returncode: int, stdout: str, stderr: str, elapsed: float) -> None:
        # A tool that streams (StarNet2, GraXpert) has its stderr folded into
        # stdout, so stderr is empty and the message used to end at the colon.
        # Its own first complaint is the useful line: StarNet2 opens with
        # "Image size is too small for the window!" before any routine output.
        said = (stderr or "").strip() or _first_line(stdout)
        super().__init__(f"CLI failed ({returncode}): {said}")
        self.command = list(command)
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.elapsed = elapsed


def _first_line(text: str) -> str:
    for line in (text or "").splitlines():
        if line.strip():
            return line.strip()
    return ""


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


def run_cli(args: list[str], cancel=None, on_line=None) -> None:
    """Run a tool to completion, raising ToolError on a non-zero exit.

    `on_line` opts into STREAMING: each line is handed over as the child prints
    it, instead of everything arriving at once when it exits. Only GraXpert needs
    this — it prints `Progress: N%` about every two seconds through a slow
    denoise, and buffering it meant the app showed a still screen for minutes and
    read as hung. Without the callback the behaviour is exactly as before, so
    RC-Astro and ASTAP are untouched.
    """
    token = cancel if cancel is not None else current()
    start = time.monotonic()
    if on_line is None:
        proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, errors="replace", **child_process_kwargs())
        if token is not None:
            token.bind_process(proc)
        out, err = proc.communicate()         # returns when the child exits (incl. after a kill)
    else:
        # stderr folded into stdout: two pipes need two readers or the child
        # blocks when one fills, and GraXpert writes its progress to stderr
        # anyway. The merged text becomes ToolError's stdout so a failure still
        # carries everything the tool said.
        proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, errors="replace", bufsize=1,
                                **child_process_kwargs())
        if token is not None:
            token.bind_process(proc)
        lines = []
        for line in proc.stdout:              # ends when the child exits or is killed
            line = line.rstrip("\n")
            lines.append(line)
            try:
                on_line(line)
            except Exception:
                pass                          # a reporting failure must not kill the run
        proc.wait()
        out, err = "\n".join(lines), ""
    elapsed = time.monotonic() - start
    # HERE, not in either branch above and not after the raise: this is the one
    # point both the streaming and the non-streaming paths converge on, and it
    # is before the ToolError — a tool that FAILED is precisely what a support
    # ticket is usually about, and an exception must not take the record with
    # it. The elapsed time is kept because it is the signal people actually
    # read: a step that finishes suspiciously fast is how a silently
    # downgraded pipeline looks (2026-09-22).
    sessionlog.write(f"tool  {' '.join(str(a) for a in args)} "
                     f"-> exit {proc.returncode} in {elapsed:.1f}s")
    if token is not None and token.cancelled:
        raise Cancelled()
    if proc.returncode != 0:
        raise ToolError(args, proc.returncode, out or "", err or "", elapsed)
