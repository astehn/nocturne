import os
import sys

import pytest

_TRAINING = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REPO_ROOT = os.path.dirname(_TRAINING)
sys.path.insert(0, _TRAINING)
sys.path.insert(0, _REPO_ROOT)


def test_a_model_that_makes_a_deep_stack_worse_fails():
    """The exact 2026-08-22 regression: fine on shallow inputs, damaging on a
    deep one. A gate that only looks at the average would have passed it."""
    from gate import check_no_harm, DepthResult
    r = [DepthResult("NGC6888",   8, 0.000175, 0.000068),
         DepthResult("NGC6888",  32, 0.000130, 0.000071),
         DepthResult("NGC6888", 405, 0.000032, 0.000039)]   # worse than nothing
    g = check_no_harm(r)
    assert not g.passed
    assert any("405" in f for f in g.failures)


def test_a_gate_with_nothing_to_check_does_not_pass():
    """A vacuous pass is the worst possible outcome here: `passed=True` is the
    signal that authorises overwriting the model the app ships, and an empty
    result set would grant it having verified nothing. nightly.py guards its
    own call site, but the authority lives in this function, so the refusal
    belongs here too."""
    from gate import check_no_harm

    result = check_no_harm([])
    assert result.passed is False
    assert result.failures and "no held-out" in result.failures[0]


def test_a_model_that_helps_everywhere_passes():
    from gate import check_no_harm, DepthResult
    g = check_no_harm([DepthResult("NGC6888", 8, 1.0e-4, 0.5e-4),
                       DepthResult("NGC6888", 405, 3.2e-5, 3.1e-5)])
    assert g.passed and not g.failures


# --- Step 5: the gate must have teeth against the REAL regression ---------
#
# READ THE 2026-08-24 CORRECTION FIRST (above the v2 replay, below): the
# reasoning in this block is sound about WHAT to measure and wrong about what
# to measure it AGAINST. Comparing to the untouched input made the number a
# measure of noise removal, so it convicted a plain Gaussian blur too, and
# the conclusion it draws about this checkpoint does not survive a control.
# Kept as written because the correction only makes sense against it.
#
# The M 8 master that was actually damaged (docs/superpowers/specs/
# 2026-08-22-denoise-training-system-design.md) has no deep-stack "truth" of
# its own -- it IS the deepest stack there is, 405 frames. So this cannot use
# input_err/model_err measured against ground truth the way a held-out pair
# can.
#
# Chosen proxy: does the model move the image's OWN statistics in a direction
# that indicates damage, measured self-referentially with no truth image at
# all. The documented failure was specific -- "the background broke into
# green and magenta blotches" -- which is large-scale, spatially-correlated
# colour bias, not pixel-to-pixel chroma noise. Measuring plain per-pixel
# chroma std (evaluate.chroma_noise) on this master gives the WRONG answer:
# the model lowers it (0.000077 -> 0.000021 measured directly), because
# blurring away real per-pixel noise also lowers that number even when it is
# busy creating the blotches. What catches the blotches is a Gaussian-blurred
# (sigma=25px) version of the same chroma-difference channels: that isolates
# patch-scale colour bias from pixel noise, and on this exact master +
# checkpoint it INCREASES after the model runs, at every strength from 0.5 to
# 1.5, measured directly. Applying it after Nocturne's own display stretch
# (nocturne.core.autostretch.linked_stretch) matters too -- the bias is tiny
# in linear data (this is what made every prior relative-to-truth test miss
# it) and only becomes the visible blotching once stretched the way a user
# would actually see it. This is the same principle the project's WYSIWYG
# rule states for the preview: what gets measured must be what gets seen.
#
# What this proves: this specific checkpoint (today's s30_v2, the pre-
# conditioning 3-channel model that is the actual subject of the incident
# report) makes THIS specific real master's background patchier after
# denoising than before, at its real default strength. What it does NOT
# prove: it is not a general-purpose harm detector for arbitrary models or
# targets -- unlike the held-out-pair path, there is no ground truth here, so
# a model could still pass this specific check while doing other damage this
# proxy is blind to (e.g. star deformation on a deep stack; this proxy only
# looks at background colour). It exists to make sure THIS regression, on
# THIS master, can never silently start passing again -- it is not, by
# itself, a complete safety net. The held-out-pair path (Steps 1-4) is the
# one that generalises: it has real ground truth and covers stars directly
# via evaluate.star_table, which this proxy does not attempt to replace.
#
# Needs the M8 master and the s30_v2 checkpoint, both on an external volume
# not in git -- skipped, not failed, when that volume isn't mounted here.

_M8_MASTER = "/Volumes/Work2/Images/Astro/Work/M8 Total/lights/M8_405x10s_68min.fits"
_V2_RUN = "/Volumes/Work2/Images/Astro/denoise_runs/s30_v2/best.pt"

