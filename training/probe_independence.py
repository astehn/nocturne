"""Measure how much of two half-stacks' noise is COMMON, not independent.

The Noise2Noise argument in this project's 2026-08-23 spec is that two
disjoint half-stacks of one group are independent noisy views of the same
sky, so a model trained A->B can only learn what they agree on -- the sky.
That argument fails silently for any noise that is NOT independent: a hot
pixel sits in the same place in every frame, lands identically in both
halves, and is therefore something the two halves "agree" on. The model
would learn it as signal.

rho, as computed here, is directly the fraction of each half's noise that is
common-mode, and therefore the fraction a perfectly-trained model would
faithfully reproduce as if it were real. It is measured on the real
registration/normalisation/integration path, not on an idealisation of it,
because registration and dither are part of what decorrelates a sensor-fixed
defect -- how much, is exactly what is unmeasured.

Thresholds (from the spec, decided before running, so they cannot be
rationalised afterwards):

    rho <= 0.10        proceed
    0.10 < rho <= 0.25 re-measure with sigma_clip; proceed only if it drops
    rho > 0.25         STOP -- Noise2Noise is the wrong tool for this data
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
from scipy.ndimage import gaussian_filter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nocturne.training.pairs import (  # noqa: E402
    discover_frame_groups,
    partition_pair,
    prepare_stack,
)

PROCEED = 0.10
STOP = 0.25


def common_mode_fraction(
    a: np.ndarray,
    b: np.ndarray,
    *,
    hp_sigma: float = 2.0,
    mask_sigma: float = 25.0,
    dark_fraction: float = 0.60,
) -> float:
    """Pearson correlation of two stacks' high-pass residuals, over dark sky.

    High-pass first, or the shared SCENE would dominate and every real pair
    would read ~1.0. hp_sigma and dark_fraction mirror noise.py's _HP_SIGMA
    and _DARK_FRACTION so this measures noise on the same definition of
    "noise" the conditioning channel uses.

    mask_sigma does NOT mirror noise.py, deliberately. noise.py picks the dark
    region off luminance smoothed at _HP_SIGMA, which is fine when the thing
    being measured is zero-mean noise. Here it is not: a common-mode defect is
    typically BRIGHT (hot pixel, warm column, amp glow), so a 2 px smoothing
    lets the defect raise its own neighbourhood above the 60th percentile and
    delete itself from the mask -- measured on the fixed-pattern fixture in
    test_probe_independence.py, a 2 px mask retains 0.03% of the defect pixels
    and reads rho=0.011 on data that is 47% common-mode. Estimating the dark
    region at a scale far above the defect and far below the frame fixes it:
    rho reads 0.468/0.465/0.466/0.467 at mask_sigma 8/16/25/40, so 25.0 is a
    plateau rather than a tuned edge. 25 px also matches the scale
    gate.patch_chroma_bias already uses for the same pixel-scale-vs-scene
    split. The three other fixtures move by <0.002, so this only changes WHERE
    the residual is sampled, never what is measured.
    """
    a = np.asarray(a, np.float32)
    b = np.asarray(b, np.float32)
    if a.ndim == 2:
        a, b = a[:, :, None], b[:, :, None]
    if a.shape != b.shape:
        raise ValueError(f"shape mismatch: {a.shape} vs {b.shape}")

    lum = (a.mean(axis=2) + b.mean(axis=2)) / 2.0
    bg = gaussian_filter(lum, mask_sigma)
    mask = bg <= np.percentile(bg, dark_fraction * 100.0)

    xs, ys = [], []
    for c in range(a.shape[2]):
        xs.append((a[:, :, c] - gaussian_filter(a[:, :, c], hp_sigma))[mask])
        ys.append((b[:, :, c] - gaussian_filter(b[:, :, c], hp_sigma))[mask])
    x = np.concatenate(xs).astype(np.float64)
    y = np.concatenate(ys).astype(np.float64)
    if x.size == 0:
        return 0.0
    x -= x.mean()
    y -= y.mean()
    denom = float(np.sqrt((x * x).sum() * (y * y).sum()))
    if denom <= 0.0:
        return 0.0
    return float((x * y).sum() / denom)


def probe_group(
    group,
    *,
    method: str = "average",
    kappa: float = 2.5,
    seed: int = 20260823,
    workers: int | None = None,
    on_line=print,
) -> dict:
    """Split one group in half, integrate both, and report rho."""
    paths = [f.path for f in group.frames]
    reference = paths[0]
    pool = paths[1:]                       # reference belongs to neither half

    on_line(f"{group.slug}: registering {len(pool)} frames")
    prepared = prepare_stack(pool, reference, workers=workers)
    # Partition only what actually registered: a rejected frame is absent from
    # PreparedStack.frames, and integrate() raises on any path it never saw.
    usable = [p for p in prepared.available_paths if p != prepared.reference_path]
    if prepared.rejected:
        on_line(f"{group.slug}: {len(prepared.rejected)} frame(s) failed registration")
    half = len(usable) // 2
    if half < 1:
        raise ValueError(f"{group.slug}: only {len(usable)} usable frames")
    left, right = partition_pair(usable, input_count=half, target_count=half, seed=seed)

    a = prepared.integrate(left, method=method, kappa=kappa, workers=workers)
    b = prepared.integrate(right, method=method, kappa=kappa, workers=workers)
    rho = common_mode_fraction(a.data, b.data)
    on_line(f"{group.slug}: half={half} method={method} rho={rho:.4f}")
    return {
        "group": group.slug,
        "n_frames": len(group.frames),
        "half": half,
        "method": method,
        "rho": rho,
    }


def verdict(rho: float) -> str:
    if rho <= PROCEED:
        return "proceed"
    if rho <= STOP:
        return "retry-with-sigma-clip"
    return "stop"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", default="/Volumes/Work2/Images/Astro/Training")
    ap.add_argument("--sensor", default="s30")
    ap.add_argument("--targets", nargs="*", default=["M8", "M16", "M45"])
    ap.add_argument("--method", default="average", choices=["average", "sigma_clip"])
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    groups = discover_frame_groups(args.source, sensor=args.sensor,
                                   min_frames=3, combine_nights=True)
    groups = [g for g in groups if not g.mosaic]
    chosen = [g for g in groups if any(t.lower() in g.slug.lower() for t in args.targets)]
    if not chosen:
        print(f"no groups matched {args.targets}", file=sys.stderr)
        return 2

    results = [probe_group(g, method=args.method, workers=args.workers) for g in chosen]
    worst = max(results, key=lambda r: r["rho"])
    print(f"\nWORST: {worst['group']} rho={worst['rho']:.4f} -> {verdict(worst['rho']).upper()}")
    if args.out:
        Path(args.out).write_text(json.dumps(
            {"results": results, "worst": worst, "verdict": verdict(worst["rho"])}, indent=2))
    return 0 if verdict(worst["rho"]) != "stop" else 1


if __name__ == "__main__":
    raise SystemExit(main())
