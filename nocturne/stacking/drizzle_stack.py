from __future__ import annotations

import numpy as np

DRIZZLE_SCALE = 2      # ×2 output grid — the only supported factor (kept simple)
KERNEL = "square"      # flux-conserving (gaussian/lanczos do NOT conserve flux)
PIXFRAC = 0.9          # drop shrink factor — the fraction of each input pixel
                       # poured onto the finer grid. Was 0.6. Measured 2026-08-31
                       # on 100 IC 1396A frames: 0.6 gives marginally tighter
                       # stars (FWHM 3.43 vs 3.50 on the 2x grid) but 0.9 detects
                       # MORE of them (7,625 vs 6,579) and adds slightly less
                       # large-scale structure — fuller coverage, better SNR. 0.9
                       # is also what Siril and PixInsight users run.


# Measured 2026-08-31 on this machine: 60 frames of 3840x2160 took 220 s end to
# end through run_stack, against 21 s for a normal stack of the same subs. That
# is 3.7 s per frame, and it scales with INPUT pixels because both passes walk
# every input pixel — the warp-and-measure pass and the gather-and-drizzle pass.
_SECONDS_PER_FRAME = 3.7
_REFERENCE_PIXELS = 3840 * 2160


def estimate_seconds(n_frames: int, shape) -> float:
    """Roughly how long a drizzle stack will take, for the dialog to say BEFORE
    the button is pressed.

    Andreas asked for this after a 314-frame run: "it would also be good if the
    tool could do an estimation of how much time a drizzle stack will take based
    on the number of selected subs, that way the user can actually decide for
    themselves if its worth it prior to actually pressing the button."

    Deliberately a rough number on a fixed constant rather than a benchmark: it
    only has to answer "minutes or an hour".

    KNOWN TO UNDER-PREDICT AT SCALE, and returned as a floor for that reason.
    The constant comes from 60 frames and is extrapolated linearly; Andreas ran
    314 and reported it took considerably longer than the 19 minutes this
    predicts. There is a mechanism, and it is not linear: BOTH passes read every
    frame, which is ~1 GB at 60 subs and ~5 GB at 314. At 60 the page cache
    holds them and the second pass reads nothing from disk; at 314 it cannot.
    A measurement at full scale is pending — recalibrate this constant from it
    rather than trusting the small-N number.
    """
    h, w = (shape[0], shape[1]) if shape else (2160, 3840)
    return max(1.0, n_frames * _SECONDS_PER_FRAME * (h * w) / _REFERENCE_PIXELS)


def estimate_megabytes(shape) -> float:
    """Size of the master a drizzle stack writes: 4x the pixels, 3 channels,
    float32. A real 3840x2160 stack came out at 398 MB."""
    h, w = (shape[0], shape[1]) if shape else (2160, 3840)
    return (h * DRIZZLE_SCALE) * (w * DRIZZLE_SCALE) * 3 * 4 / 1e6


def build_pixmap(matrix: np.ndarray, in_shape: tuple[int, int], scale: int) -> np.ndarray:
    """Per-input-pixel output (x, y) coords for drizzle. `matrix` maps input (x,y)
    to reference (x,y); the drizzle output grid is the reference scaled by `scale`."""
    h, w = in_shape
    ys, xs = np.mgrid[0:h, 0:w]
    pts = np.stack([xs.ravel(), ys.ravel(), np.ones(h * w)], axis=0)   # (3, N) = (x,y,1)
    out = np.asarray(matrix, dtype=np.float64) @ pts
    xo = out[0] / out[2] * scale
    yo = out[1] / out[2] * scale
    return np.stack([xo.reshape(h, w), yo.reshape(h, w)], axis=-1).astype(np.float64)