# Checked: could the +24% at strength 0.75 be a tile-seam artefact of
# _apply_unconditioned's ramp-blended overlap rather than real damage? A
# seam would show up as extra patch-scale (~25px) chroma structure at the
# tile pitch specifically, which a healthy model could also produce and
# would make this a false-positive risk for the gate.
#
# Measured directly on a flat field + Gaussian noise (same distribution on
# every channel, so the correct output has ZERO chroma structure by
# construction -- there is no real colour to damage, so any bias increase
# after the model runs has to come from the machinery, not the scene):
#   - tiled (this harness, tile=256/overlap=32): input_err 0.00318,
#     model_err 0.00462, +45.0%
#   - single forward pass, NO tiling at all (512x512, fits in one call):
#     input_err 0.00335, model_err 0.00485, +44.8%
#   Tiling changes the result by 0.2 percentage points out of 45 -- noise,
#   not signal.
#   - within the tiled run, a 20px band straddling every tile seam measures
#     LOWER bias than the interior (ratio 0.961), not higher, which is the
#     opposite of what a seam artefact would look like.
# Conclusion: the tiling contributes nothing measurable; the bias this test
# measures is the model's own behaviour, confirmed by reproducing it with no
# tiling involved at all. (Separately notable: this model invents patch-
# scale chroma bias even on pure noise with no real structure present --
# consistent with the postmortem's "learned chroma noise is large and strips
# it hard" diagnosis, and not something a seam explanation would predict.)


def _apply_unconditioned(img_hwc, model, device, strength, tile=256, overlap=32):
    """Tiled inference for the pre-conditioning (3-channel) checkpoint.

    Not evaluate.apply_model: that hard-codes model.denoise(t, sigma,
    strength), which requires the 4-channel conditioned architecture this
    checkpoint predates (its enc.0.0.weight is [32, 3, 3, 3], not [32, 4, 3,
    3]). This mirrors what the app's denoise path did before Task 4 added
    conditioning: out = x - strength * model(x), no sigma channel at all.
    """
    import numpy as np
    import torch

    H, W, C = img_hwc.shape
    step = tile - overlap
    out = np.zeros((H, W, C), np.float32)
    wsum = np.zeros((H, W, 1), np.float32)
    ramp = np.minimum(np.arange(tile), np.arange(tile)[::-1]).astype(np.float32)
    ramp = np.clip(ramp / max(overlap, 1), 0, 1)
    win = (ramp[:, None] * ramp[None, :])[:, :, None] + 1e-6
    with torch.no_grad():
        for y in range(0, max(H - overlap, 1), step):
            for x in range(0, max(W - overlap, 1), step):
                y0, x0 = min(y, max(H - tile, 0)), min(x, max(W - tile, 0))
                patch = img_hwc[y0:y0+tile, x0:x0+tile]
                if patch.shape[0] != tile or patch.shape[1] != tile:
                    continue
                t = torch.from_numpy(np.ascontiguousarray(patch))
                t = t.permute(2, 0, 1)[None].to(device)
                pred_noise = model(t)
                r = (t - strength * pred_noise)[0].permute(1, 2, 0).cpu().numpy()
                out[y0:y0+tile, x0:x0+tile] += r * win
                wsum[y0:y0+tile, x0:x0+tile] += win
    return out / np.maximum(wsum, 1e-6)


# The proxy lives in gate.py, where nightly.py can call it on every run instead
# of it existing only inside this one replay test. The replay below no longer
# calls patch_chroma_bias directly: it goes through gate.deep_end_result, so
# what it exercises is what the gate exercises -- a replay measured with a
# metric the gate has stopped using proves nothing about the gate.


