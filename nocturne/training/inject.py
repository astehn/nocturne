"""Manufacture a noisy view of a clean master, out of the camera's own noise.

The denoiser had no supervision at the depths Andreas actually shoots. Training
pairs were formed from two stacks of the same sky, one deeper than the other --
but at 300+ frames his stack is already among the cleanest images in the
archive, so there was nothing cleaner to point at and the lesson was empty. The
2026-08-24 postmortem has the measurements.

So invert it: take the clean master and dirty it deliberately, by a chosen
amount. The dirt is not invented. Subtract one disjoint half-stack from the
other and the sky cancels, leaving that camera's real noise on that real field
-- carrying its signal dependence, its per-channel imbalance, and the spatial
correlation that registration and demosaicing put there. A Gaussian generator
reproduces none of that.
"""
from __future__ import annotations

import math

import numpy as np


def _checked(a: np.ndarray, b: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    a = np.asarray(a, np.float32)
    b = np.asarray(b, np.float32)
    if a.shape != b.shape:
        raise ValueError(f"halves differ in shape: {a.shape} vs {b.shape}")
    return a, b


def noise_field(half_a: np.ndarray, half_b: np.ndarray) -> np.ndarray:
    """Pure noise with the statistics of a stack the depth of ONE half.

    The sqrt(2) is not cosmetic. For two disjoint n-frame halves,
    var(A - B) = 2*sigma1^2/n, so the difference is sqrt(2) noisier than either
    half. Dividing it back gives sigma1^2/n -- exactly what a real n-frame stack
    carries. Omit it and every manufactured input is 41% noisier than the frame
    count it claims to represent, which would quietly bias the whole sigma
    conditioning.
    """
    a, b = _checked(half_a, half_b)
    return (a - b) / math.sqrt(2.0)


def target_from_halves(half_a: np.ndarray, half_b: np.ndarray) -> np.ndarray:
    """The clean side: both halves averaged, i.e. the full stack.

    Uncorrelated with `noise_field` of the same halves, because
    cov(A-B, (A+B)/2) = (var A - var B)/2 = 0 for equal halves. That is what
    makes `target + k*field` honest: the added noise is independent of the
    noise already in the target rather than a scaled copy of it.
    """
    a, b = _checked(half_a, half_b)
    return (a + b) / 2.0
