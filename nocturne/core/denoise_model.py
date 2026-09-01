"""Nocturne's own denoiser: ONNX inference in pure NumPy.

No torch. The app ships this file, an ONNX graph and onnxruntime; training
lives entirely outside the package in `training/` and never travels with the
build.

The model predicts NOISE rather than a clean image, so the result is
`input - strength * predicted`, and strength 0 provably returns the input
untouched. It runs on LINEAR data, before Stretch, because that is what it was
trained on: a stretch derives its parameters from each image's own statistics,
so a denoiser applied after one sees a transfer function it cannot know about.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache

import numpy as np
from scipy.ndimage import gaussian_filter

from .image import AstroImage

_MODEL_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "assets", "models")
_TILE = 256
_OVERLAP = 32

_SIGMA_HP_SIGMA = 2.0        # high-pass scale: removes scene, keeps noise
_SIGMA_DARK_FRACTION = 0.60  # measure on the darker 60%, away from nebula cores

# Default if a model's .json predates the conditioning channel (none should,
# but this keeps a stale metadata file from crashing rather than mis-scaling).
# Mirrors training/model.py::SIGMA_SCALE -- see that file for how it was measured.
_DEFAULT_SIGMA_SCALE = 0.0015


def estimate_sigma(img: np.ndarray) -> float:
    """Robust noise sigma, in the units of whatever array it is given.

    Duplicated verbatim from `training/noise.py` rather than imported: the
    sigma fed to the model as a conditioning channel must be computed
    identically at training and inference time, and this package must never
    import training code (or torch). See that file for why the mask is built
    from smoothed luminance and MAD is pooled per-channel rather than on the
    channel-averaged image -- both avoid biases that make the naive version
    read noise levels wrong by 2-3x.
    """
    img = np.asarray(img, np.float32)
    if img.ndim == 2:
        img = img[:, :, None]
    lum = img.mean(axis=2)
    bg = gaussian_filter(lum, _SIGMA_HP_SIGMA)
    mask = bg <= np.percentile(bg, _SIGMA_DARK_FRACTION * 100.0)
    parts = []
    for c in range(img.shape[2]):
        chan = img[:, :, c]
        hp = chan - gaussian_filter(chan, _SIGMA_HP_SIGMA)
        parts.append(hp[mask])
    v = np.concatenate(parts) if parts else np.empty(0, np.float32)
    if v.size == 0:
        return 0.0
    return float(1.4826 * np.median(np.abs(v - np.median(v))))


def model_path(sensor: str = "s30") -> str:
    return os.path.join(_MODEL_DIR, f"denoise_{sensor}_v1.onnx")


def available(sensor: str = "s30") -> bool:
    return os.path.isfile(model_path(sensor))


def metadata(sensor: str = "s30") -> dict:
    p = os.path.splitext(model_path(sensor))[0] + ".json"
    if not os.path.isfile(p):
        return {}
    with open(p) as fh:
        return json.load(fh)


@lru_cache(maxsize=2)
def _session(path: str):
    try:
        import onnxruntime as ort
    except ImportError as exc:
        # onnxruntime is 64 MB and is NOT bundled: AI Denoise is built but not
        # shipped (see ui/pipeline.py), and carrying an inference runtime for an
        # unreachable step cost every launch. Measured 2026-09-01: excluding it
        # took a cold start from 9.2 s to 1.0 s on this machine.
        #
        # The one way to arrive here is a saved project made before v0.18.0,
        # when the step WAS in the pipeline. Say that, rather than letting an
        # ImportError for a library the user never heard of reach them.
        raise RuntimeError(
            "This project uses AI Denoise, which is not part of this version of "
            "Nocturne. The step was withdrawn in v0.18.0 because the model "
            "damaged deep stacks. Every other step in the project will still "
            "apply; remove this one to open it."
        ) from exc
    opts = ort.SessionOptions()
    opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    return ort.InferenceSession(path, opts, providers=["CPUExecutionProvider"])


_EXPECTED_IN_CH = 4  # 3 image channels + 1 sigma-conditioning channel


def _check_conditioned(sess, sensor: str) -> None:
    """Refuse a pre-conditioning model outright rather than let onnxruntime's
    raw shape error reach the user.

    There is deliberately NO 3-channel fallback path here. The 3-channel model
    is the one that visibly broke a 405-frame master into colour blotches; a
    silent fallback is exactly how a known-harmful artifact keeps running
    after everyone believes it was replaced.
    """
    found = sess.get_inputs()[0].shape[1]
    if found != _EXPECTED_IN_CH:
        raise RuntimeError(
            f"denoise model '{sensor}' expects {found} input channels, not "
            f"{_EXPECTED_IN_CH}. This is the OLD model, trained before noise "
            "conditioning existed -- it does not know how noisy its input is "
            "and will over-smooth a clean stack. Retrain and re-export it "
            "with the current 4-channel pipeline (training/export_onnx.py) "
            "before it can be used.")


def _to_model_space(x: np.ndarray, a: float) -> np.ndarray:
    # float32 explicitly: np.arcsinh(1.0/a) is a numpy float64 scalar and would
    # otherwise upcast the whole array.
    return (np.arcsinh(x / a) / np.arcsinh(1.0 / a)).astype(np.float32, copy=False)


def _from_model_space(y: np.ndarray, a: float) -> np.ndarray:
    return (np.sinh(y * np.arcsinh(1.0 / a)) * a).astype(np.float32, copy=False)


def _feather(tile: int, overlap: int) -> np.ndarray:
    """Blend weights that taper toward a tile's edge but never reach zero.

    The +1 matters. With a ramp starting at 0, the image's outermost corner is
    covered by exactly one tile at weight 1e-6, and dividing by a weight that
    small amplifies float32 error enormously — measured at 3.8e-04 on pixel
    (0,0) while every other pixel agreed to 7e-09. Interior seams are fine
    because neighbouring tiles overlap them; only the frame's own corners have a
    single contributor, which is exactly where a zero weight is unrecoverable.
    """
    r = np.minimum(np.arange(tile), np.arange(tile)[::-1]).astype(np.float32) + 1.0
    r = np.clip(r / max(overlap, 1), 0.0, 1.0)
    return (r[:, None] * r[None, :])[:, :, None]


def denoise(img: AstroImage, strength: float = 0.75, *, sensor: str = "s30",
            on_progress=None) -> AstroImage:
    """Apply the model. `strength` scales the predicted noise; 0 is a no-op."""
    if not img.is_linear:
        raise ValueError(
            "the denoise model runs on linear data, before Stretch — it was "
            "trained there and its input transform assumes it")
    if not available(sensor):
        raise FileNotFoundError(f"no denoise model for {sensor}: {model_path(sensor)}")
    if strength <= 0:
        return AstroImage(img.data.copy(), is_linear=True, metadata=dict(img.metadata))

    a = float(metadata(sensor).get("asinh_a", 0.01))
    sigma_scale = float(metadata(sensor).get("sigma_scale", _DEFAULT_SIGMA_SCALE))
    sess = _session(model_path(sensor))
    _check_conditioned(sess, sensor)
    name = sess.get_inputs()[0].name

    src = _to_model_space(np.ascontiguousarray(img.data, np.float32), a)
    if src.ndim == 2:
        src = np.repeat(src[:, :, None], 3, axis=2)
    H, W, _ = src.shape

    # Measured ONCE on the whole model-space image, not per tile: every tile
    # of a given image must be told the same thing about how noisy it is, or
    # a 405-frame master's already-clean edges would read as noisier than its
    # centre for no reason connected to the actual noise.
    sigma_val = estimate_sigma(src)
    smap_value = np.float32(sigma_val / sigma_scale)
    sigma_channel = np.full((1, 1, _TILE, _TILE), smap_value, np.float32)

    out = np.zeros_like(src)
    wsum = np.zeros((H, W, 1), np.float32)
    win = _feather(_TILE, _OVERLAP)
    step = _TILE - _OVERLAP
    ys = list(range(0, max(H - _OVERLAP, 1), step))
    xs = list(range(0, max(W - _OVERLAP, 1), step))
    total = len(ys) * len(xs)
    done = 0
    for y in ys:
        for x in xs:
            y0, x0 = min(y, max(H - _TILE, 0)), min(x, max(W - _TILE, 0))
            patch = src[y0:y0+_TILE, x0:x0+_TILE]
            if patch.shape[0] != _TILE or patch.shape[1] != _TILE:
                continue
            rgb = patch.transpose(2, 0, 1)[None]
            inp = np.ascontiguousarray(np.concatenate([rgb, sigma_channel], axis=1))
            noise = sess.run(None, {name: inp})[0][0].transpose(1, 2, 0)
            out[y0:y0+_TILE, x0:x0+_TILE] += (patch - strength * noise) * win
            wsum[y0:y0+_TILE, x0:x0+_TILE] += win
            done += 1
            if on_progress is not None and done % 8 == 0:
                on_progress(done, total)
    out /= np.maximum(wsum, 1e-6)

    data = np.clip(_from_model_space(out, a), 0.0, 1.0)
    if img.data.ndim == 2:
        data = data.mean(axis=2)
    return AstroImage(data.astype(np.float32), is_linear=True,
                      metadata=dict(img.metadata))
