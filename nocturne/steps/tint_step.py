from __future__ import annotations

from ..core.color import apply_tint
from ..core.image import AstroImage
from ..history.step import Step


class TintStep(Step):
    """Deliberate colour-cast move, applied AFTER the colour calibration.

    A separate processing entry rather than a field on ColorSettings, so the
    order of operations matches how the tool is actually used: calibrate the
    colour first (sky balance or SPCC), look at the result, and only then nudge
    it if it is not to taste. Bundled into ColorSettings the sliders could only
    take effect by re-running the calibration, and a preview taken before it.

    Not a visible step: like Remove Green, it lives in the Color panel and maps
    back to the Color stage in the stepper.
    """

    name = "Colour Tint"

    def options(self) -> list[str]:
        return []

    def default_option(self) -> str:
        return ""

    def apply(self, img: AstroImage, option=None) -> AstroImage:
        try:
            tint, temperature = option
        except (TypeError, ValueError):
            return img.copy()
        return apply_tint(img, float(tint), float(temperature))
