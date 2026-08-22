from __future__ import annotations

from ..core.denoise_model import available, denoise
from ..core.image import AstroImage
from ..history.step import Step

# Strength scales the predicted noise. 0.75 is the default rather than 1.0
# because full strength measurably OVER-smooths: on the held-out target its
# background noise came out 0.000004 against the 128-frame truth's 0.000032,
# and it lifted the 1st percentile from the truth's 0.043 to 0.138. 0.75 lands
# on the truth's own noise level and keeps stars tighter (radius 1.011 vs 1.017).
_LEVELS = {"light": 0.5, "medium": 0.75, "strong": 1.0}


class AiDenoiseStep(Step):
    """Nocturne's own denoiser, trained on Seestar stacks.

    Runs on LINEAR data, before Stretch — which is where it was trained and
    where Deconvolution already sits. A stretch derives its parameters from the
    image's own statistics, so a model applied afterwards would face a transfer
    function that was not present in any training pair.
    """

    name = "AI Denoise"

    def __init__(self, sensor: str = "s30") -> None:
        self._sensor = sensor

    def options(self) -> list[str]:
        return ["light", "medium", "strong"]

    def default_option(self) -> str:
        return "medium"

    def apply(self, img: AstroImage, option) -> AstroImage:
        level = option if option in _LEVELS else self.default_option()
        if not available(self._sensor):
            return img          # no model for this camera; a no-op beats an error
        return denoise(img, _LEVELS[level], sensor=self._sensor)