def drizzle_integrate(items, in_shape, n_channels, *, pixfrac=PIXFRAC):
    """Drizzle-average `items` (data, matrix, weight_or_None) onto a DRIZZLE_SCALE×
    master. One `Drizzle` accumulator per channel; same pixmap feeds all channels
    of a given frame.

    Normalization: with `in_units="counts"`, the underlying `drizzle` library's
    `out_img` is *already* the per-pixel weight-normalized mean (it divides by
    the accumulated weight internally) -- it is not a raw weighted sum that
    still needs dividing by `out_wht`. Verified empirically: a constant input
    reproduces the same constant in `out_img` even though `out_wht` varies
    strongly pixel-to-pixel (from the square-kernel/pixfrac footprint overlap
    pattern). Dividing `out_img` by `out_wht` again would double-normalize and
    make a constant field look nonuniform, so we return `out_img` untouched.
    """
    from drizzle.resample import Drizzle

    h, w = in_shape
    out_shape = (h * DRIZZLE_SCALE, w * DRIZZLE_SCALE)
    drizzlers = [Drizzle(kernel=KERNEL, out_shape=out_shape) for _ in range(n_channels)]
    for data, matrix, weight in items:
        pixmap = build_pixmap(matrix, in_shape, DRIZZLE_SCALE)
        data = np.asarray(data, np.float32)
        for c in range(n_channels):
            chan = data[..., c] if data.ndim == 3 else data
            drizzlers[c].add_image(
                chan,
                exptime=1.0,
                pixmap=pixmap,
                weight_map=weight,
                pixfrac=pixfrac,
                in_units="counts",
            )
    chans = [d.out_img for d in drizzlers]   # already weight-normalized mean
    return np.stack(chans, axis=-1).astype(np.float32)


def _scaled(matrix: np.ndarray) -> np.ndarray:
    """Compose a frame's input->reference transform with the ×DRIZZLE_SCALE
    grid scale, so warping with the result lands directly on the drizzle
    output grid's coordinate system (rather than the 1× reference grid)."""
    scale = np.diag([DRIZZLE_SCALE, DRIZZLE_SCALE, 1]).astype(np.float64)
    return scale @ np.asarray(matrix, dtype=np.float64)


def _warp_to_grid(data: np.ndarray, matrix: np.ndarray, out_shape: tuple[int, int]) -> np.ndarray:
    """Warp `data` (H, W, C) onto a grid of `out_shape` using `matrix` as the
    input->output transform. Mirrors `register.warp_to`, which only supports
    same-size (input-shape-preserving) warps, by adding an explicit
    `output_shape` to `skimage.transform.warp`."""
    from skimage.transform import SimilarityTransform, warp

    tform = SimilarityTransform(matrix=np.asarray(matrix, dtype=np.float64))
    channels = [
        warp(data[:, :, c], tform.inverse, output_shape=out_shape, order=1, preserve_range=True)
        for c in range(data.shape[2])
    ]
    return np.stack(channels, axis=2).astype(np.float64)