# THE TEETH THIS TEST WAS BELIEVED TO HAVE WERE THE BUG.
#
# It was the project's positive control: the incident checkpoint, the real
# master, "if this ever starts passing a human needs to look." Measured
# 2026-08-24, against a noise-matched blur control instead of the untouched
# input (see DEEP_END_TOLERANCE and the section at the foot of this file),
# model / control on that master:
#
#     s30_v2  @0.75 / @1.0 / @1.5      1.043, 1.009, 1.014   <- the bad one
#     n2n_v1  @0.75 / @1.0 / @1.5      1.041, 1.032, 1.093   <- the clean one
#     plain blur, any sigma            1.000
#
# The incident checkpoint is indistinguishable from a working denoiser, and
# at two of three strengths it scores BETTER. So the old form of this test
# did not detect the damage: it detected NOISE REMOVAL. v2 removed 71% of
# the noise at strength 0.75 and read +24%; n2n_v1 removes 86% and reads
# +28%, which is why the gate rejected the good model. Ranking by how much
# noise a model removed happened to convict the guilty model, and would have
# convicted a Gaussian blur just as hard.
#
# Kept, switched to the metric the gate actually uses now, and marked
# xfail(strict) rather than deleted, because the question it asks is still
# the right one and an XPASS is worth a human's time: if a future change to
# the deep-end metric makes this checkpoint fail again -- for a reason that
# is about the damage rather than about noise removal -- this test turns red
# and says so. What is NOT available today is a real-checkpoint positive
# control for the deep-end proxy; the injection test at the foot of this file
# is synthetic, and that is the honest state of it.
@pytest.mark.xfail(
    strict=True,
    reason=(
        "the deep-end chroma proxy cannot separate the incident checkpoint "
        "from a working denoiser once the noise-removal confound is removed: "
        "s30_v2 reads 1.043 against a noise-matched control where n2n_v1 "
        "reads 1.032 (2026-08-24). Remove this marker only with a measurement."),
)
@pytest.mark.skipif(
    not (os.path.isfile(_M8_MASTER) and os.path.isfile(_V2_RUN)),
    reason=(
        f"needs the real M8 master ({_M8_MASTER}) and the s30_v2 checkpoint "
        f"({_V2_RUN}), both on an external volume not tracked in git -- not "
        "a code failure if that drive isn't mounted here"),
)
def test_v2_model_fails_the_gate_on_the_real_m8_master():
    """This is the actual incident, replayed: today's v2 checkpoint, applied
    at its real default strength (nocturne.core.denoise_model.denoise's
    default, 0.75) to the exact master that was damaged. If this ever starts
    passing, either the metric stopped detecting the known damage or a future
    checkpoint genuinely fixed it -- either way it needs a human to look."""
    import torch
    from astropy.io import fits

    import data as D
    from evaluate import _hwc
    from model import DenoiseUNet
    from gate import check_no_harm, deep_end_result

    device = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
    ck = torch.load(_V2_RUN, map_location=device)
    assert ck["model"]["enc.0.0.weight"].shape[1] == 3, (
        "s30_v2 was expected to be the pre-conditioning 3-channel model this "
        "test is about; its checkpoint shape changed."
    )
    model = DenoiseUNet(base=ck.get("args", {}).get("base", 32), in_ch=3).to(device)
    model.load_state_dict(ck["model"])
    model.eval()

    inp = _hwc(fits.getdata(_M8_MASTER))
    a = D._ASINH_A
    model_space_out = _apply_unconditioned(D.to_model_space(inp, a), model, device, strength=0.75)
    out = D.from_model_space(model_space_out, a)

    result = deep_end_result(inp, out, "M8", 405)
    g = check_no_harm([result])

    assert not g.passed, (
        f"expected the do-no-harm gate to catch the known M8 regression, but "
        f"it passed: control={result.input_err:.5f} model={result.model_err:.5f}"
    )
    assert any("M8" in f and "405" in f for f in g.failures)


# --- the deep-end proxy, now a gate function rather than a test fixture ----

def test_patch_chroma_bias_is_zero_on_a_neutral_field():
    """No colour structure -> no chroma bias. Anchors the metric's zero."""
    import numpy as np
    from gate import patch_chroma_bias, sky_mask

    img = np.full((256, 256, 3), 0.2, np.float32)
    assert patch_chroma_bias(img, sky_mask(img)) == pytest.approx(0.0, abs=1e-6)


def test_patch_chroma_bias_detects_patch_scale_colour_blotching():
    """The M8 failure signature: large-scale green/magenta patches. Single-
    pixel chroma noise must NOT register, or the metric would fire on every
    noisy image instead of on damage. Measured 2026-08-23 at the shipped
    scale=25px: speckle 0.00039, blotching 0.01592 -- a factor of 40. Drop the
    scale to 5px and the speckle figure rises to 0.0022 and breaks the first
    assertion, which is what makes that assertion load-bearing."""
    import numpy as np
    from gate import patch_chroma_bias, sky_mask

    rng = np.random.default_rng(0)
    base = np.full((256, 256, 3), 0.2, np.float32)
    mask = sky_mask(base)

    speckle = base + rng.normal(0, 0.02, base.shape).astype(np.float32)
    blotchy = base.copy()
    blotchy[:128, :, 1] += 0.02          # a big green patch
    blotchy[128:, :, 0] += 0.02          # a big red one

    assert patch_chroma_bias(speckle, mask) < 0.002
    assert patch_chroma_bias(blotchy, mask) > 0.005


def test_the_sky_mask_selects_the_dark_end_and_leaves_the_bright_end_out():
    """`sky_mask` is what keeps the metric off nebula cores, so it has to
    actually exclude the bright end -- on a flat field every pixel qualifies
    and the mask is untested by the two metric tests above."""
    import numpy as np
    from gate import sky_mask

    ramp = np.linspace(0.0, 1.0, 256, dtype=np.float32)
    img = np.repeat(np.tile(ramp, (256, 1))[:, :, None], 3, axis=2)
    mask = sky_mask(img, percentile=60.0)

    assert mask.mean() == pytest.approx(0.60, abs=0.01)
    assert mask[:, 0].all()               # the darkest column is sky
    assert not mask[:, -1].any()          # the brightest column is not


