"""Subtract the light-pollution gradient, by as much as the user asks for.

Two things were wrong here, and the first hid the second.

The options were LABELLED by how much correction they apply and IMPLEMENTED as
GraXpert's `-smoothing`, which is the opposite axis: smoothing controls how
stiff the background model is, and a stiffer model removes LESS. So "strong"
(0.7) was gentler than "light" (0.3), and the help told users to reach for it
when the gradient was heavy. Andreas hit this on a real M31 frame 2026-08-04 —
his log recorded Background (strong) changing the image 8.8% and Background
(light) 9.1%. The v1 plan had named these Small/Medium/Large, which described
the smoothing scale honestly; the later rename to light/strong changed the
promise without changing the numbers.

Fixing the direction alone would have been close to pointless, which is the
second problem: smoothing barely moves the result. Measured against a known
gradient, the whole 0.1-0.9 range spans 86.8% removed down to 84.6% — a 2.2
point choice, and 1.2 points between the two options actually offered. A
control with no range is decoration.

GraXpert's CLI has no amount parameter (only -smoothing, -correction and -bg),
so the amount is applied here: run the extraction, then subtract that fraction
of what it proposes. Measured on the same gradient, that gives a genuinely
linear 0 to 86.2% — around forty times the range smoothing offered.

Both settings move together, and monotonically. "light" pairs a STIFFER model
with a partial correction, which is what the awkward case wants: when the
object fills the frame — a large galaxy, say — a flexible model mistakes its
faint outer halo for sky and subtracts the thing you came for. "strong" pairs a
flexible model with the full correction, which is right for an ordinary frame
where the object is small against the sky.
"""
from __future__ import annotations

from ..core.image import AstroImage
from ..history.step import Step
from ..tools.base import run_cli
from ..tools.graxpert import GraXpert

# option -> (GraXpert -smoothing, fraction of the modelled correction to apply)
_SETTINGS = {
    "light": (0.8, 0.5),
    "strong": (0.3, 1.0),
}


class BackgroundStep(Step):
    name = "Background"

    def __init__(self, graxpert: GraXpert) -> None:
        self._gx = graxpert
        self._runner = run_cli

    def options(self) -> list[str]:
        return ["off", "light", "strong"]

    def default_option(self) -> str:
        # "strong" is the ordinary choice, not the emergency one: it removes the
        # whole modelled gradient, which is what almost every frame wants and
        # what BOTH options effectively did before. Defaulting to "light" would
        # now quietly halve the correction everyone gets.
        return "strong"

    def apply(self, img: AstroImage, option: str) -> AstroImage:
        if option == "off":
            return img.copy()
        smoothing, amount = _SETTINGS[option]
        corrected = self._gx.background_extraction(img, smoothing, runner=self._runner)
        if amount >= 1.0:
            return corrected
        # Subtracting `amount` of the proposed correction. Equivalent to scaling
        # the background model, without needing a second GraXpert run to fetch it.
        blended = img.data + amount * (corrected.data - img.data)
        return AstroImage(blended.astype(img.data.dtype),
                          is_linear=img.is_linear,
                          metadata=dict(img.metadata))