def drizzle_clipped(make_items, in_shape, n_channels, *, kappa=2.5, pixfrac=PIXFRAC):
    """Two-pass drizzle that rejects per-pixel outliers (cosmic rays, satellite
    trails, hot pixels) before accumulating, so that -- unlike a naive
    drizzle-average -- one bad frame cannot lift the output at a pixel that is
    clean in every other frame.

    `make_items` is a callable returning a *fresh* iterable of `(data, matrix)`
    pairs each time it is called (the same contract as
    `integrate.sigma_clip_integrate`'s `make_frames`), since this needs two
    independent passes over the frames.

    Pass 1 (stats): warp each frame onto the 2×-output grid -- composing its
    transform with the ×DRIZZLE_SCALE grid scale via `_scaled` and using
    `_warp_to_grid` (the same warp `register.warp_to` uses, at 2× output
    size) -- and accumulate a streaming per-output-pixel, per-channel
    mean/std with Welford's algorithm, identical math to
    `integrate.sigma_clip_integrate`.

    Pass 2 (drizzle): for each frame, look up the pass-1 mean/std at each
    input pixel's mapped output cell (`build_pixmap`, rounded to the nearest
    output cell and clipped to bounds) and reject the input pixel -- weight
    0 instead of 1 -- if *any* channel's value is more than `kappa*std` from
    that cell's mean. The drizzle weight_map is one 2D mask per input pixel
    shared across all channels of that frame, so channels are OR-combined
    into a single mask rather than kept independent; this is the simpler of
    the two documented options (per-channel vs. luminance) and is exactly as
    correct for this app's mono/RGB frames. Frames are then drizzled with the
    same per-channel `Drizzle` accumulation as `drizzle_integrate`, except
    `fillval=0.0` is passed to the constructor: masking can drop an input
    pixel's weight to zero entirely (and output edges only have partial
    coverage), and `out_img` fills zero-total-weight pixels with NaN unless
    told otherwise.
    """
    from drizzle.resample import Drizzle

    h, w = in_shape
    out_shape = (h * DRIZZLE_SCALE, w * DRIZZLE_SCALE)

    def _as_hwc(data: np.ndarray) -> np.ndarray:
        data = np.asarray(data)
        return data[..., None] if data.ndim == 2 else data

    # --- Pass 1: streaming per-output-pixel, per-channel mean/std (Welford) ---
    # Accumulators are float32 (not float64): at full Seestar resolution the
    # 2x-scaled grid makes each float64 accumulator ~800 MB, and float32 is
    # more than precise enough for sigma-clip statistics.
    mean = m2 = None
    count = 0
    for data, matrix in make_items():
        warped = _warp_to_grid(_as_hwc(data).astype(np.float64), _scaled(matrix), out_shape)
        count += 1
        if mean is None:
            mean = np.zeros_like(warped, dtype=np.float32)
            m2 = np.zeros_like(warped, dtype=np.float32)
        delta = warped - mean
        mean += delta / count
        m2 += delta * (warped - mean)
    if mean is None:
        raise ValueError("no frames to integrate")
    # m2 is mathematically >= 0, but float32's coarser cancellation error can
    # push a near-constant pixel's m2 fractionally below zero; clamp before
    # sqrt so that doesn't produce NaNs (it didn't at float64's precision).
    std = np.sqrt(np.maximum(m2, 0.0) / count)
    # Small-N note: single-pass frame-wise sigma-clip can only flag a lone
    # outlier once the deviation/std ratio (bounded by sqrt(N-1)) exceeds kappa
    # -- e.g. at kappa=2.5, N must be >=~8. This is inherent and identical to
    # integrate.sigma_clip_integrate; real stacks have hundreds of frames, so it
    # is a non-issue in practice.

    # --- Pass 2: mask per-input-pixel outliers, then drizzle ---
    drizzlers = [Drizzle(kernel=KERNEL, out_shape=out_shape, fillval=0.0) for _ in range(n_channels)]
    for data, matrix in make_items():
        data = _as_hwc(data).astype(np.float32)
        pixmap = build_pixmap(matrix, in_shape, DRIZZLE_SCALE)
        xo = np.clip(np.round(pixmap[..., 0]).astype(np.int64), 0, out_shape[1] - 1)
        yo = np.clip(np.round(pixmap[..., 1]).astype(np.int64), 0, out_shape[0] - 1)

        reject = np.zeros(in_shape, dtype=bool)
        for c in range(n_channels):
            mean_at = mean[..., c][yo, xo]
            std_at = std[..., c][yo, xo]
            reject |= (std_at > 0) & (np.abs(data[..., c].astype(np.float64) - mean_at) > kappa * std_at)
        weight = np.where(reject, 0.0, 1.0).astype(np.float32)

        for c in range(n_channels):
            drizzlers[c].add_image(
                data[..., c],
                exptime=1.0,
                pixmap=pixmap,
                weight_map=weight,
                pixfrac=pixfrac,
                in_units="counts",
            )

    chans = [d.out_img for d in drizzlers]
    out = np.stack(chans, axis=-1).astype(np.float32)

    # Coverage on the 2x grid, so the caller can auto-crop the rotation envelope
    # exactly as it does for every other method. out_wht is an accumulated
    # WEIGHT, not a frame count, and its scale depends on pixfrac — so it is
    # rescaled to "effective frames" against its own well-covered interior.
    # full_coverage_bounds only ever compares it to a fraction of the frame
    # count, so a consistent scale is all it needs.
    # Coverage for the caller's auto-crop, on the same 2x grid as the image.
    #
    # out_wht is an accumulated WEIGHT, not a frame count, and it is noisy: on
    # real 12-frame data it ran p5 9.53, median 11.03, p99 12.00. Two things
    # follow, both learned the hard way.
    #
    # SMOOTH IT. The scatter is per-pixel — the square kernel's footprint
    # overlap, which this module's docstring already warned "varies strongly
    # pixel-to-pixel" — while the coverage envelope is smooth over hundreds of
    # pixels.
    #
    # NORMALISE TO THE MEDIAN, not the maximum. Mapping p99 to the frame count
    # puts the TYPICAL pixel below full_coverage_bounds' 0.9 threshold: measured,
    # only 52% of pixels cleared it, scattered like noise, so the largest
    # hole-free rectangle came out 192x32 from a 7680x4320 image. Mapping the
    # median there puts the whole interior comfortably above the line and lets
    # the falloff at the rotation envelope do the actual cropping.
    from scipy.ndimage import uniform_filter

    wht = uniform_filter(np.asarray(drizzlers[0].out_wht, dtype=np.float32),
                         size=32, mode="nearest")
    mid = float(np.median(wht[wht > 0])) if np.any(wht > 0) else 0.0
    coverage = (wht / mid * count) if mid > 0 else wht
    return out, coverage.astype(np.float32)
