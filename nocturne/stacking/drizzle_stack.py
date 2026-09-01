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


# Measured through run_stack on real IC 1396A frames, 2026-09-01:
#
#     40 frames   132 s   3.29 s/frame
#     80 frames   261 s   3.26 s/frame
#    160 frames   534 s   3.34 s/frame
#
# FLAT. The cost does not grow with frame count, which is what the design says
# should happen: the accumulators are fixed by the output grid and every frame is
# warped and drizzled exactly once per pass.
#
# It is set slightly above that measurement rather than at it, because one real
# 2,037-frame run took 16.4 s/frame — five times this — and the cause was never
# established. Reading is not it: the disk does 1045 MB/s and full per-frame
# preparation is 240 ms, so 0.48 s even done twice. Nor is it scaling, per the
# table. Something environmental (indexing, backup, memory pressure at the
# 15.5 GB that run reached) is the likeliest explanation and cannot be proven
# after the fact.
#
# So this is deliberately pessimistic by about 50%, and the phases now log their
# own timing — the next long run will say where its time went instead of leaving
# it to be inferred from screenshots.
#
# A previous version of this constant was 16.4, set from that single anomalous
# run. Recalibrating a constant from one measurement is the mistake this file
# has now made in both directions.
_SECONDS_PER_FRAME = 5.0
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


def _warp_to_grid(data: np.ndarray, matrix: np.ndarray, out_shape: tuple[int, int]):
    """Warp `data` (H, W, C) onto `out_shape`, AND say which pixels it reached.

    The validity mask is the whole point, and it was missing. `warp` fills
    everything outside the source with zero, and zero is a legitimate pixel
    value — register.warp_with_validity exists in the normal path for exactly
    this reason and says so. Without it, pass 1's mean and variance counted a
    zero for every frame that did not cover a pixel: at the rotation envelope a
    pixel seen by 200 of 314 frames had its mean divided by 314 and its variance
    inflated, so pass 2 judged real data against corrupted statistics and
    rejected the wrong pixels. Each channel sits at a different level, so the
    corruption differed per channel and drew COLOURED streaks along the coverage
    boundaries — which is what Andreas saw on his first real drizzle stack, and
    what the normal stack of the same subs does not do.

    Threshold 0.999 rather than > 0, matching warp_with_validity: interpolation
    makes a boundary pixel a blend of real data and the zero fill, so a
    fractionally covered pixel counts as not covered.
    """
    from skimage.transform import SimilarityTransform, warp

    tform = SimilarityTransform(matrix=np.asarray(matrix, dtype=np.float64))
    channels = [
        warp(data[:, :, c], tform.inverse, output_shape=out_shape, order=1, preserve_range=True)
        for c in range(data.shape[2])
    ]
    ones = np.ones(data.shape[:2], dtype=np.float64)
    valid = warp(ones, tform.inverse, output_shape=out_shape, order=1,
                 preserve_range=True) >= 0.999
    # float32, not float64. At 7680x4320x3 the difference is 398 MB per array
    # against 796, and EVERY temporary in the accumulation below inherits it.
    # float32 is already what the accumulators use, and this module has always
    # said so: "float32 is more than precise enough for sigma-clip statistics".
    return np.stack(channels, axis=2).astype(np.float32), valid


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
    # The WARP is the expensive part of this pass — measured on a 2,037-frame
    # run, pass 1 took about 410 minutes against pass 2's 143 — and skimage's
    # warp releases the GIL, so it threads: measured 3.76x on four threads,
    # with byte-identical output. The accumulation below stays serial because it
    # shares state, so this is a producer/consumer: warp ahead, accumulate in
    # order.
    #
    # A DELIBERATELY SMALL window. Each warped frame is 398 MB at 7680x4320x3,
    # so ordered_results' default lookahead of workers+2 would hold gigabytes;
    # this project already has a 396 GB stacking runaway in its history and a
    # 15.5 GB drizzle run last night.
    import logging
    import time as _time
    from .parallel import ordered_results, plan_workers

    _log = logging.getLogger("nocturne.drizzle")
    _t0 = _time.time()

    def warp_one(item):
        data, matrix = item
        return _warp_to_grid(_as_hwc(data).astype(np.float32),
                             _scaled(matrix), out_shape)

    threads = max(1, min(4, plan_workers().count))
    mean = m2 = seen = None
    count = 0
    for warped, valid in ordered_results(make_items(), warp_one,
                                         workers=threads, window=threads):
        count += 1
        if mean is None:
            mean = np.zeros_like(warped, dtype=np.float32)
            m2 = np.zeros_like(warped, dtype=np.float32)
            seen = np.zeros(out_shape, dtype=np.int32)
            d1 = np.empty_like(mean)
            d2 = np.empty_like(mean)
            counted = np.empty(out_shape, dtype=np.float32)
        # Welford, but only over the frames that actually reached each pixel.
        # Counting every frame everywhere is what corrupted the statistics at
        # the coverage boundary — see _warp_to_grid.
        seen += valid
        v = valid[..., None]
        np.maximum(seen, 1, out=counted)
        # Welford over the covering frames only, in PREALLOCATED buffers.
        #
        # The first version of this wrote the arithmetic out plainly:
        #     delta = np.where(v, warped - mean, 0.0)
        #     mean += (delta / n).astype(np.float32)
        #     m2 += (delta * np.where(v, warped - mean, 0.0)).astype(np.float32)
        # which allocates five full-size float64 temporaries per frame. On a
        # real 2,037-frame IC 1396A run that took resident memory to 15.5 GB
        # against a predicted 2-3, and allocation churn at that scale costs real
        # time on top. Same maths, two reused buffers.
        np.subtract(warped, mean, out=d1)          # delta
        d1 *= v                                    # only where the frame reached
        np.divide(d1, counted[..., None], out=d2)
        mean += d2
        np.subtract(warped, mean, out=d2)          # delta2, after the update
        d2 *= v
        d1 *= d2
        m2 += d1
    if mean is None:
        raise ValueError("no frames to integrate")
    # m2 is mathematically >= 0, but float32's coarser cancellation error can
    # push a near-constant pixel's m2 fractionally below zero; clamp before
    # sqrt so that doesn't produce NaNs (it didn't at float64's precision).
    # Divided by what actually contributed, not by the frame count.
    std = np.sqrt(np.maximum(m2, 0.0) / np.maximum(seen, 1)[..., None])
    # Small-N note: single-pass frame-wise sigma-clip can only flag a lone
    # outlier once the deviation/std ratio (bounded by sqrt(N-1)) exceeds kappa
    # -- e.g. at kappa=2.5, N must be >=~8. This is inherent and identical to
    # integrate.sigma_clip_integrate; real stacks have hundreds of frames, so it
    # is a non-issue in practice.

    _t1 = _time.time()
    _log.info("drizzle pass 1 (measure): %d frames in %.0f s (%.2f s/frame)",
              count, _t1 - _t0, (_t1 - _t0) / max(count, 1))

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

    _t2 = _time.time()
    _log.info("drizzle pass 2 (drizzle): %d frames in %.0f s (%.2f s/frame)",
              count, _t2 - _t1, (_t2 - _t1) / max(count, 1))
    _log.info("drizzle total: %.0f s (%.2f s/frame) for %d frames",
              _t2 - _t0, (_t2 - _t0) / max(count, 1), count)

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