# --- the deep end, measured against a noise-matched control ---------------
#
# The bug this section exists for: `patch_chroma_bias` compared against the
# UNTOUCHED input, and that comparison is invalid. Removing pixel noise makes
# pre-existing low-frequency colour structure MORE visible -- it was always
# there, hidden under the speckle. Measured 2026-08-24 on the real M8 master
# with a plain Gaussian blur, which invents nothing and has no opinion about
# colour:
#
#     untouched master                    0.0407    --
#     blur sigma=0.6   (29% noise gone)   0.0437   1.07x
#     blur sigma=0.9   (48%)              0.0458   1.13x
#     blur sigma=1.3   (66%)              0.0478   1.18x
#     blur sigma=1.8   (79%)              0.0495   1.22x
#     n2n_v1 @1.0      (86%)              0.0520   1.28x
#
# The proxy rises monotonically with HOW MUCH noise was removed, whatever
# removed it, so the gate read "noise was removed" as "harm was done" and
# could not pass any working denoiser. (About a third of that rise is the
# display stretch re-deriving its own shadow clip from a less noisy image;
# the rest is genuine exposure of real structure. Matching the noise level
# fixes both at once, since two images with the same noise get near-identical
# stretch parameters.)


def _synthetic_deep_sky(seed: int = 0, h: int = 512, w: int = 512):
    """A deep-stack-like frame: faint large-scale colour structure under noise.

    The structure is what makes this fixture able to reproduce the bug at all
    -- on a scene with no low-frequency colour there is nothing for noise
    removal to expose, and a blur would score 1.00 under the old comparison
    too. Here it scores 5.3x, which is the bug, larger than life.
    """
    import numpy as np
    from scipy.ndimage import gaussian_filter

    rng = np.random.default_rng(seed)

    def lf(scale):
        return gaussian_filter(rng.normal(0, 1, (h, w)).astype(np.float32), scale)

    base = 0.02 + 0.004 * lf(60)
    img = np.stack([base + 0.0015 * lf(45) for _ in range(3)], axis=2)
    img += rng.normal(0, 0.002, img.shape).astype(np.float32)
    return img.astype(np.float32)


def test_noise_matched_blur_reaches_the_noise_level_it_was_asked_for():
    import numpy as np
    from gate import noise_matched_blur
    from noise import estimate_sigma

    img = _synthetic_deep_sky()
    target = estimate_sigma(img) * 0.4
    blurred, s = noise_matched_blur(img, target)

    assert estimate_sigma(blurred) == pytest.approx(target, rel=0.05)
    assert 0.2 < s < 6.0
    assert blurred.shape == img.shape
    # and it is a plain blur of the input, inventing nothing
    from scipy.ndimage import gaussian_filter
    assert np.allclose(blurred, gaussian_filter(img, (s, s, 0)))


def test_noise_matched_blur_returns_the_nearest_bound_when_the_target_is_out_of_reach():
    """Both ends are legitimate answers, not errors: a model may denoise less
    than the gentlest blur in the range, or more than the strongest. The caller
    still needs a control to compare against, so this clamps rather than
    raising -- an exception here would take down the whole gate on an
    otherwise fine model."""
    from gate import noise_matched_blur
    from noise import estimate_sigma

    img = _synthetic_deep_sky()
    sigma = estimate_sigma(img)

    _, s_hi = noise_matched_blur(img, 0.0, lo=0.2, hi=6.0)       # unreachably quiet
    _, s_lo = noise_matched_blur(img, sigma * 2, lo=0.2, hi=6.0)  # noisier than the input
    assert s_hi == 6.0
    assert s_lo == 0.2


def test_a_plain_blur_passes_the_deep_end_gate_that_the_untouched_input_fails():
    """THE regression test for this bug. A Gaussian blur invents nothing and
    has no opinion about colour, so it is the one thing that cannot be doing
    chroma damage -- if the deep-end gate fails it, the gate is measuring
    noise removal, not harm. Measured on this fixture: against the untouched
    input a sigma=1.5 blur reads 5.26x and fails; against a noise-matched
    control it reads 1.00 and passes."""
    from scipy.ndimage import gaussian_filter

    from gate import check_no_harm, deep_end_result, patch_chroma_bias, sky_mask, DepthResult
    from nocturne.core.autostretch import linked_stretch

    img = _synthetic_deep_sky()
    blurred = gaussian_filter(img, (1.5, 1.5, 0))
    sky = sky_mask(img)

    old = DepthResult("synthetic", 405,
                      patch_chroma_bias(linked_stretch(img, 0.25), sky),
                      patch_chroma_bias(linked_stretch(blurred, 0.25), sky))
    assert old.model_err / old.input_err > 3.0, "fixture no longer reproduces the bug"
    assert not check_no_harm([old]).passed, "the old comparison failed a plain blur"

    new = deep_end_result(img, blurred, "synthetic", 405)
    assert new.model_err / new.input_err == pytest.approx(1.0, abs=0.05)
    assert check_no_harm([new]).passed


