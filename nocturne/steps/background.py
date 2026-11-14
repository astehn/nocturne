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

One model, two amounts. An earlier version also stiffened the model for
"light", on the theory that a flexible model mistakes a frame-filling object's
faint outer halo for sky and subtracts the thing you came for. Measured on the
real M31 master that theory earned almost nothing — 92.8% of the gradient
removed at smoothing 0.3 against 90.1% at 0.8, under three points — while the
amount moved the same frame from 44% to 93%. Two dials moving at once for a
benefit too small to see is a worse control than one dial, so the stiffening
went. It can come back if a frame ever shows it is needed.
"""
from __future__ import annotations

from ..core.image import AstroImage
from ..history.step import Step
from ..tools.base import run_cli
from ..tools.graxpert import GraXpert

# One background model for both options, at the smoothing that modelled the real
# M31 gradient best of those measured (92.8% removed, against 92.0% at 0.5 and
# 90.1% at 0.8).
_SMOOTHING = 0.3

# Fraction of the modelled correction to subtract. Measured on that master:
# 0.5 removes 44.3% of the gradient, 1.0 removes 92.8% — so "light removes about
# half of what strong does" is literally true, on any frame, by construction.
_AMOUNT = {"light": 0.5, "strong": 1.0}


# Strokes a painted option may carry; anything else is a corrupt record.
_STROKE_KINDS = ("sky", "nebula", "erase")

# Said when a painted option arrives with no "strokes" key at all: that is a
# recipe or preset replayed on a new picture, where one picture's strokes mean
# nothing and only the automatic selection ran. `strokes: []` is different — the
# user applied with nothing painted, so there is nothing to warn about.
AUTO_MASK_MESSAGE = "Background used Auto-mask \u2014 check the result."


def is_painted(option) -> bool:
    return isinstance(option, dict) and option.get("method") == "painted"


def normalise_painted(option: dict, *, keep_strokes: bool = True) -> dict:
    """The one reader of a painted option: validates, and rounds coordinates to
    0.1 px so what is recorded is exactly what ran. `keep_strokes=False` is the
    recipe/preset form: the key is dropped, which is what later reads as
    "automatic selection only"."""
    amount = option.get("amount")
    if amount not in _AMOUNT:
        raise ValueError(f"Painted background: unknown amount {amount!r}")
    out: dict = {"method": "painted", "amount": amount}
    if keep_strokes and "strokes" in option:
        strokes = []
        for s in option["strokes"] or []:
            kind = s.get("kind")
            if kind not in _STROKE_KINDS:
                raise ValueError(f"Painted background: unknown stroke kind {kind!r}")
            strokes.append({
                "kind": kind,
                "radius": round(float(s.get("radius", 0.0)), 1),
                "points": [[round(float(x), 1), round(float(y), 1)]
                           for x, y in (s.get("points") or [])],
            })
        out["strokes"] = strokes
    return out


class BackgroundStep(Step):
    name = "Background"

    def __init__(self, graxpert: GraXpert) -> None:
        self._gx = graxpert
        self._runner = run_cli
        self.last_message = ""

    def options(self) -> list[str]:
        return ["off", "light", "strong"]

    def default_option(self) -> str:
        # "strong" is the ordinary choice, not the emergency one: it removes the
        # whole modelled gradient, which is what almost every frame wants and
        # what BOTH options effectively did before. Defaulting to "light" would
        # now quietly halve the correction everyone gets.
        return "strong"

    def apply(self, img: AstroImage, option: str) -> AstroImage:
        # Named in the log like every other external-tool step (his ask,
        # 2026-09-27): "Background (strong (GraXpert))". Off ran nothing.
        self.last_engine = None
        self.last_message = ""
        if option == "off":
            return img.copy()
        if is_painted(option):
            # Never touches GraXpert. The "Show what was removed" view needs no
            # model from here: it is the step's before minus after, and
            # apply_painted zeroes the output where the input was all-zero, so
            # a mosaic border shows no fake gradient.
            from ..core.painted_background import apply_painted
            opt = normalise_painted(option)
            self.last_engine = "Nocturne"
            if "strokes" not in opt:
                self.last_message = AUTO_MASK_MESSAGE
            out, _model = apply_painted(img, opt.get("strokes"), _AMOUNT[opt["amount"]])
            return out
        self.last_engine = "GraXpert"
        amount = _AMOUNT[option]
        corrected = self._gx.background_extraction(img, _SMOOTHING, runner=self._runner)
        if amount >= 1.0:
            return corrected
        # Subtracting `amount` of the proposed correction. Equivalent to scaling
        # the background model, without needing a second GraXpert run to fetch it.
        blended = img.data + amount * (corrected.data - img.data)
        return AstroImage(blended.astype(img.data.dtype),
                          is_linear=img.is_linear,
                          metadata=dict(img.metadata))
