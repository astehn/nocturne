"""StarNet2: a free star/starless split.

The same job StarXTerminator does, from a tool that costs nothing. It matters
because NINE surfaces and twelve call sites depend on a split — Star Reduction,
De-green Stars, Nebula Saturation, Narrowband, Starless Levels, Star Colour,
Sharpen Nebulosity, Upscale Crop, Auto Enhance, Colour Balance, Batch and the
starless+stars export — and without RC-Astro they all fall back to
`core/starless.py`, which says of itself "an availability fallback, not a
quality match". Measured on a real NGC 7635 master, 2026-09-18: the free path
leaves 40.3% of star flux where StarNet2 leaves 20.9%, and the 1:1 crops are not
close — blobs and half-removed stars against a clean frame.

Design and the decisions behind it:
docs/superpowers/specs/2026-09-18-starnet2-integration.md (local).

USER-INSTALLED, NEVER BUNDLED. The licence is non-transferable and grants no
redistribution, so Nocturne finds it the way it finds GraXpert and ASTAP. Its
licence also forbids using its OUTPUT to train neural networks, which binds the
separate Nocturne NR project however convenient a labeller it would make.
"""
from __future__ import annotations

import os
import re
import tempfile

import numpy as np
import tifffile

from ..core.image import AstroImage
from ..core.tasks import report_progress
from .base import run_cli

# 16-bit, because that is what StarNet2 writes by default and what the round
# trip should preserve. 8-bit (its --eight) would quantise the faint end that
# every later step works in.
_MAX16 = 65535.0

# StarNet2 reports per-tile progress as `Working: 11.1%`, and the updates are
# separated by CARRIAGE RETURNS so that a terminal overwrites one line in place.
# That looks like it would defeat line streaming, and it does not: Python's
# universal-newline mode treats a lone \r as a line ending, so run_cli hands
# each update over AS IT HAPPENS. Measured 2026-09-19 — updates arrived at
# 0.07 s, 0.12 s, 0.17 s rather than in one lump at the end.
_PROGRESS_RE = re.compile(r"\bWorking:\s*(\d{1,3}(?:\.\d+)?)\s*%")


def parse_progress(line: str):
    """The percentage in a StarNet2 progress line, or None.

    Anchored on the word, like GraXpert's parser, so a percentage that is not
    progress cannot be mistaken for one — the non-quiet output also prints
    ranges and percentages of its own.

    Deliberately NOT `--machine-progress`, which reports the same tile counts as
    JSON Lines. That flag exists only in 2.6.2 and later; both of Andreas's
    macOS installs are 2.5.2, whose argument parser REJECTS an unknown flag, so
    using it would need a capability probe and would fail every split on a
    machine that has the older build. `Working: N%` is emitted by every version
    with no flag at all.
    """
    m = _PROGRESS_RE.search(line or "")
    return float(m.group(1)) if m else None


def _write_tiff(img: AstroImage, path: str) -> None:
    data = np.clip(np.asarray(img.data, np.float32), 0.0, 1.0)
    if data.ndim == 2:
        data = np.repeat(data[:, :, None], 3, axis=2)
    tifffile.imwrite(path, (data * _MAX16).astype(np.uint16))


def _read_tiff(path: str, like: AstroImage) -> AstroImage:
    """Read one of StarNet2's outputs back.

    It writes LZW-COMPRESSED 16-bit TIFF, which tifffile can only decode with
    `imagecodecs` — hence that dependency. Pillow opens the same file happily
    and hands back EIGHT bits without saying so, which would show up much later
    as banding in faint gradients and be blamed on something else entirely.
    """
    data = np.asarray(tifffile.imread(path), np.float32) / _MAX16
    return AstroImage(np.clip(data, 0.0, 1.0), is_linear=like.is_linear,
                      metadata=dict(like.metadata))


class StarNet:
    """Wraps the `starnet2` CLI. Mirrors RCAstro's shape on purpose."""

    def __init__(self, binary_path: str) -> None:
        self.binary_path = binary_path

    def remove_stars(self, img: AstroImage, *, runner=run_cli) -> tuple[AstroImage, AstroImage]:
        """Return (starless, stars_only).

        `stars` comes from `--unscreen`, which is the SCREEN-compatible form:
        `1-(1-starless)*(1-stars)` reconstructs the original. Every caller in
        this app screen-recombines, and RCAstro.remove_stars documents the same
        contract — the flag is even spelled the same — so this is a drop-in and
        not one call site changes.
        """
        tmp = tempfile.mkdtemp(prefix="starnet_")
        src = os.path.join(tmp, "in.tif")
        starless = os.path.join(tmp, "starless.tif")
        stars = os.path.join(tmp, "stars.tif")

        def _line(text: str) -> None:
            pct = parse_progress(text)
            if pct is not None:
                report_progress(int(round(pct)), 100)

        try:
            _write_tiff(img, src)
            # NO --quiet. It was here from the first version, and it is the
            # whole reason a split showed nothing: measured 2026-09-19, with
            # --quiet StarNet2 prints a single newline and NOTHING else, so
            # there was never any progress to miss — the app was asking for the
            # silence. Without it the tool reports every tile. The step is
            # 2.9 s on a master and ~38 s on a drizzled frame (33 Mpx, and time
            # is linear in area), six times that on the Linux CPU build, which
            # is far too long to show nothing. Its routine output also lands in
            # ToolError on a failure, so a broken run now says more, not less.
            runner([self.binary_path, "--input", src, "--output", starless,
                    "--unscreen", stars], on_line=_line)
            if not (os.path.isfile(starless) and os.path.isfile(stars)):
                raise RuntimeError(
                    "StarNet2 finished without writing both outputs — the "
                    f"binary at {self.binary_path} may be an incomplete copy "
                    "(its weights package must sit beside it)")
            return _read_tiff(starless, img), _read_tiff(stars, img)
        finally:
            for f in (src, starless, stars):
                try:
                    os.remove(f)
                except OSError:
                    pass
            try:
                os.rmdir(tmp)
            except OSError:
                pass