def test_the_deep_end_gate_still_fails_invented_patch_chroma():
    """The positive control the tolerance is measured against. A model that
    smooths AND paints 30px green/magenta patches must fail -- otherwise the
    fix above would have removed the check rather than corrected it.

    Amplitude 0.0002 linear here (a tenth of this fixture's noise sigma) reads
    5.06x. On the real M8 master, on top of n2n_v1's own output, the crossing
    point is 0.37x the sky sigma -- see DEEP_END_TOLERANCE."""
    from scipy.ndimage import gaussian_filter
    import numpy as np

    from gate import check_no_harm, deep_end_result

    img = _synthetic_deep_sky()
    honest = gaussian_filter(img, (1.5, 1.5, 0))

    rng = np.random.default_rng(99)
    blob = gaussian_filter(rng.normal(0, 1, img.shape[:2]).astype(np.float32), 30)
    blob /= blob.std()
    harmful = honest.copy()
    harmful[:, :, 1] += 0.0002 * blob            # green where the blob is positive,
    harmful[:, :, 0] -= 0.0001 * blob            # magenta where it is negative
    harmful[:, :, 2] -= 0.0001 * blob

    r = deep_end_result(img, harmful, "synthetic", 405)
    assert r.model_err / r.input_err > 3.0
    g = check_no_harm([r])
    assert not g.passed
    assert any("synthetic" in f for f in g.failures)


def test_a_results_own_tolerance_does_not_widen_the_others():
    """The deep-end proxy carries a tolerance because it is measured against a
    blur rather than against truth. The held-out pairs are measured against
    real ground truth and must keep zero tolerance -- "slightly worse than the
    truth-based input" is still worse."""
    from gate import DepthResult, check_no_harm

    proxy = DepthResult("M8-deep-proxy", 405, 1.00, 1.10, 0.15)
    truth_based = DepthResult("NGC6888", 118, 1.00, 1.01)
    assert check_no_harm([proxy]).passed
    g = check_no_harm([proxy, truth_based])
    assert not g.passed
    assert g.failures == [f for f in g.failures if "NGC6888" in f]


@pytest.mark.skipif(
    not os.path.isfile(_M8_MASTER),
    reason=f"needs the real M8 master ({_M8_MASTER}), not tracked in git",
)
def test_a_plain_blur_of_the_real_m8_master_passes_the_deep_end_gate():
    """The same regression, on the image the gate actually runs on. This is
    the one that would have caught the bug: the old comparison fails a blur at
    every strength (1.07x at 29% noise removed, up to 1.22x at 79%), and each
    of those blurs is by construction harmless."""
    from scipy.ndimage import gaussian_filter
    from astropy.io import fits

    from evaluate import _hwc
    from gate import check_no_harm, deep_end_result, patch_chroma_bias, sky_mask
    from nocturne.core.autostretch import linked_stretch

    inp = _hwc(fits.getdata(_M8_MASTER))
    sky = sky_mask(inp)
    base = patch_chroma_bias(linked_stretch(inp, 0.25), sky)

    for blur_sigma, old_ratio in ((0.9, 1.13), (1.8, 1.22)):
        blurred = gaussian_filter(inp, (blur_sigma, blur_sigma, 0))
        against_input = patch_chroma_bias(linked_stretch(blurred, 0.25), sky) / base
        assert against_input == pytest.approx(old_ratio, abs=0.02), (
            "the old input-relative comparison no longer reads what it read on "
            "2026-08-24; re-measure before trusting the rest of this test")

        r = deep_end_result(inp, blurred, "M8-deep-proxy", 405)
        assert r.model_err / r.input_err == pytest.approx(1.0, abs=0.02)
        assert check_no_harm([r]).passed, (
            f"a plain sigma={blur_sigma} blur must not fail a do-no-harm gate: "
            f"control {r.input_err:.5f} vs model {r.model_err:.5f}")


# --- the deep end, part two: is it a denoiser or is it just a blur? --------
#
# The chroma check above cannot see the 2026-08-22 failure. Measured
# 2026-08-24 against a noise-matched control, s30_v2 (the checkpoint that
# blotched the M8 master) reads 1.043/1.009/1.014 at strengths 0.75/1.0/1.5
# where clean n2n_v1 reads 1.041/1.032/1.093 -- three tenths of a point apart,
# and at two strengths the BAD model scores better.
#
# What does separate them is a different question entirely: how much fine
# luminance detail survived, relative to the same noise-matched blur. A blur
# that removed the same noise is the trivial baseline; a denoiser earning its
# name keeps more standing than that. s30_v2 does not -- in luminance terms it
# IS a blur. See DETAIL_RETENTION_FLOOR for the full table.
#
# Both checks are kept and both must pass. Neither subsumes the other, and the
# two tests below are what prove it: a plain blur passes chroma and fails
# detail; an output that keeps every star and paints green blotches over the
# background does the exact reverse.


def _synthetic_deep_sky_with_detail(seed: int = 0, h: int = 512, w: int = 512,
                                    noise: float = 0.002):
    """(truth, noisy) -- a deep-sky-like frame with REAL fine structure in it.

    `_synthetic_deep_sky` cannot serve the detail check: its scene varies only
    at 45-60px, so at the 2px high-pass scale it is pure noise, and a blur
    retains exactly as much of it as a perfect denoiser does. Fine filaments
    and stars are the thing a blur destroys and a denoiser must not, so they
    have to exist before the metric has anything to measure.
    """
    import numpy as np
    from scipy.ndimage import gaussian_filter

    rng = np.random.default_rng(seed)

    def lf(scale):
        return gaussian_filter(rng.normal(0, 1, (h, w)).astype(np.float32), scale)

    base = 0.02 + 0.004 * lf(60)
    truth = np.stack([base + 0.0015 * lf(45) for _ in range(3)], axis=2)
    bright = np.clip((base - base.min()) / (base.max() - base.min()), 0, 1)
    filaments = 0.0035 * lf(2.5) * bright
    stars = np.zeros((h, w), np.float32)
    ys, xs = rng.integers(6, h - 6, 500), rng.integers(6, w - 6, 500)
    stars[ys, xs] = (rng.lognormal(0, 0.8, 500) * 0.01).astype(np.float32)
    stars = gaussian_filter(stars, 1.1)
    truth = truth + (filaments + stars)[:, :, None]
    noisy = truth + rng.normal(0, noise, truth.shape).astype(np.float32)
    return truth.astype(np.float32), noisy.astype(np.float32)


