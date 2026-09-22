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


def preferred_splitter(settings):
    """The best available splitter for these settings, or None for the free path.

    RC-Astro first: the user paid for it and it is still the best. StarNet2
    second — free, and measurably far better than the fallback. None means
    core/starless.py, which never goes away.

    THE ONE PLACE THIS IS DECIDED. It lives here rather than in steps/factory
    because three UI paths — Narrowband, Colour Balance and Upscale Crop — build
    their own splitter and would otherwise each need their own copy of the rule.
    They did, for RC-Astro, which is why they all still said "StarX not
    configured" hours after StarNet2 worked everywhere else (2026-09-18).
    """
    from ..settings import rcastro_valid, resolve_binary, starnet_valid
    if rcastro_valid(settings):
        from ..tools.rcastro import RCAstro
        return RCAstro(resolve_binary(settings.rcastro_path))
    if starnet_valid(settings):
        from ..tools.starnet import StarNet
        return StarNet(resolve_binary(settings.starnet_path))
    return None


def splitter_name(splitter) -> str:
    """What a step should report as the engine it used: StarX, StarNet2 or free.

    THE SAME THREE WORDS as `MainWindow._split_tagged`, deliberately. That has
    tagged its splits since 2026-09-18 and Saturation's log line prints the tag;
    a second vocabulary for the same three things would let two lines about one
    split disagree.

    Read at the moment the step runs, never re-derived from settings afterwards.
    Settings can change while a step is in flight — a GraXpert denoise takes
    minutes — so asking `rcastro_valid` at log time can report a choice that was
    never made.
    """
    if splitter is None:
        return "free"
    return "StarX" if type(splitter).__name__ == "RCAstro" else "StarNet2"
