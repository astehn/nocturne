from __future__ import annotations

from ..core.image import AstroImage
from ..core.starless import split_stars
from ..tools.base import run_cli


def resolve_star_split(img: AstroImage, rc, runner=run_cli):
    """(starless, stars) via StarXTerminator when `rc` is available, else the
    free sep-based split. Both are screen-recombine compatible."""
    if rc is not None:
        return rc.remove_stars(img, runner=runner)
    return split_stars(img)