def test_highpass_detail_falls_when_fine_structure_is_smoothed_away():
    """Anchors the direction of the raw metric before anything inverts it:
    more smoothing must read LOWER, or every conclusion drawn from it flips."""
    from scipy.ndimage import gaussian_filter

    from gate import highpass_detail, sky_mask

    _, noisy = _synthetic_deep_sky_with_detail()
    structure = ~sky_mask(noisy)
    sharp = highpass_detail(noisy, structure)
    soft = highpass_detail(gaussian_filter(noisy, (2.0, 2.0, 0)), structure)
    assert 0.0 < soft < sharp


def test_highpass_detail_measures_inside_the_mask_it_is_given():
    """`patch_chroma_bias` takes the SKY mask and measures inside it; this one
    takes the structure mask, which is the sky mask's complement. One inverted
    argument at a call site would silently measure the wrong half of the frame
    and still return a plausible number, so pin it."""
    import numpy as np

    from gate import highpass_detail

    rng = np.random.default_rng(4)
    img = np.full((128, 128, 3), 0.02, np.float32)
    left = np.zeros((128, 128), bool)
    left[:, :64] = True
    img[:, :64] += rng.normal(0, 0.002, (128, 64, 3)).astype(np.float32)

    assert highpass_detail(img, left) > 1e-4
    assert highpass_detail(img, ~left) == pytest.approx(0.0, abs=1e-9)


def test_a_plain_blur_fails_the_detail_check_and_passes_the_chroma_one():
    """Half of what proves the two deep-end checks are not the same check.

    A Gaussian blur invents no colour, so the chroma check clears it -- and
    that is correct, it is doing no chroma harm. It is also, in luminance
    terms, nothing but a blur, which is exactly what the detail check exists
    to reject. Measured on this fixture: chroma 1.000, retention 1.000."""
    from scipy.ndimage import gaussian_filter

    from gate import DETAIL_RETENTION_FLOOR, check_no_harm, deep_end_results

    # A blur is its OWN noise-matched control, so it retains 1.000 by
    # construction. A floor at or below 1.0 therefore demands nothing at all
    # and the check passes everything -- assert it directly, because on a
    # machine without the external volume the real-master test that would
    # otherwise notice is skipped.
    assert DETAIL_RETENTION_FLOOR > 1.0

    _, noisy = _synthetic_deep_sky_with_detail()
    blurred = gaussian_filter(noisy, (1.5, 1.5, 0))
    chroma, detail = deep_end_results(noisy, blurred, "synthetic", 405)
    assert 1.0 / detail.model_err == pytest.approx(1.0, abs=0.02)

    assert check_no_harm([chroma]).passed, "a blur invents no colour"
    g = check_no_harm([detail])
    assert not g.passed, "a blur must never clear a check that demands more than a blur"
    assert any("synthetic-detail" in f for f in g.failures)
    assert not check_no_harm([chroma, detail]).passed


def test_invented_chroma_over_preserved_detail_fails_chroma_and_passes_detail():
    """The other half. This output keeps every star and filament -- the detail
    check has no complaint -- and paints 30px green/magenta patches across the
    background, which is the 2026-08-22 failure and the chroma check's job.
    Neither check subsumes the other, and dropping either loses a real
    failure mode."""
    import numpy as np
    from scipy.ndimage import gaussian_filter

    from gate import check_no_harm, deep_end_results

    truth, noisy = _synthetic_deep_sky_with_detail()
    rng = np.random.default_rng(11)
    honest = (truth + rng.normal(0, 0.0006, truth.shape)).astype(np.float32)

    blob = gaussian_filter(rng.normal(0, 1, truth.shape[:2]).astype(np.float32), 30)
    blob /= blob.std()
    harmful = honest.copy()
    harmful[:, :, 1] += 0.0002 * blob
    harmful[:, :, 0] -= 0.0001 * blob
    harmful[:, :, 2] -= 0.0001 * blob

    chroma, detail = deep_end_results(noisy, harmful, "synthetic", 405)
    assert check_no_harm([detail]).passed, "it kept the detail; only the colour is wrong"
    assert not check_no_harm([chroma]).passed
    assert not check_no_harm([chroma, detail]).passed


