"""Is manufactured noise a stand-in for real noise, or a decoration?

The injection design (2026-08-24) builds training inputs by adding a scaled
noise field to a clean master. That is only honest if the manufactured result is
statistically the same animal as a real stack at the same level. Five numbers
are checked, each chosen because it is something a naive Gaussian generator
would get wrong:

  autocorrelation at 1-2 px  registration warps every frame with interpolation
                             and demosaicing mixes neighbours, so real stacked
                             noise is spatially correlated. White noise is not.
                             This is the statistic the gate lives or dies on.
  per-channel ratios         Bayer gives green twice the samples, hence less
                             noise. Equal channels look wrong as colour
                             blotching, the artefact this project keeps
                             fighting.
  kurtosis                   real noise is not perfectly Gaussian; sigma-clipped
                             stacking truncates the tails.
  variance vs intensity      shot noise grows with signal. Flat noise over a
                             nebula is the tell of a synthetic field.

STOP CONDITIONS, fixed before measuring (see the spec): autocorrelation at lag
1-2 differing by more than 20% relative, or channel ratios by more than 10%,
means manufactured noise is not a stand-in and the design is wrong. They are
constants here so that widening one is a diff, not a decision made in a
sentence.

WHAT IS COMPARED, and why it is not the two images themselves. The real stack
and the manufactured input show the SAME sky, so any statistic taken on them
directly is measured through a scene both of them carry -- and a shared scene
drags both answers towards each other, which would make the gate agree with
itself for the wrong reason. That is the 2026-08-23 failure exactly: a probe
that measured starlight and called it sensor noise. So the runner differences
each image against the clean master first, leaving two fields with NO scene in
them at all, and compares those.
"""
from __future__ import annotations

import os
import sys

import numpy as np

# Same two lines as build_dataset.py: run as a script, `sys.path[0]` is
# `training/`, so `nocturne` is not importable until the repo root is added.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

AUTOCORR_STOP = 0.20
CHANNEL_STOP = 0.10

_VARIANCE_BINS = 12      # enough to fit a slope, wide enough that MAD is stable


def _sigma(values: np.ndarray) -> float:
    """MAD sigma. A real noise field carries hot pixels and star residuals; a
    plain std lets a handful of them set the answer."""
    if values.size == 0:
        return 0.0
    return float(1.4826 * np.median(np.abs(values - np.median(values))))


def _autocorr(field: np.ndarray, mask: np.ndarray, lag: int, axis: int) -> float:
    """Correlation of the field with itself shifted `lag` px along `axis`.

    The two selections use the SAME boolean mask -- the intersection of the
    mask with its own shift -- so pixel i on the left is always paired with its
    own neighbour on the right. Selecting `mask[:, :-lag]` from one side and
    `mask[:, lag:]` from the other pairs unrelated pixels wherever the mask is
    ragged, and on a real coverage mask the two selections are not even the
    same length, so the bug surfaces as numpy raising rather than as a wrong
    number.
    """
    if axis == 1:
        left, right = field[:, :-lag], field[:, lag:]
        both = mask[:, :-lag] & mask[:, lag:]
    else:
        left, right = field[:-lag, :], field[lag:, :]
        both = mask[:-lag, :] & mask[lag:, :]
    a = left[both].astype(np.float64)
    b = right[both].astype(np.float64)
    if a.size < 100:
        return 0.0
    a = a - a.mean()
    b = b - b.mean()
    d = float(np.sqrt((a * a).sum() * (b * b).sum()))
    return float((a * b).sum() / d) if d > 0 else 0.0


def _autocorr_axis(field: np.ndarray, mask: np.ndarray, lag: int, axis: int) -> float:
    return float(np.mean([_autocorr(field[:, :, c], mask, lag, axis)
                          for c in range(field.shape[2])]))


def _rel(real: float, made: float) -> float:
    return 0.0 if real == 0 else (made - real) / abs(real)


def _channel_ratio(field: np.ndarray, mask: np.ndarray) -> float:
    """Green's noise against red and blue's. Bayer's signature."""
    s = [_sigma(field[:, :, c][mask]) for c in range(field.shape[2])]
    return s[1] / max((s[0] + s[2]) / 2.0, 1e-12)


def _kurtosis(field: np.ndarray, mask: np.ndarray) -> float:
    """Pooled across channels; 3.0 is Gaussian."""
    v = np.concatenate([field[:, :, c][mask].astype(np.float64)
                        for c in range(field.shape[2])])
    if v.size == 0:
        return 0.0
    v = v - v.mean()
    s = v.std()
    return float((v ** 4).mean() / s ** 4) if s > 0 else 0.0


