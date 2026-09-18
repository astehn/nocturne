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
import tempfile

import numpy as np
import tifffile

from ..core.image import AstroImage
from .base import run_cli

# 16-bit, because that is what StarNet2 writes by default and what the round
# trip should preserve. 8-bit (its --eight) would quantise the faint end that
# every later step works in.
_MAX16 = 65535.0


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
        try:
            _write_tiff(img, src)
            runner([self.binary_path, "--input", src, "--output", starless,
                    "--unscreen", stars, "--quiet"])
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
