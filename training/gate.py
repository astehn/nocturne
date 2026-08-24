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
so the deep end is evaluated with a chroma proxy that only catches
chroma-shaped damage -- see `deep_end_result` and test_gate.py for what it
does and does not prove. The held-out-pair path (input_err/model_err against
real ground truth) is the check that generalises, stars included.

That proxy needs something to be measured AGAINST, and the choice of control
is the whole thing: against the untouched input it measures how much noise
the model removed, not how much harm it did, and fails a plain Gaussian blur.
Against a blur matched to the model's own noise reduction it measures the
question worth asking. `deep_end_result` carries the numbers.
"""
from __future__ import annotations

from collections import namedtuple

import numpy as np

# How much MORE patch-scale chroma than the noise-matched blur control a model
# may leave in the deep-end master before the gate calls it damage. It cannot
# be zero: a real denoiser legitimately differs from a blur -- it keeps stars
# and fine structure instead of smearing them, which leaves more standing.
#
# Measured 2026-08-24 on the real M8 master (405 frames), model / control:
#   blur sigma 1.0, 2.3   (neutral, by construction)     1.000, 1.000
#   n2n_v1   @0.75 / @1.0 / @1.5                    1.041, 1.032, 1.093
#   s30_v2   @0.75 / @1.0 / @1.5                    1.043, 1.009, 1.014
# 0.15 clears every working denoiser measured, with 40% headroom over the
# worst of them. Its teeth, measured the same day by injecting 30px-scale
# green/magenta blotches into n2n_v1's own output on that master: 0.18x the
# sky noise sigma reads 1.090 and passes, 0.37x reads 1.225 and fails. So it
# catches invented blotching from about a third of a sigma upwards, on a
# master whose sky sigma is 5.5e-5.
#
# READ THIS BEFORE TRUSTING IT: s30_v2 is the checkpoint that actually broke
# this master into green and magenta blotches, and the numbers above are the
# whole story about what this proxy can and cannot do. Against a noise-matched
# control it scores that model 1.009-1.043 -- indistinguishable from, and at
# two of three strengths BETTER than, the model everyone agrees is clean. The
# proxy's apparent teeth in the old input-relative form were an artefact of
# the confound this constant's neighbours fix: it ranked models by how much
# noise they removed, and v2 only looked guilty because it removed a lot.
# So this tolerance has NO proven positive control among real checkpoints;
# its lower bound comes from real models and its upper bound from synthetic
# injection alone. Treat a pass as "not grossly unlike a neutral smoother",
# never as "not the 2026-08-22 failure".
DEEP_END_TOLERANCE = 0.15

DepthResult = namedtuple("DepthResult", "target depth input_err model_err tolerance",
                         defaults=(0.0,))
GateResult = namedtuple("GateResult", "passed failures")


def check_no_harm(results, tolerance: float = 0.0) -> GateResult:
    """Fails if the model is further from truth than the input at ANY depth.

    `tolerance` stays 0.0 by default -- "slightly worse" is still worse. A
    caller may widen it deliberately (e.g. for a noisy proxy metric), but the
    default must never soften "worse than doing nothing" into "close enough."

    A result may also carry its OWN tolerance, for a metric whose zero is not
    truly zero -- the deep-end proxy compares against a blur control rather
    than against truth, and a real denoiser is entitled to differ from a blur
    (see DEEP_END_TOLERANCE). Per-result and caller tolerance do not add up;
    the wider of the two applies, so widening one can never quietly narrow the
    other.
    """
    results = list(results)
    if not results:
        # `passed` is the signal that authorises overwriting the model the app
        # ships. Granting it on an empty result set would ship a model that was
        # never measured against anything -- refuse instead of passing vacuously.
        return GateResult(passed=False, failures=["no held-out results to check"])
    failures = []
    for r in results:
        tol = max(float(tolerance), float(getattr(r, "tolerance", 0.0) or 0.0))
        if r.model_err > r.input_err * (1.0 + tol):
            allowed = f" (allowance {tol:.0%})" if tol else ""
            failures.append(
                f"{r.target} @ {r.depth} frames: model {r.model_err:.3e} "
                f"vs input {r.input_err:.3e}{allowed}")
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


# ------------------------------------- the deep end, against a fair control

def noise_matched_blur(img_hwc, target_sigma: float, lo: float = 0.2, hi: float = 6.0):
    """A plain Gaussian blur of `img_hwc` left with `target_sigma` noise.

    The neutral control `deep_end_result` compares a model against. A blur
    invents nothing and has no opinion about colour, so whatever chroma
    structure it exposes was already in the image -- which is exactly the
    quantity the old deep-end check mistook for damage.

    Returns (blurred, blur_sigma_px). Measured noise falls monotonically with
    blur radius, so a bounded search is enough; when the target lies outside
    what [lo, hi] can reach the nearest bound is returned rather than raising,
    because "the model denoised less than a 0.2px blur" is a legitimate answer
    and the caller still needs a control to compare against.
    """
    from scipy.ndimage import gaussian_filter
    from scipy.optimize import brentq

    from noise import estimate_sigma

    img = np.asarray(img_hwc, np.float32)

    def blurred(s: float):
        return gaussian_filter(img, (s, s, 0) if img.ndim == 3 else (s, s))

    def residual(s: float) -> float:
        return estimate_sigma(blurred(s)) - float(target_sigma)

    if residual(lo) <= 0.0:
        return blurred(lo), lo
    if residual(hi) >= 0.0:
        return blurred(hi), hi
    # xtol in px: 0.02 is far finer than the scale any of these measurements
    # resolve, and caps the search at ~9 blurs of a full master.
    s = brentq(residual, lo, hi, xtol=0.02)
    return blurred(s), float(s)


def deep_end_result(inp_hwc, out_hwc, target: str, depth: int,
                    stretch: float = 0.25, tolerance: float | None = None):
    """Deep-end DepthResult: the model's patch chroma against a blur's, not the input's.

    Comparing the model to the UNTOUCHED input is invalid, because removing
    pixel noise makes pre-existing low-frequency colour structure more visible
    -- it was always there, under the speckle. Measured 2026-08-24 on the real
    M8 master (405 frames) with a plain Gaussian blur, which invents nothing:

        untouched                          0.0407   --
        blur sigma=0.6  (29% noise gone)   0.0437   1.07x
        blur sigma=0.9  (48%)              0.0458   1.13x
        blur sigma=1.3  (66%)              0.0478   1.18x
        blur sigma=1.8  (79%)              0.0495   1.22x
        n2n_v1 @1.0     (86%)              0.0520   1.28x

    The proxy rises with HOW MUCH noise was removed, whatever removed it, so
    the old comparison read "noise was removed" as "harm was done" and no
    working denoiser could pass it. n2n_v1 -- visibly clean, better global
    colour balance than the input -- was rejected on that line, for out-doing
    a blur.

    So the control is a blur matched to the model's OWN noise reduction, and
    the question becomes the one worth asking: does the model add more
    patch-scale chroma than a neutral smoother that removed just as much
    noise? The sky mask comes from the input for both sides, and both are
    measured after the display stretch -- the bias is invisible in linear data,
    which is what every prior relative-to-truth test missed. Matching on noise
    also matches the stretch, which is a second confound in one: linked_stretch
    derives its shadow clip from the image's own MAD, so a denoised image is
    stretched differently from its input, and about a third of the rise in the
    table above is that alone (measured: blur 1.8 reads 1.22x with each image
    stretched on its own terms, 1.14x under a single shared transfer).
    """
    from nocturne.core.autostretch import linked_stretch

    from noise import estimate_sigma

    inp_hwc = np.asarray(inp_hwc, np.float32)
    out_hwc = np.asarray(out_hwc, np.float32)
    sky = sky_mask(inp_hwc)
    control, _ = noise_matched_blur(inp_hwc, estimate_sigma(out_hwc))
    return DepthResult(
        target, depth,
        patch_chroma_bias(linked_stretch(control, stretch), sky),
        patch_chroma_bias(linked_stretch(out_hwc, stretch), sky),
        DEEP_END_TOLERANCE if tolerance is None else float(tolerance),
    )