def _skew(field: np.ndarray, mask: np.ndarray) -> float:
    v = np.concatenate([field[:, :, c][mask].astype(np.float64)
                        for c in range(field.shape[2])])
    if v.size == 0:
        return 0.0
    v = v - v.mean()
    s = v.std()
    return float((v ** 3).mean() / s ** 3) if s > 0 else 0.0


def _variance_slope(field: np.ndarray, mask: np.ndarray,
                    intensity: np.ndarray) -> float:
    """How much variance grows across the intensity range actually present.

    From a fit of ``var = a + b*I``, reported as ``b * (Imax - Imin) / mean(var)``
    -- the fractional change in noise variance from the darkest bin to the
    brightest. Two normalisations, both load-bearing: dividing by ``mean(var)``
    makes it independent of the noise LEVEL (the real and manufactured fields
    differ in level by construction, and an absolute slope would report that as
    a difference in signal dependence), and multiplying by the intensity SPAN
    makes it independent of the arbitrary ADU scale of the stack, so 0.5 means
    "half again as much variance in the bright bins" whatever the units are.
    """
    ivals = intensity[mask].astype(np.float64)
    if ivals.size < _VARIANCE_BINS * 50:
        return 0.0
    edges = np.quantile(ivals, np.linspace(0.0, 1.0, _VARIANCE_BINS + 1))
    edges = np.unique(edges)
    if edges.size < 4:
        return 0.0
    centres, variances = [], []
    for lo, hi in zip(edges[:-1], edges[1:]):
        sel = (ivals >= lo) & (ivals < hi if hi != edges[-1] else ivals <= hi)
        if sel.sum() < 50:
            continue
        v = np.concatenate([field[:, :, c][mask].astype(np.float64)[sel]
                            for c in range(field.shape[2])])
        centres.append(float(ivals[sel].mean()))
        variances.append(_sigma(v) ** 2)
    if len(centres) < 3:
        return 0.0
    c = np.asarray(centres)
    v = np.asarray(variances)
    if v.mean() <= 0:
        return 0.0
    b = float(np.polyfit(c, v, 1)[0])
    return b * float(c.max() - c.min()) / v.mean()


def compare_noise(real: np.ndarray, manufactured: np.ndarray, mask: np.ndarray,
                  *, intensity: np.ndarray | None = None,
                  per_axis: bool = False) -> dict:
    """Each statistic for both fields, plus the relative difference.

    Every value is a ``(real, manufactured, rel_diff)`` triple, where
    ``rel_diff = (manufactured - real) / |real|``. All of them are scale-free,
    which matters because the two fields are not required to be at identical
    levels -- only to have the same *shape* of noise.

    ``intensity`` is the clean master, needed for the signal-dependence check;
    without it ``variance_slope`` is reported as zero on both sides rather than
    guessed at. ``per_axis`` adds the horizontal and vertical autocorrelations
    separately: the headline number averages them, and an averaged number can
    hide a field that is correlated along one axis only.
    """
    real = np.asarray(real, np.float32)
    manufactured = np.asarray(manufactured, np.float32)
    mask = np.asarray(mask, bool)
    out: dict[str, tuple[float, float, float]] = {}

    for lag in (1, 2):
        per = {}
        for name, axis in (("x", 1), ("y", 0)):
            r = _autocorr_axis(real, mask, lag, axis)
            m = _autocorr_axis(manufactured, mask, lag, axis)
            per[name] = (r, m)
            if per_axis:
                out[f"autocorr_{lag}_{name}"] = (r, m, _rel(r, m))
        r = float(np.mean([per["x"][0], per["y"][0]]))
        m = float(np.mean([per["x"][1], per["y"][1]]))
        out[f"autocorr_{lag}"] = (r, m, _rel(r, m))

    r, m = _channel_ratio(real, mask), _channel_ratio(manufactured, mask)
    out["channel_ratios"] = (r, m, _rel(r, m))

    r, m = _kurtosis(real, mask), _kurtosis(manufactured, mask)
    out["kurtosis"] = (r, m, _rel(r, m))

    if intensity is None:
        out["variance_slope"] = (0.0, 0.0, 0.0)
    else:
        intensity = np.asarray(intensity, np.float32)
        r = _variance_slope(real, mask, intensity)
        m = _variance_slope(manufactured, mask, intensity)
        out["variance_slope"] = (r, m, _rel(r, m))
    return out


