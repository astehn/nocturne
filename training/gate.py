"""Do-no-harm gate: is the model worse than doing nothing, at ANY depth?

Every prior test on this project was RELATIVE ("closer to truth than the
noisy input was"). The 2026-08-22 prototype passed all of them, scored better
than two commercial competitors on its held-out target, and still broke a
real 405-frame M 8 master into green and magenta blotches -- because nothing
ever asked whether it was worse than leaving the image alone.

Checked PER DEPTH, never averaged. That regression was invisible in an
average: shallow depths improved so much they buried one deep-stack
regression. A gate that averages would have passed the exact model that
caused this.

The real M8 master has no ground truth of its own (it IS the deepest stack),
so training/tests/test_gate.py evaluates it with a self-referential chroma
proxy that only catches chroma-shaped damage -- see that file for what it
does and does not prove. The held-out-pair path (input_err/model_err against
real ground truth) is the check that generalises, stars included.
"""
from __future__ import annotations

from collections import namedtuple

import numpy as np

DepthResult = namedtuple("DepthResult", "target depth input_err model_err")
GateResult = namedtuple("GateResult", "passed failures")


def check_no_harm(results, tolerance: float = 0.0) -> GateResult:
    """Fails if the model is further from truth than the input at ANY depth.

    `tolerance` stays 0.0 by default -- "slightly worse" is still worse. A
    caller may widen it deliberately (e.g. for a noisy proxy metric), but the
    default must never soften "worse than doing nothing" into "close enough."
    """
    results = list(results)
    if not results:
        # `passed` is the signal that authorises overwriting the model the app
        # ships. Granting it on an empty result set would ship a model that was
        # never measured against anything -- refuse instead of passing vacuously.
        return GateResult(passed=False, failures=["no held-out results to check"])
    failures = [
        f"{r.target} @ {r.depth} frames: model {r.model_err:.3e} vs input {r.input_err:.3e}"
        for r in results if r.model_err > r.input_err * (1.0 + tolerance)
    ]
    return GateResult(passed=not failures, failures=failures)


# ------------------------------------------------- the truth-free deep end

def sky_mask(img_hwc, percentile: float = 60.0):
    """The darker `percentile`% of the frame -- background, not nebula cores.

    Matches noise.py's own dark-region convention so "sky" means the same
    thing here as it does where sigma is measured.
    """
    lum = np.asarray(img_hwc, np.float32).mean(axis=2)
    return lum <= np.percentile(lum, percentile)


def patch_chroma_bias(img_hwc, sky_mask, scale: float = 25.0) -> float:
    """Large-scale colour-difference std within `sky_mask` -- the blotch signature.

    This is the ONLY check in this project that can speak about a deep stack,
    because it is self-referential: it needs no ground truth, and a 405-frame
    master has none by definition -- it IS the deepest stack there is.

    `scale` (px) is well above single-pixel noise and well below the whole
    frame; the regression signal was empirically stable across a wide strength
    range at this value, so it is not knife-edge tuning. Measured on the
    synthetic fixtures in test_gate.py: at 25px, pixel-scale chroma speckle
    reads 0.00039 and patch-scale blotching 0.0159, a factor of 40; at 5px the
    speckle rises to 0.0022 and the separation starts to close.

    Blind to anything not chroma-shaped -- star deformation in particular. A
    pass here is not proof of safety, which is why nothing promotes itself on
    the strength of it.
    """
    from scipy.ndimage import gaussian_filter

    img_hwc = np.asarray(img_hwc, np.float32)
    r, g, b = img_hwc[:, :, 0], img_hwc[:, :, 1], img_hwc[:, :, 2]
    gm = gaussian_filter((r + b) / 2 - g, scale)
    rb = gaussian_filter(r - b, scale)
    return float((gm[sky_mask].std() ** 2 + rb[sky_mask].std() ** 2) ** 0.5)
