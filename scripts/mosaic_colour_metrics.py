"""Measure panel tiling in a mosaic: does the colour agree between panels?

    .venv/bin/python scripts/mosaic_colour_metrics.py <master.fits> [--label L]
    .venv/bin/python scripts/mosaic_colour_metrics.py a.fits b.fits --compare

Developer tool, NOT shipped. Written for the 2026-09-04 per-channel offset work
(docs/MOSAIC_COLOUR_MATCHING_PLAN.md).

WHAT IT MEASURES

`match_offsets` matched panel BRIGHTNESS across every overlap and panel COLOUR
across none, so each panel kept its own tint. Brightness spread is therefore the
wrong number to watch: it contains the real sky gradient and the galaxy's outer
halo, and driving it to zero would mean subtracting signal. The number that must
fall is the spread of each channel's RATIO to the patch's own brightness, which
is blind to how bright a patch is and sees only its colour.

RECONSTRUCTED, and that matters for reading the result. The original ad-hoc
function that produced docs/mosaic-colour/baseline.json was not kept, so this
follows its written description — resize by 1/16, 24 background patches from the
LEFT 40% (away from M 31 itself), spread of each channel's ratio to the patch
mean — but cannot be byte-identical to it. So:

  * comparing two runs measured HERE is exact, and that is the actual test;
  * comparing to baseline.json is indicative only, and is additionally measured
    on a different image (Andreas' starless export, not a raw mosaic master).

One deliberate departure: patch statistics are MEDIANS, not means. The baseline
was measured on a starless export; a raw mosaic master still has its stars, and
a single bright star in a patch moves a mean and not a median.

MEASURE STRETCHED (--stretch), and understand why it is not optional.

Panels differ by an ADDITIVE offset. Against a linear background B, an offset d
gives a colour ratio of about (B+d)/B, which is close to 1 while B is large — so
a linear master reports a colour spread of 0.06% for tiling that is glaring on
screen. A stretch subtracts a black point sitting just under B, and the residual
turns that same d into a large relative difference. The tiling is a property of
the picture people look at, so it has to be measured on the picture people look
at. Measured both ways on the same M 31 master: 0.062% linear against a figure
two orders larger stretched.

Using the app's own `neutral_stretch` rather than an ad-hoc one, so the number
describes what Nocturne actually shows. Both runs get the identical transform,
so the comparison stays fair even though that stretch has its own known
per-channel clipping defect (see TODO).
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SHRINK = 16
LEFT_FRAC = 0.40      # M 31 sits right of this on Andreas' framing
N_PATCHES = 24
PATCH = 24            # patch side, in shrunken pixels


def _load_rgb(path: str) -> np.ndarray:
    from astropy.io import fits
    if path.lower().endswith((".tif", ".tiff")):
        import tifffile
        arr = np.asarray(tifffile.imread(path)).astype(np.float64)
    else:
        arr = np.asarray(fits.getdata(path)).astype(np.float64)
        if arr.ndim == 3 and arr.shape[0] == 3:      # FITS stores (3, h, w)
            arr = np.transpose(arr, (1, 2, 0))
    if arr.ndim != 3 or arr.shape[2] != 3:
        raise SystemExit(f"{path}: expected a colour image, got shape {arr.shape}")
    peak = float(np.nanmax(arr))
    return arr / peak if peak > 0 else arr


def stretched(rgb: np.ndarray) -> np.ndarray:
    """The app's default view of this data — see the module docstring."""
    from nocturne.core.autostretch import neutral_stretch
    return np.asarray(neutral_stretch(rgb.astype(np.float32)), np.float64)


