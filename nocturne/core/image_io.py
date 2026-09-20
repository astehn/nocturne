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


_ICC_TAG = 34675            # the same tag core/export.py embeds on the way out

# Profile description -> the name core/colour.py knows it by. Matched on the
# profile's OWN description rather than on the bytes, because byte-matching
# would mean importing nocturne/colour_profiles.py, which sources its blobs
# from Qt — and core/ is Qt-free by rule. Parsing is the better answer anyway:
# it recognises a profile written by Photoshop or a camera, not only one of
# ours. The aliases are the names those writers actually use; ROMM RGB is
# ProPhoto's formal name.
_ICC_ALIASES = {
    "srgb": "sRGB",
    "srgb iec61966-2.1": "sRGB",
    "srgb built-in": "sRGB",
    "display p3": "Display P3",
    "adobe rgb": "Adobe RGB",
    "adobe rgb (1998)": "Adobe RGB",
    "prophoto rgb": "ProPhoto RGB",
    "romm rgb": "ProPhoto RGB",
    "romm rgb: iso 22028-2:2013": "ProPhoto RGB",
}


def _icc_description(blob: bytes) -> str:
    """The human-readable name inside an ICC profile, or ''.

    Handles both forms: ICC v2 stores 'desc' as ASCII, v4 as 'mluc' UTF-16BE.
    Qt writes v4, Photoshop preserves whatever it was given, and a file from
    elsewhere may be either. Anything malformed returns '' and the caller
    leaves the pixels alone — a profile we cannot read is one whose numbers we
    do not understand, and guessing is worse than the status quo.
    """
    try:
        count = int.from_bytes(blob[128:132], "big")
        for i in range(count):
            off = 132 + i * 12
            sig = blob[off:off + 4]
            if sig != b"desc":
                continue
            start = int.from_bytes(blob[off + 4:off + 8], "big")
            size = int.from_bytes(blob[off + 8:off + 12], "big")
            tag = blob[start:start + size]
            if tag[:4] == b"mluc":                       # ICC v4
                n = int.from_bytes(tag[8:12], "big")
                if not n:
                    return ""
                ln = int.from_bytes(tag[16:20], "big")
                lo = int.from_bytes(tag[20:24], "big")
                return tag[lo:lo + ln].decode("utf-16-be", "replace").strip("\x00").strip()
            if tag[:4] == b"desc":                       # ICC v2
                ln = int.from_bytes(tag[8:12], "big")
                return tag[12:12 + ln].decode("latin-1", "replace").strip("\x00").strip()
    except Exception:
        return ""
    return ""


def _embedded_space(page) -> str | None:
    """Which colour space this TIFF declares, if we recognise it."""
    tag = page.tags.get(_ICC_TAG)
    if tag is None:
        return None
    blob = bytes(tag.value) if not isinstance(tag.value, bytes) else tag.value
    return _ICC_ALIASES.get(_icc_description(blob).lower())


def load_tiff(path: str) -> AstroImage:
    """A TIFF as an `AstroImage`, with `is_linear` decided by measurement.

    Metadata carries only what the FILE states. A TIFF has no target, frames,
    gain, exposure, instrument or WCS, and inventing any of them would be worse
    than leaving the panel to say nothing. An embedded colour profile is the
    exception, because it is not invented provenance — it is a fact about what
    the numbers mean, and acting on it CHANGES THE PIXELS, which the user is
    entitled to be told.

    WHY THE PROFILE IS HONOURED AT ALL. core/colour.py's reasoning — that astro
    data has no source colour space, a FITS being photon counts — is right for
    the pipeline and wrong for this one case. A tagged TIFF is a finished image
    that genuinely has a source space. core/export.py:22 already records the
    mirror of this bug: an untagged export "rendered dark in Photoshop: sRGB
    data read as ProPhoto", fixed by embedding the profile so the reader stops
    guessing. We then did the identical thing to files we opened. Measured on
    Andreas's Veil Nebula master, 2026-09-20: 5.0 levels short of red, 5.6 long
    of blue, mean dE2000 6.8 across the frame, and a mid grey pushed to
    dE2000 10.2 — the whole-image cast he reported.

    AN UNTAGGED FILE IS UNTOUCHED, and that matters more than the fix. Every
    saved project, every FITS-derived export and every file from a tool that
    does not tag depends on it. So does an unreadable or unrecognised profile:
    if we cannot say what the numbers mean, we do not change them.

    The conversion clips whatever lies outside sRGB, which is the price of a
    pipeline that works in sRGB. Measured on his real edit: 0.057% of pixels,
    because the data originated here and converting to a wider space on export
    never added gamut.
    """
    import tifffile

    with tifffile.TiffFile(path) as tf:
        page = tf.pages[0]
        raw = np.asarray(page.asarray())
        space = _embedded_space(page)

    raw = _channels_last(raw)
    if raw.ndim == 3 and raw.shape[2] > 3:
        raw = raw[:, :, :3]          # drop alpha: Photoshop writes RGBA readily
    data = _normalize(raw)
    if data.ndim == 2:
        data = np.repeat(data[:, :, None], 3, axis=2)

    metadata: dict = {}
    if space is not None:
        metadata["colour_space"] = space
        if space != "sRGB":
            from .colour import convert
            data = np.clip(convert(data, to="sRGB", frm=space), 0.0, 1.0)
            metadata["colour_note"] = f"Converted from {space} to sRGB on open"
        else:
            metadata["colour_note"] = "Already sRGB; opened unchanged"

    # AFTER any conversion, deliberately. The verdict describes the image the
    # pipeline will work on, and a conversion changes the transfer curve —
    # ProPhoto's gamma is 1.8 against sRGB's ~2.2, which moves the statistic
    # this decision reads.
    return AstroImage(data.astype(np.float32),
                      is_linear=looks_linear(data), metadata=metadata)
