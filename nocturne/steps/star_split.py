from __future__ import annotations

from ..core.image import AstroImage
from ..core.starless import split_stars
from ..tools.base import run_cli


def resolve_star_split(img: AstroImage, splitter, runner=run_cli):
    """(starless, stars), from whichever splitter the caller was given.

    `splitter` is anything with `remove_stars(img, runner=...)` — RCAstro
    (StarXTerminator, paid) or StarNet (free). It used to be named `rc` and
    meant only the first; the name was kept honest when StarNet2 arrived on
    2026-09-18, because five steps hold this object and NONE of them uses it for
    anything but splitting.

    `None` falls back to core/starless.py, which is always available and stays
    for exactly that reason: it is what makes the app work with nothing
    installed at all. It is also visibly the worst of the three — measured on a
    real master it leaves 40.3% of star flux where StarNet2 leaves 20.9%, and
    the crops are not close.

    All three are screen-recombine compatible: 1-(1-starless)*(1-stars) gives
    back the original.
    """
    if splitter is not None:
        return splitter.remove_stars(img, runner=runner)
    return split_stars(img)
