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


# The proxy now lives in gate.py, where nightly.py can call it on every run
# instead of it existing only inside this one replay test. Aliased rather than
# rewritten at the call sites so the v2 positive control below stays literally
# the test that was proven to catch the real regression.
from gate import patch_chroma_bias as _patch_chroma_bias  # noqa: E402


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
    import numpy as np
    import torch
    from astropy.io import fits

    import data as D
    from evaluate import _hwc
    from model import DenoiseUNet
    from gate import check_no_harm, DepthResult
    from nocturne.core.autostretch import linked_stretch

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

    lum = inp.mean(axis=2)
    sky = lum <= np.percentile(lum, 60)  # matches noise.py's own dark-region convention

    input_err = _patch_chroma_bias(linked_stretch(inp, 0.25), sky)
    model_err = _patch_chroma_bias(linked_stretch(out, 0.25), sky)

    result = DepthResult("M8", 405, input_err, model_err)
    g = check_no_harm([result])

    assert not g.passed, (
        f"expected the do-no-harm gate to catch the known M8 regression, but "
        f"it passed: input_err={input_err:.5f} model_err={model_err:.5f}"
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
