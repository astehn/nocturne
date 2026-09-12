from __future__ import annotations

from ..core.color import remove_green_fringe, remove_green_fringe_masked
from ..core.image import AstroImage
from ..core.starless import star_mask
from ..history.step import Step
from ..tools.base import run_cli
from ..tools.rcastro import RCAstro

# Green fringe lives in the halo AROUND stars, so the free-path mask is widened
# past the star core to cover it (only used by the no-RC-Astro masked de-green).
FRINGE_MASK_SCALE = 2.5

# The StarX path's own confinement mask. A SEPARATE constant from the one above
# on purpose: that one governs how much of the image the free path de-greens
# outright, this one only limits where a stars-layer de-green may land. Sharing
# a number would mean tuning one path silently moved the other.
#
# 4.0 is the knee. Measured on a real drizzled NGC 7000 master (2026-09-12),
# mean |delta| per region, /255:
#
#     mask   covered   cores    halo   far bg    mean G
#      2.5     53%     0.440   0.511    0.165    +0.06
#      4.0     83%     0.518   0.877    0.197    -0.08     <- chosen
#      6.0     97%     0.584   1.152    0.375    -0.34
#      none   100%     0.781   1.717    2.437    -1.88
#
# 2.5 -> 4.0 buys 72% more fringe for 19% more background. 4.0 -> 6.0 buys 31%
# more for nearly double. Andreas judged 2.5 too tight on 1:1 crops of four
# bright stars; the table says where the trade stops paying.
SPLIT_MASK_SCALE = 4.0


class GreenFringeStep(Step):
    name = "De-green Stars"

    def __init__(self, rcastro: RCAstro | None = None) -> None:
        self._rc = rcastro
        self._runner = run_cli

    def options(self) -> list[str]:
        return []

    def default_option(self) -> str:
        return ""

    def apply(self, img: AstroImage, option) -> AstroImage:
        strength = float(option) if option not in (None, "") else 0.0
        if self._rc is not None:                              # StarX: clean stars layer
            starless, stars = self._rc.remove_stars(img, runner=self._runner)
            return remove_green_fringe(starless, stars, strength,
                                       star_mask(img, SPLIT_MASK_SCALE))
        # Free path: the split can't isolate a broad chromatic halo, so de-green
        # the image in place inside a widened star-neighbourhood mask instead.
        return remove_green_fringe_masked(img, star_mask(img, FRINGE_MASK_SCALE), strength)
