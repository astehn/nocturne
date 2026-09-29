"""Whether two folders of subs came from the same camera.

Frame size alone cannot tell: an S50 Pro sub is 2160x3840 exactly like an S30
Pro one (his NGC 7000 subs, CREATOR='ZWO Seestar S50 Pro', FOCALLEN=260 against
160), and the S30 Pro's own wide-angle camera writes the same CREATOR at about
55" per pixel against 3.7". The image scale is what has to match; a stack
registered across two scales is not a stack.
"""
from __future__ import annotations

from dataclasses import dataclass

from .verdict import pixel_scale

# Two readings of one camera differ only by header rounding (XPIXSZ is written
# as 2.90000009536743); the closest real pair, S30 Pro against S50 Pro, is 38%
# apart.
SCALE_TOLERANCE = 0.02


@dataclass(frozen=True)
class Camera:
    creator: str
    size: tuple[int, int]         # sorted, so a portrait and a landscape frame match
    scale: float | None           # arc-seconds per pixel

    def describe(self) -> str:
        scale = f"{self.scale:.1f}″ per pixel" if self.scale else "unknown scale"
        return f"{self.creator or 'an unnamed camera'}, {scale}"


def read_camera(path: str) -> Camera | None:
    from astropy.io import fits
    try:
        h = fits.getheader(path)
    except Exception:            # noqa: BLE001 — unreadable: the caller tries another
        return None
    w, ht = int(h.get("NAXIS1") or 0), int(h.get("NAXIS2") or 0)
    if not (w and ht):
        return None
    creator = str(h.get("CREATOR") or h.get("INSTRUME") or "").strip()
    return Camera(creator, tuple(sorted((w, ht))), pixel_scale(h))


def first_camera(paths, skip_masters: bool = False) -> Camera | None:
    """The first readable raw sub decides. A stacked master sitting among the
    subs is skipped when asked: it can be cropped to any size."""
    from ..core.fits_io import is_stacked_master
    for p in paths:
        if skip_masters:
            try:
                if is_stacked_master(p):
                    continue
            except Exception:    # noqa: BLE001 — unreadable: read_camera says None
                continue
        cam = read_camera(p)
        if cam is not None:
            return cam
    return None


def mismatch(listed: Camera | None, added: Camera | None) -> str | None:
    """Why `added` cannot join `listed`, or None when it can (or when either is
    unknown — refusing on a missing card would block every non-Seestar file)."""
    if listed is None or added is None:
        return None
    if listed.scale and added.scale:
        if abs(added.scale - listed.scale) / listed.scale > SCALE_TOLERANCE:
            return (f"a different camera or lens ({added.describe()}) from the "
                    f"subs listed ({listed.describe()})")
    if added.size != listed.size:
        a, b = added.size, listed.size
        return (f"frames of a different size ({a[1]}×{a[0]}) from the subs "
                f"listed ({b[1]}×{b[0]})")
    return None