def test_a_detail_preserving_denoiser_passes_the_detail_check():
    """The check must not simply fail everything -- that is the exact failure
    it was built to correct in the chroma check next door. A denoiser that
    keeps the structure and drops the noise reads 1.30 on this fixture."""
    import numpy as np

    from gate import DETAIL_RETENTION_FLOOR, check_no_harm, detail_result

    truth, noisy = _synthetic_deep_sky_with_detail()
    rng = np.random.default_rng(11)
    honest = (truth + rng.normal(0, 0.0006, truth.shape)).astype(np.float32)

    r = detail_result(noisy, honest, "synthetic", 405)
    assert check_no_harm([r]).passed
    retained = 1.0 / r.model_err              # model_err is 1/retention
    assert r.input_err == pytest.approx(1.0 / DETAIL_RETENTION_FLOOR)
    assert retained > DETAIL_RETENTION_FLOOR
    assert retained == pytest.approx(1.30, abs=0.10)


def test_the_detail_result_is_inverted_so_less_detail_reads_as_more_error():
    """THE test for the direction of the inversion. `check_no_harm` fails when
    model_err > input_err, so retention has to go in upside down -- and an
    inversion that got the sign wrong would produce a check that passes
    everything, silently, which is precisely the failure being fixed here.

    Pinned by moving the floor across a FIXED measured retention: raise the bar
    above what the output achieved and it must fail, lower it and it must pass.
    A result that ignored the floor, or read the ratio the right way up, would
    behave identically on both sides."""
    import numpy as np

    from gate import check_no_harm, detail_result

    truth, noisy = _synthetic_deep_sky_with_detail()
    rng = np.random.default_rng(11)
    honest = (truth + rng.normal(0, 0.0006, truth.shape)).astype(np.float32)

    at_one = detail_result(noisy, honest, "synthetic", 405, floor=1.0)
    retained = at_one.model_err ** -1          # input_err is 1/1.0 == 1.0
    assert retained == pytest.approx(1.30, abs=0.10)

    assert check_no_harm([detail_result(noisy, honest, "s", 405,
                                        floor=retained * 0.9)]).passed
    assert not check_no_harm([detail_result(noisy, honest, "s", 405,
                                            floor=retained * 1.1)]).passed
    # ... and the tolerance carried on the result must not soften it, the way
    # the chroma result's 0.15 legitimately does.
    assert detail_result(noisy, honest, "s", 405).tolerance == 0.0


def test_both_deep_end_checks_are_measured_against_one_shared_control():
    """Two searches for the control would be two different blurs (brentq stops
    at xtol=0.02px) and two minutes of a 4K master's time. More importantly the
    two checks would then be answering about different baselines, and "both
    must pass" would stop meaning one thing."""
    import gate

    _, noisy = _synthetic_deep_sky_with_detail()
    from scipy.ndimage import gaussian_filter
    blurred = gaussian_filter(noisy, (1.5, 1.5, 0))

    calls = []
    real = gate.noise_matched_blur
    try:
        gate.noise_matched_blur = lambda *a, **k: (calls.append(1) or real(*a, **k))
        chroma, detail = gate.deep_end_results(noisy, blurred, "synthetic", 405)
    finally:
        gate.noise_matched_blur = real

    assert len(calls) == 1
    assert chroma.target == "synthetic-chroma" and detail.target == "synthetic-detail"
    assert chroma.depth == detail.depth == 405


# --- the real positive control this project has never had -----------------

_M45_MASTER = "/Volumes/Work2/Images/Astro/Work/M 45_sub/M45_280x10s_47min.fits"
_M45_DEPTH = 280
_M8_DEPTH = 405
_N2N_RUN = "/Volumes/Work2/Images/Astro/denoise_runs/n2n_v1/best.pt"

# 0.75 is nocturne.core.denoise_model.denoise's default -- the strength a user
# actually gets. It is NOT the strength nightly's configs run the gate at
# (1.0), and that gap is a real limit of the separation below, written down in
# DETAIL_RETENTION_FLOOR rather than hidden here.
_APP_DEFAULT_STRENGTH = 0.75

_REAL_MASTERS = ((_M8_MASTER, "M8", _M8_DEPTH), (_M45_MASTER, "M45", _M45_DEPTH))

_needs_masters = pytest.mark.skipif(
    not all(os.path.isfile(p) for p, _, _ in _REAL_MASTERS),
    reason=("needs the real M8 and M45 masters on an external volume not "
            "tracked in git -- not a code failure if that drive isn't mounted"),
)


def _load_master(path):
    from astropy.io import fits

    from evaluate import _hwc
    return _hwc(fits.getdata(path))


def _denoise_v2(inp, strength):
    """s30_v2, the incident checkpoint: 3-channel, pre-conditioning."""
    import torch

    import data as D
    from model import DenoiseUNet

    device = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
    ck = torch.load(_V2_RUN, map_location=device)
    assert ck["model"]["enc.0.0.weight"].shape[1] == 3
    m = DenoiseUNet(base=ck.get("args", {}).get("base", 32), in_ch=3).to(device)
    m.load_state_dict(ck["model"])
    m.eval()
    a = D._ASINH_A
    return D.from_model_space(
        _apply_unconditioned(D.to_model_space(inp, a), m, device, strength), a)