def verdict(result: dict) -> tuple[bool, list[str]]:
    """Pass/fail against the stop conditions fixed in the spec before measuring."""
    failures = []
    for lag in (1, 2):
        rel = result[f"autocorr_{lag}"][2]
        if abs(rel) > AUTOCORR_STOP:
            failures.append(
                f"autocorr_{lag} differs by {rel*100:+.1f}% "
                f"(stop at +-{AUTOCORR_STOP*100:.0f}%)")
    rel = result["channel_ratios"][2]
    if abs(rel) > CHANNEL_STOP:
        failures.append(
            f"channel_ratios differ by {rel*100:+.1f}% "
            f"(stop at +-{CHANNEL_STOP*100:.0f}%)")
    return (not failures), failures


# --------------------------------------------------------------------------
# The real-data runner. This is the decision gate: it builds a genuinely real
# n-frame stack and a manufactured one at the same measured sigma, out of three
# DISJOINT subsets of one group, and reports whether they are the same animal.
# --------------------------------------------------------------------------

_SOURCE = "/Volumes/Work2/Images/Astro/Training"
# 366 frames: three disjoint subsets of 122 with a frame to spare for the
# registration reference, and NOT one of M8/M45/NGC6888/NGC281, which are held
# out so they can judge the finished model.
_GROUP = "s30_M16_2026-08-09_LP_10s"
_HP_SIGMA = 2.0          # training/noise.py's high-pass scale
_DARK_FRACTION = 0.60    # training/noise.py's convention: the darker 60%


