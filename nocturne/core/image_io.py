"""Readers for picture formats. Qt-free, like the rest of `core/`.

FITS has its own module because it carries a header worth parsing. A TIFF
carries no capture metadata at all, so the only interesting question it raises
is whether the pixels are still LINEAR — and that is measurable.
"""
from __future__ import annotations

import numpy as np

from .fits_io import _normalize
from .image import AstroImage

# p99.9 below this means the file is still LINEAR. Measured on four real masters
# (IC 1396A drizzle and 724-frame, NGC 6888, M 31) after the same peak
# normalisation `load_fits` applies:
#
#     linear (unstretched)       0.021
#     stretched, amount 0.00     0.873     <- the darkest stretch possible
#     stretched, amount 0.30     0.941
#     stretched, amount 1.00     0.981     <- the brightest
#
# Ten times above every linear measurement and four times below every stretched
# one, and stable across linked and unlinked stretches alike.
LINEAR_P999_MAX = 0.20


def looks_linear(data: np.ndarray) -> bool:
    """Is this unstretched data?

    p99.9 rather than the median, which is the obvious choice and the wrong one:
    the median moves 0.10 -> 0.45 across the stretch range, so its margin
    collapses at the dark end and a conservative stretch reads as linear. p99.9
    holds because ANY stretch pushes stars toward white while linear data keeps
    everything crushed near zero — it measures what actually separates the two
    states rather than a side effect of one particular target.

    The failure mode to worry about was assumed to be a stretched STARLESS file,
    on the reasoning that removing the stars removes the bright tail this keys
    on. MEASURED, it does not: a stretched starless IC 1396A reads 0.579,
    nowhere near the threshold, because after a stretch the NEBULOSITY carries
    the bright tail and only the star cores are taken out. (Approximated with a
    star mask rather than a StarX split, so treat it as the right order of
    magnitude rather than an exact figure.)

    What remains is a very bright subject — lunar, planetary — which could push
    a linear frame's p99.9 up. Out of scope for this app, but not impossible.
    Either way the user's override in the Import panel is one click, and the
    verdict is stated rather than applied silently.
    """
    finite = data[np.isfinite(data)]
    if finite.size == 0:
        return True          # nothing to judge; the pipeline's normal entry
    return bool(np.percentile(finite, 99.9) < LINEAR_P999_MAX)


def _channels_last(raw: np.ndarray) -> np.ndarray:
    """Transpose a PLANAR TIFF into the (H, W, C) the rest of the app assumes.

    A TIFF may store its channels as three separate planes rather than
    interleaved, and `tifffile` hands those back as (C, H, W). Nothing else in
    Nocturne expects that, and the alpha-drop below would have sliced the WIDTH
    to three columns — a 240x180 frame came back (3, 240, 3), three pixels of
    garbage, with the linear/stretched verdict wrong as well because the mangled
    data has different statistics.

    Shape alone decides, because tifffile has already collapsed the planar flag
    by the time we see the array. An image only 1-4 pixels TALL would be
    misread; that is not a photograph.
    """
    if raw.ndim != 3:
        return raw
    h, _w, c = raw.shape
    if c > 4 and h <= 4:             # channels first: (C, H, W)
        return np.transpose(raw, (1, 2, 0))
    return raw


def load_tiff(path: str) -> AstroImage:
    """A TIFF as an `AstroImage`, with `is_linear` decided by measurement.

    Metadata is deliberately empty: a TIFF carries no target, frames, gain,
    exposure, instrument or WCS, and inventing any of them would be worse than
    leaving the panel to say nothing.
    """
    import tifffile

    raw = np.asarray(tifffile.imread(path))
    raw = _channels_last(raw)
    if raw.ndim == 3 and raw.shape[2] > 3:
        raw = raw[:, :, :3]          # drop alpha: Photoshop writes RGBA readily
    data = _normalize(raw)
    if data.ndim == 2:
        data = np.repeat(data[:, :, None], 3, axis=2)
    return AstroImage(data.astype(np.float32),
                      is_linear=looks_linear(data), metadata={})