def _denoise_n2n(inp, strength):
    """n2n_v1, the clean checkpoint: 4-channel, sigma-conditioned."""
    import torch

    import data as D
    import evaluate
    from model import DenoiseUNet

    device = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
    ck = torch.load(_N2N_RUN, map_location=device)
    assert ck["model"]["enc.0.0.weight"].shape[1] == 4
    m = DenoiseUNet(base=ck.get("args", {}).get("base", 32), in_ch=4).to(device)
    m.load_state_dict(ck["model"])
    m.eval()
    a = D._ASINH_A
    return D.from_model_space(
        evaluate.apply_model(D.to_model_space(inp, a), m, device, strength=strength), a)


@_needs_masters
def test_a_plain_blur_of_the_real_masters_fails_the_detail_check():
    """The degenerate case, on the images the gate really runs on. A blur is
    its own noise-matched control, so it retains 1.000 by construction and must
    fail -- if it ever passes, the check has stopped demanding anything. It
    must still PASS the chroma check on the same images, which is what keeps
    the two checks from collapsing into one."""
    from scipy.ndimage import gaussian_filter

    from gate import check_no_harm, deep_end_results

    for path, name, depth in _REAL_MASTERS:
        inp = _load_master(path)
        for blur_sigma in (1.0, 2.3):
            blurred = gaussian_filter(inp, (blur_sigma, blur_sigma, 0))
            chroma, detail = deep_end_results(inp, blurred, name, depth)

            assert check_no_harm([chroma]).passed, (
                f"{name}: a sigma={blur_sigma} blur invents no colour")
            retained = 1.0 / detail.model_err
            assert retained == pytest.approx(1.0, abs=0.02), (
                f"{name} sigma={blur_sigma}: a blur must read 1.000 against its "
                f"own control, read {retained:.3f}")
            g = check_no_harm([chroma, detail])
            assert not g.passed
            assert [f for f in g.failures if f"{name}-detail" in f]


@_needs_masters
@pytest.mark.skipif(not os.path.isfile(_V2_RUN),
                    reason=f"needs the s30_v2 checkpoint ({_V2_RUN})")
def test_the_incident_checkpoint_fails_the_deep_end_gate_on_both_real_masters():
    """THE positive control, and the first one on this project made of a real
    checkpoint rather than a synthetic injection.

    s30_v2 is the model that broke the 405-frame M8 master into green and
    magenta blotches. The chroma proxy cannot see it -- that is what the
    xfail(strict) replay above records. The detail check can: at the app's own
    default strength it retains LESS fine luminance detail than a plain
    Gaussian blur that removed the same noise (0.979 on M8, 0.942 on M45,
    measured 2026-08-24), which is to say that in luminance terms it is a blur.

    Both masters, because one image is an anecdote. Read the limits in
    DETAIL_RETENTION_FLOOR before reading this as a general harm detector: it
    is one checkpoint, and the separation holds at strength 0.75 but not at
    1.0."""
    from gate import check_no_harm, deep_end_results

    for path, name, depth in _REAL_MASTERS:
        inp = _load_master(path)
        out = _denoise_v2(inp, _APP_DEFAULT_STRENGTH)
        chroma, detail = deep_end_results(inp, out, name, depth)

        assert 1.0 / detail.model_err < 1.0, (
            f"{name}: expected the incident checkpoint to retain less detail "
            f"than a plain blur, got {1.0 / detail.model_err:.3f}")
        assert check_no_harm([chroma]).passed, (
            f"{name}: the chroma proxy is blind to this checkpoint -- if that "
            f"has changed, the xfail(strict) replay above is now an XPASS and "
            f"this test's premise needs re-reading")
        g = check_no_harm([chroma, detail])
        assert not g.passed
        assert g.failures == [f for f in g.failures if f"{name}-detail" in f]


@_needs_masters
@pytest.mark.skipif(not os.path.isfile(_N2N_RUN),
                    reason=f"needs the n2n_v1 checkpoint ({_N2N_RUN})")
def test_the_clean_checkpoint_passes_the_deep_end_gate_on_both_real_masters():
    """The negative control, without which the one above proves nothing: a
    check that fails everything would satisfy it just as well. n2n_v1 is
    visibly clean and better balanced than the input, and it must pass BOTH
    deep-end checks on BOTH masters -- retention 1.196 on M8 and 1.189 on M45
    against a 1.10 floor, which is also where that floor's headroom comes
    from."""
    from gate import DETAIL_RETENTION_FLOOR, check_no_harm, deep_end_results

    for path, name, depth in _REAL_MASTERS:
        inp = _load_master(path)
        out = _denoise_n2n(inp, _APP_DEFAULT_STRENGTH)
        chroma, detail = deep_end_results(inp, out, name, depth)

        retained = 1.0 / detail.model_err
        assert retained > DETAIL_RETENTION_FLOOR, (
            f"{name}: the clean checkpoint reads {retained:.3f}, at or under "
            f"the floor -- the floor has no headroom left")
        g = check_no_harm([chroma, detail])
        assert g.passed, g.failures