def _dark_mask(master: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """`training/noise.py`'s mask: the darker 60% of the SMOOTHED luminance.

    Smoothed, not raw -- selecting the darker N% of a raw luminance selects the
    low tail of the very noise being measured, which reads sigma at about a
    third of its true value on a flat field. The percentile is taken over the
    valid region only, or the uncovered border decides where "dark" is.
    """
    bg = _smoothed_luminance(master)
    cut = np.percentile(bg[valid], _DARK_FRACTION * 100.0)
    return valid & (bg <= cut)


def _smoothed_luminance(img: np.ndarray) -> np.ndarray:
    from scipy.ndimage import gaussian_filter

    return gaussian_filter(img.mean(axis=2), _HP_SIGMA).astype(np.float32)


def _highpass(img: np.ndarray) -> np.ndarray:
    from scipy.ndimage import gaussian_filter

    return np.stack(
        [img[:, :, c] - gaussian_filter(img[:, :, c], _HP_SIGMA)
         for c in range(img.shape[2])], -1).astype(np.float32)


def _split_three(paths, seed: int):
    """Three disjoint, equal subsets. Disjoint is the whole basis of the test:
    an overlapping 'real' stack would share frames -- and therefore noise --
    with the master it is being compared against."""
    rng = np.random.default_rng(seed)
    order = rng.permutation(len(paths))
    n = len(paths) // 3
    a = [paths[int(i)] for i in order[:n]]
    b = [paths[int(i)] for i in order[n:2 * n]]
    c = [paths[int(i)] for i in order[2 * n:3 * n]]
    if set(a) & set(b) or set(a) & set(c) or set(b) & set(c):
        raise AssertionError("subsets overlap; the comparison would be circular")
    return a, b, c


def _table(title: str, result: dict, note: str = "") -> None:
    print(f"\n{title}")
    if note:
        print(f"  {note}")
    print(f"  {'statistic':<18}{'real':>14}{'manufactured':>16}{'rel diff':>12}")
    for key in ("autocorr_1", "autocorr_1_x", "autocorr_1_y",
                "autocorr_2", "autocorr_2_x", "autocorr_2_y",
                "channel_ratios", "kurtosis", "variance_slope"):
        if key not in result:
            continue
        r, m, rel = result[key]
        flag = ""
        if key in ("autocorr_1", "autocorr_2") and abs(rel) > AUTOCORR_STOP:
            flag = "  <-- STOP"
        if key == "channel_ratios" and abs(rel) > CHANNEL_STOP:
            flag = "  <-- STOP"
        indent = "    " if key.endswith(("_x", "_y")) else "  "
        name = key if not key.endswith(("_x", "_y")) else key.split("_", 2)[2]
        print(f"{indent}{name:<{20 - len(indent)}}{r:>14.4f}{m:>16.4f}"
              f"{rel * 100:>11.1f}%{flag}")


def main(argv=None) -> int:
    import argparse
    import time

    from nocturne.core.denoise_model import estimate_sigma
    from nocturne.stacking.coverage import full_coverage_bounds
    from nocturne.training.inject import (
        inject, noise_field, scale_for_sigma, target_from_halves,
    )
    from nocturne.training.pairs import discover_frame_groups, prepare_stack

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", default=_SOURCE)
    p.add_argument("--group", default=_GROUP)
    p.add_argument("--seed", type=int, default=20260824)
    p.add_argument("--workers", type=int, default=None)
    p.add_argument("--kappa", type=float, default=2.5)
    p.add_argument("--cache", default=None,
                   help="directory to keep the three integrations in, so the "
                        "comparison can be re-run without re-stacking")
    args = p.parse_args(argv)

    cache = args.cache
    stacks = {}
    if cache and all(os.path.isfile(os.path.join(cache, f"{n}.npy"))
                     for n in ("a", "b", "c", "cov_a", "cov_b", "cov_c")):
        print(f"loading cached integrations from {cache}")
        for n in ("a", "b", "c", "cov_a", "cov_b", "cov_c"):
            stacks[n] = np.load(os.path.join(cache, f"{n}.npy"))
    else:
        t0 = time.time()
        print(f"scanning {args.source} ...")
        groups = discover_frame_groups(
            args.source, sensor="s30", combine_nights=True)
        match = [g for g in groups if g.slug == args.group]
        if not match:
            print(f"group {args.group!r} not found. Candidates with >=300 frames:")
            for g in sorted(groups, key=lambda g: -len(g.frames))[:15]:
                print(f"    {g.slug:<44}{len(g.frames):>5} frames")
            return 2
        group = match[0]
        print(f"{group.slug}: {len(group.frames)} frames "
              f"({time.time() - t0:.0f}s to scan)")

        paths = [f.path for f in group.frames]
        reference = paths[len(paths) // 2]
        t0 = time.time()
        prepared = prepare_stack(paths, reference, workers=args.workers)
        available = [q for q in prepared.available_paths if q != reference]
        print(f"registered {len(available)}/{len(paths) - 1} frames "
              f"({len(prepared.rejected)} rejected) in {time.time() - t0:.0f}s")

        a, b, c = _split_three(available, args.seed)
        print(f"three disjoint subsets of {len(a)} frames each")
        for name, subset in (("a", a), ("b", b), ("c", c)):
            t0 = time.time()
            raw = prepared.integrate(subset, method="sigma_clip",
                                     kappa=args.kappa, workers=args.workers,
                                     autocrop=False, label=name)
            stacks[name] = raw.data
            stacks[f"cov_{name}"] = raw.coverage
            print(f"  integrated {name}: {len(subset)} frames, "
                  f"method={raw.method_used}, {time.time() - t0:.0f}s")
        if cache:
            os.makedirs(cache, exist_ok=True)
            for n, v in stacks.items():
                np.save(os.path.join(cache, f"{n}.npy"), v)

    half_a, half_b, real = (stacks["a"], stacks["b"], stacks["c"])
    counts = [int(stacks[f"cov_{n}"].max()) for n in ("a", "b", "c")]
    # Crop to where all three subsets are essentially fully covered. Frames
    # rotate between each other, so the fringe of the canvas is built from a
    # different (and smaller) set of frames than the middle -- comparing noise
    # there would compare stack depths, not stack noise.
    frac = np.minimum.reduce([stacks[f"cov_{n}"] / max(counts[i], 1)
                              for i, n in enumerate("abc")])
    top, bottom, left, right = full_coverage_bounds(
        (frac * 1000).astype(np.int32), 1000, frac=0.999)
    box = (slice(top, bottom), slice(left, right))
    half_a, half_b, real = half_a[box], half_b[box], real[box]
    valid = np.ones(real.shape[:2], bool)
    print(f"\ncomparison area {real.shape[1]}x{real.shape[0]} px "
          f"(cropped from {stacks['a'].shape[1]}x{stacks['a'].shape[0]})")

    master = target_from_halves(half_a, half_b)
    field = noise_field(half_a, half_b)

    sigma_real = estimate_sigma(real)
    sigma_master = estimate_sigma(master)
    k = scale_for_sigma(field, sigma_real, estimate_sigma, base=master)
    made = inject(master, field, k)
    print(f"sigma: real {counts[2]}-frame stack {sigma_real:.6f} | "
          f"master ({counts[0] + counts[1]} frames) {sigma_master:.6f} | "
          f"manufactured {estimate_sigma(made):.6f} (k={k:.4f})")

    dark = _dark_mask(master, valid)
    print(f"dark mask keeps {dark.sum() / dark.size * 100:.0f}% of the area")

    # Primary comparison. Differencing against the master removes the SCENE
    # exactly -- not approximately, as a high-pass would -- so neither field
    # contains a single photon of M16. That is the whole defence against the
    # 2026-08-23 failure, where a probe measured starlight and called it noise.
    real_noise = (real - master).astype(np.float32)
    made_noise = (made - master).astype(np.float32)
    print(f"noise field MAD sigma: real {_sigma(real_noise[dark]):.6f} | "
          f"manufactured {_sigma(made_noise[dark]):.6f}")
    print(f"skew: real {_skew(real_noise, dark):+.4f} | "
          f"manufactured {_skew(made_noise, dark):+.4f}")

    # Bin by the SMOOTHED luminance, never the raw one. `training/noise.py`
    # makes the same point about its dark mask and for the same reason: the raw
    # luminance is itself part of the noise being measured, so binning on it
    # conditions on that noise -- pixels land in a bright bin partly because
    # their own noise was high, and the within-bin variance is truncated by the
    # act of selecting them. Smoothing leaves the scene, which is what "how does
    # noise grow with signal" is actually asking about.
    scene = _smoothed_luminance(master)
    primary = compare_noise(real_noise, made_noise, dark,
                            intensity=scene, per_axis=True)
    _table("PRIMARY -- scene-free noise fields (real - master vs manufactured - master)",
           primary,
           "both sides are differences of independent stacks, so both are "
           "scene-free. The real\n  side is noise(C) - noise(A+B)/2 and the "
           "manufactured side k*(noise(A) - noise(B))/sqrt2,\n  so their LEVELS "
           "differ by construction -- every statistic here is scale-free for "
           "that\n  reason. Adding independent fields of the same character "
           "leaves autocorrelation and\n  channel ratios exactly unchanged; it "
           "does pull kurtosis towards Gaussian on both\n  sides, slightly "
           "harder on the real one (three fields, not two).")

    wide = compare_noise(real_noise, made_noise, valid, intensity=scene)
    print(f"\n  variance_slope over the WHOLE frame (full intensity range): "
          f"real {wide['variance_slope'][0]:+.3f} | "
          f"manufactured {wide['variance_slope'][1]:+.3f} | "
          f"{wide['variance_slope'][2] * 100:+.1f}%")
    for label, res in (("dark mask", primary), ("whole frame", wide)):
        r, m, rel = res["variance_slope"]
        if max(abs(r), abs(m)) < 0.05:
            print(f"  NOTE: variance_slope over the {label} is near zero on BOTH "
                  f"sides ({r:+.3f} vs {m:+.3f}).\n        A large relative "
                  f"difference between two numbers this small says nothing; on "
                  f"this\n        field the signal-dependence check has no "
                  f"discriminating power either way.")

    # Cross-check only. This one measures the images themselves, so both sides
    # carry the same stars and the same faint nebulosity -- shared structure
    # that pushes the two answers together whether or not the noise matches.
    # It cannot be evidence of a pass; it can only be evidence of a failure.
    secondary = compare_noise(_highpass(real), _highpass(made), dark)
    _table("CROSS-CHECK -- high-passed images (scene NOT removed; agreement here "
           "is weak evidence)", secondary)

    # THE CONTROL, and the reason any of the above is worth reading. The same
    # comparison is run against white Gaussian noise matched to the manufactured
    # field's per-channel sigma. If that does NOT trip the stop conditions, the
    # gate cannot tell real stacked noise from a random number generator and its
    # verdict on the manufactured field means nothing -- which is precisely how
    # the 2026-08-23 independence probe passed while measuring starlight.
    rng = np.random.default_rng(20260824)
    per_channel = np.array([_sigma(made_noise[:, :, c][dark]) for c in range(3)])
    white = (rng.standard_normal(made_noise.shape) * per_channel).astype(np.float32)
    control = compare_noise(real_noise, white, dark, intensity=scene)
    _table("CONTROL -- the same comparison against WHITE GAUSSIAN noise of the "
           "same per-channel sigma", control,
           "this MUST trip the stop conditions. If it does not, the gate is "
           "blind and\n  nothing above is evidence.")
    control_ok, control_failures = verdict(control)

    ok, failures = verdict(primary)
    print("\n" + "=" * 72)
    if control_ok:
        print("GATE IS BLIND: white Gaussian noise passed the same stop "
              "conditions.\n         No verdict below can be trusted.")
        print("=" * 72)
        return 3
    print("control: white noise correctly REJECTED --",
          "; ".join(control_failures))
    if ok:
        print("VERDICT: PASS -- manufactured noise is within the stop conditions "
              "fixed\n         in the spec before measuring "
              f"(autocorr +-{AUTOCORR_STOP*100:.0f}%, "
              f"channels +-{CHANNEL_STOP*100:.0f}%).")
    else:
        print("VERDICT: STOP -- manufactured noise is NOT a stand-in for real "
              "noise.")
        for f in failures:
            print(f"         {f}")
        print("         The design is wrong. Do not build Tasks 4-7.")
    print("=" * 72)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
