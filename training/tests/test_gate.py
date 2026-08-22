import os
import sys

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
# proxy is blind to. It exists to make sure THIS regression, on THIS master,
# can never silently start passing again.

_M8_MASTER = "/Volumes/Work2/Images/Astro/Work/M8 Total/lights/M8_405x10s_68min.fits"
_V2_RUN = "/Volumes/Work2/Images/Astro/denoise_runs/s30_v2/best.pt"


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


def _patch_chroma_bias(img_hwc, sky_mask, scale=25.0):
    """Large-scale colour-difference std within `sky_mask` -- the blotch
    signature. `scale` (px) is well above single-pixel noise and well below
    the whole frame; empirically the regression signal is stable across a
    wide strength range with this value, so it is not a knife-edge tuning."""
    from scipy.ndimage import gaussian_filter

    r, g, b = img_hwc[:, :, 0], img_hwc[:, :, 1], img_hwc[:, :, 2]
    gm = gaussian_filter((r + b) / 2 - g, scale)
    rb = gaussian_filter(r - b, scale)
    return float((gm[sky_mask].std() ** 2 + rb[sky_mask].std() ** 2) ** 0.5)


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
