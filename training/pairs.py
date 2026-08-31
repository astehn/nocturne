"""Noise2Noise training pairs: two stacks of the same sky that share no frame.

The idea in one line: given two independent noisy pictures of the same thing, a
model trained to predict one from the other learns the thing, because the noise
averages away and the scene does not.

That matters here because this archive contains no clean data at any depth. A
2034-frame stack of IC 1396A is still visibly noisy; an uncooled IMX585 does not
give you truth, only progressively less noise (sigma falls as N^-0.46, with no
floor and no arrival). Every earlier attempt trained against a deep stack as if
it were truth, which teaches the model that the target's own noise is correct.

So nothing here is treated as clean. Take 2N frames, split them into two halves
sharing no frame, stack each. Same sky, same depth, same noise level,
independent noise.

TWO THINGS THE HALVES MUST SHARE, and the reason this file is not three lines:

  * THE SAME PIXEL GRID. v1 integrated each half to its own extent, so where one
    half covered a pixel and the other did not, the difference between them was
    scene rather than noise. Measured on its tiles, the injected noise field
    correlated with its own target up to 0.46 against a null of 0.03. Here both
    halves are cropped to the region every frame of BOTH covers.

  * THE SAME SCALE. Dividing each half by its own peak would leave a brightness
    difference between them, and the model would happily learn to correct that
    instead of denoising.

Registration comes from `nocturne.stacking` — the code that runs when Andreas
presses Stack. v1 carried a second implementation of registration and stacking;
the two drifted and produced a misregistration that took a day to find. One
implementation cannot disagree with itself.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nocturne.stacking.coverage import _largest_true_rectangle
from nocturne.stacking.frames import load_sub
from nocturne.stacking.grade import grade_frames, judge, order_best_first
from nocturne.stacking.integrate import average_integrate
from nocturne.stacking.normalize import frame_stats, normalize_to
from nocturne.stacking.register import warp_with_validity
from nocturne.stacking.register_pool import register_frames


def time_order(paths) -> list:
    """Frames oldest-first, by DATE-OBS, falling back to filename.

    The header rather than the name because the name is a convention and the
    header is a record; Seestar filenames do encode the timestamp, but a
    renamed or re-exported frame would silently sort wrong and the failure would
    look like noise.
    """
    from astropy.io import fits

    def key(p):
        try:
            d = fits.getheader(p).get("DATE-OBS")
            if d:
                return (0, str(d))
        except Exception:                    # noqa: BLE001 - unreadable header
            pass
        return (1, os.path.basename(p))

    return sorted(paths, key=key)


@dataclass
class Prepared:
    """Frames registered once, ready to be stacked in any subset.

    Registration is most of the cost, and it does not depend on which frames end
    up in which half — so it happens once and every pair reuses it. v1
    re-registered per rung, paying a full pass over the frames for each.
    """
    paths: list[str]
    ordered: list = field(default_factory=list)   # the same frames, oldest first
    transforms: dict = field(default_factory=dict)
    stats: dict = field(default_factory=dict)
    ref_stats: tuple = ()
    ref_path: str = ""


def prepare(paths, *, workers: int = 3, strictness: str = "normal",
            on_line=print) -> Prepared:
    """Grade, reject and register a target's frames, once.

    Grading and reference choice come from `nocturne.stacking.grade`, the same
    code the Stack tool runs, for two reasons beyond not writing it twice.

    It excludes already-stacked masters. A target folder holds them: "M 16_sub"
    contains HaOIII_master.fits and two full stacks alongside 366 subs, and
    HaOIII_master.fits sorts FIRST alphabetically. Taking paths[0] as the
    reference registered 3840x2160 subs against a 2896x1160 master and dropped
    every single frame with "dimension mismatch". Measured, not imagined — it is
    what happened the first time this ran on real data.

    And it picks the reference on geometry rather than order. Both stackers
    align to paths[0], so whatever leads the list IS the reference; Stack and
    Ha/OIII once disagreed about it and produced differently-framed masters from
    identical subs.

    Frames that fail to register are dropped: one with no transform cannot be
    placed on the grid, and including it would put an unaligned field into a half.
    """
    paths = list(paths)
    if len(paths) < 2:
        raise ValueError(f"need at least 2 frames, got {len(paths)}")
    stats = grade_frames(paths, strictness=strictness)
    judge(stats, strictness)
    keep = [s for s in stats if s.included and not s.error]
    if len(keep) < 2:
        raise ValueError(
            f"only {len(keep)} of {len(paths)} frames are usable — "
            f"masters and rejects excluded")
    if len(keep) < len(paths):
        on_line(f"  {len(paths) - len(keep)} of {len(paths)} excluded "
                f"(already-stacked masters, or rejected by grading)")
    paths = order_best_first(keep)
    ref_path = paths[0]                      # best geometry leads: it IS the grid
    ref = load_sub(ref_path, normalize=False)
    ref_stats = frame_stats(ref.data)

    results = register_frames(paths[1:], ref_path, workers)
    transforms = {ref_path: np.eye(3, dtype=np.float64)}
    stats = {ref_path: ref_stats}
    kept = [ref_path]
    for r in results:
        if r.reason is not None or r.matrix is None:
            on_line(f"  dropped {os.path.basename(r.path)}: {r.reason or 'no transform'}")
            continue
        transforms[r.path] = r.matrix
        stats[r.path] = r.stats
        kept.append(r.path)
    on_line(f"  registered {len(kept)}/{len(paths)}")
    return Prepared(kept, time_order(kept), transforms, stats, ref_stats, ref_path)


def split_disjoint(ordered, depth: int, rng):
    """Two lists of `depth` items each, sharing nothing.

    `ordered` must be oldest-first. A contiguous run of 2*depth frames is taken
    from a random position and DEALT ALTERNATELY — A, B, A, B — rather than the
    obvious random permutation.

    That is not fussiness. Measured on IC 1396A, which spans 2026-08-11..08-26:

                     random split                interleaved
        depth 16   +0.210 +-0.319  max 0.637   +0.017 +-0.060  max 0.132
        depth 32   -0.232 +-0.163  max 0.430   -0.007 +-0.036  max 0.070
        depth 64   -0.002 +-0.303  max 0.534   -0.015 +-0.065  max 0.094

    where the number is corr(A-B, (A+B)/2) against a null of +-0.0006. A random
    draw across fifteen nights hands each half a different mix of sky
    conditions, and a difference in average sky is a smooth gradient that tracks
    the scene — so A-B carries structure rather than only noise, which is
    exactly what a model will learn instead of denoising. The random split's
    worst case, 0.637, is WORSE than the 0.46 that retired v1.

    Dealing alternately from a contiguous run gives both halves the same
    conditions, the same transparency, the same moon, the same dew.

    Refuses rather than shortening: depth is what the model is conditioned on
    and what the manifest records, so a quietly shallower pair is a mislabel.
    """
    ordered = list(ordered)
    if len(ordered) < 2 * depth:
        raise ValueError(
            f"a pair at depth {depth} needs {2 * depth} frames, only {len(ordered)} available")
    start = int(rng.integers(0, len(ordered) - 2 * depth + 1))
    block = ordered[start:start + 2 * depth]
    return block[0::2], block[1::2]


def _stack(prep: Prepared, paths):
    """Integrate a subset onto the common grid, exactly as the Stack tool does.

    Normalise BEFORE warping, so the out-of-frame fill stays a clean zero that
    the validity mask keeps out of the average — correcting afterwards would turn
    that fill into a plausible-looking sky value.
    """
    def frames():
        for p in paths:
            data = normalize_to(load_sub(p, normalize=False).data,
                                prep.stats[p], prep.ref_stats)
            yield warp_with_validity(data, prep.transforms[p])

    return average_integrate(frames())


def common_bounds(cov_a, cov_b, depth: int):
    """The rectangle where EVERY frame of BOTH halves contributed.

    The intersection, not either half's own extent and not their union. v1 took
    each half's own, so at the rotation envelope one half covered a pixel the
    other did not and the difference between them was scene rather than noise —
    the mechanism behind a noise field correlating 0.46 with its own target.

    Not `stacking.full_coverage_bounds`, though that is the same idea, for two
    reasons found on real M 16 frames after the synthetic tests were happy:

      * its `coverage` is an integer frame COUNT, so the threshold has to be the
        depth. Called with n_frames=1 it means "at least one frame touched this
        pixel", and a depth-16 pair came back containing pixels covered by ONE
        frame — nominally 4x noisier than the depth claims.
      * it searches a subsampled mask for speed and says so: "the kept rectangle
        can dip a little under frac". A few stray edge pixels are invisible in a
        picture and are a mislabel in training data.

    So the mask is exact and the search runs at full resolution. It costs about
    a second on a 3840x2160 frame, once per pair, which is nothing next to
    stacking the frames in the first place.
    """
    both = np.minimum(np.asarray(cov_a), np.asarray(cov_b))
    mask = both >= depth
    if not mask.any():
        raise ValueError(
            f"no pixel is covered by all {depth} frames of both halves — "
            f"the frames may be too widely dithered to pair at this depth")
    return _largest_true_rectangle(mask)


def shared_scale(a, b) -> float:
    """ONE number for both halves, from their mean.

    Their mean is what the full stack would have been, so the pair sits where
    the app's own master sits. Scaling each half by its own peak would leave a
    brightness difference between them that the model would learn to correct —
    a mapping that has nothing to do with noise.
    """
    return float(((np.asarray(a) + np.asarray(b)) / 2.0).max())


def make_pair(prep: Prepared, depth: int, rng, *, return_coverage: bool = False):
    """One Noise2Noise pair: (A, B), same grid, same scale, no shared frame."""
    pa, pb = split_disjoint(prep.ordered or prep.paths, depth, rng)
    a, cov_a = _stack(prep, pa)
    b, cov_b = _stack(prep, pb)

    top, bottom, left, right = common_bounds(cov_a, cov_b, depth)
    a, b = a[top:bottom, left:right], b[top:bottom, left:right]
    cov_a, cov_b = cov_a[top:bottom, left:right], cov_b[top:bottom, left:right]

    # ONE scale for both, taken from their mean — which is what the full stack
    # would have been, so the pair sits where the app's master sits.
    peak = shared_scale(a, b)
    if peak > 0:
        a, b = a / peak, b / peak
    # Floor at zero but do NOT clip the top. The app clips because it is making
    # something to look at; clipping a training pair would teach the model that
    # a flat-topped star is what a bright star looks like.
    a = np.clip(a, 0.0, None).astype(np.float32)
    b = np.clip(b, 0.0, None).astype(np.float32)
    if return_coverage:
        return a, b, cov_a, cov_b
    return a, b