def _shrink(rgb: np.ndarray, factor: int = SHRINK) -> np.ndarray:
    """Block mean. Averaging is the point — it is what suppresses the noise that
    would otherwise dominate a per-pixel colour ratio."""
    h, w = rgb.shape[0] // factor * factor, rgb.shape[1] // factor * factor
    return rgb[:h, :w].reshape(h // factor, factor,
                               w // factor, factor, 3).mean(axis=(1, 3))


def tiling_metrics(rgb: np.ndarray, reuse: list | None = None) -> dict:
    """`reuse` pins the patch LOCATIONS from an earlier call.

    Without it each image picks its own 24 darkest patches, so two runs are
    measured over different regions and the difference between them is partly
    just that. Two mosaics built from the same panels share their geometry
    exactly, so the same coordinates are the same sky in both — and only then is
    the before/after a measurement rather than a comparison of two samples.
    """
    small = _shrink(rgb)
    h, w = small.shape[:2]
    left = small[:, : max(PATCH, int(w * LEFT_FRAC))]

    # Candidate patches on a grid, then keep the DARKEST ones: those are sky
    # rather than galaxy, and it is sky whose colour should agree everywhere.
    patches = []
    for y in range(0, left.shape[0] - PATCH, PATCH):
        for x in range(0, left.shape[1] - PATCH, PATCH):
            block = left[y:y + PATCH, x:x + PATCH]
            if not np.isfinite(block).all() or float(np.median(block)) <= 0:
                continue                       # off-canvas: no panel reached here
            patches.append((float(np.median(block)), y, x))
    if reuse is not None:
        chosen = reuse
    else:
        if len(patches) < N_PATCHES:
            raise SystemExit(f"only {len(patches)} usable background patches found")
        patches.sort()
        chosen = patches[: N_PATCHES]

    per_channel = np.array([np.median(left[y:y + PATCH, x:x + PATCH].reshape(-1, 3),
                                      axis=0)
                            for _m, y, x in chosen])          # (N_PATCHES, 3)
    brightness = per_channel.mean(axis=1)                     # (N_PATCHES,)
    ratios = per_channel / brightness[:, None]                # colour, scale-free

    def spread(v):
        v = np.asarray(v, np.float64)
        return float(np.std(v) / np.mean(v) * 100.0) if np.mean(v) else 0.0

    chan = {name: round(spread(ratios[:, i]), 3) for i, name in enumerate("RGB")}
    return {
        "patches": len(chosen),
        "brightness_spread_pct": round(spread(brightness), 3),
        "colour_ratio_spread_pct": chan,
        "colour_spread_mean_pct": round(float(np.mean(list(chan.values()))), 3),
        "_patches": chosen,
    }


def saturated_preview(rgb: np.ndarray, out_path: str, boost: float = 3.0,
                      max_width: int = 1800) -> None:
    """The x3-saturation view: the picture that made the tiling obvious."""
    from PIL import Image
    step = max(1, rgb.shape[1] // max_width)
    view = rgb[::step, ::step]
    lum = view.mean(axis=2, keepdims=True)
    sat = np.clip(lum + (view - lum) * boost, 0.0, 1.0)
    hi = float(np.percentile(sat, 99.5)) or 1.0
    img = np.clip(sat / hi, 0, 1) ** (1 / 2.2)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    Image.fromarray((img * 255).astype(np.uint8)).save(out_path, quality=92)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--label", default="")
    ap.add_argument("--preview-dir", default="")
    ap.add_argument("--out", default="")
    ap.add_argument("--stretch", action="store_true",
                    help="measure the STRETCHED picture — see the module docstring; "
                         "a linear master understates tiling by ~100x")
    args = ap.parse_args(argv)

    rows, pinned = [], None
    for path in args.paths:
        rgb = _load_rgb(path)
        if args.stretch:
            rgb = stretched(rgb)
        m = tiling_metrics(rgb, reuse=pinned)
        pinned = m.pop("_patches")          # every later image measures HERE
        m["stretched"] = bool(args.stretch)
        m["path"] = path
        m["label"] = args.label or os.path.basename(path)
        m["size"] = [int(rgb.shape[1]), int(rgb.shape[0])]
        if args.preview_dir:
            p = os.path.join(args.preview_dir,
                             os.path.splitext(os.path.basename(path))[0]
                             + "-saturated.jpg")
            saturated_preview(rgb, p)
            m["preview"] = p
        rows.append(m)
        print(f"{m['label']}: colour spread {m['colour_spread_mean_pct']}%  "
              f"(R {m['colour_ratio_spread_pct']['R']} "
              f"G {m['colour_ratio_spread_pct']['G']} "
              f"B {m['colour_ratio_spread_pct']['B']})   "
              f"brightness {m['brightness_spread_pct']}%", flush=True)

    if len(rows) == 2:
        a, b = rows
        d = b["colour_spread_mean_pct"] - a["colour_spread_mean_pct"]
        pct = 100.0 * d / a["colour_spread_mean_pct"] if a["colour_spread_mean_pct"] else 0
        print(f"\ncolour spread {a['colour_spread_mean_pct']}% -> "
              f"{b['colour_spread_mean_pct']}%   ({pct:+.1f}%)")
        print(f"brightness    {a['brightness_spread_pct']}% -> "
              f"{b['brightness_spread_pct']}%   (should NOT fall much — it holds "
              f"the real sky gradient)")
    if args.out:
        with open(args.out, "w") as f:
            json.dump(rows, f, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
