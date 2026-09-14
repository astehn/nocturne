#!/usr/bin/env python3
"""Compare noise reduction BEFORE the stretch against AFTER it, and one pass
against several — using Nocturne's own functions, so the answer is about
Nocturne's pipeline rather than about two different applications.

Why this exists. Andreas, 2026-09-13, comparing against AstroWizard: it runs
"Step 6: Linear Noise Reduction" (before the stretch) and drives
NoiseXTerminator for THREE passes; Nocturne denoises after the stretch, once.
He also reports his stacks come out "a bit cleaner" from the other tool. Those
are three separate claims and only the third is subjective — but none of them
can be settled by processing in both apps, because then everything else differs
too.

So: one master, one chain, ONE variable at a time.

    .venv/bin/python scripts/nr_experiment.py MASTER.fits --out runs/

Every variant shares the same load, the same colour calibration and the same
stretch amount. Only the position and the pass count move. Each variant writes
a PNG and a row of numbers; `--crop` writes 1:1 crops too, because the metrics
cannot see "plastic" and your eye can.

The three metrics are the ones the August 2026 NoiseSharpen calibration used on
a real M 45 master (see steps/noise_sharpen.py), so today's numbers are
comparable with the ones already written down there:

    lumN    background luminance noise  - lower is cleaner
    chroma  background colour noise     - lower is cleaner
    starR   median star radius, px      - MUST stay flat; if it falls, the
                                          denoise is eating stars, and a
                                          "cleaner" image that lost its stars
                                          is not a better one
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nocturne.core.color import ColorSettings, apply_color          # noqa: E402
from nocturne.core.fits_io import load_fits                          # noqa: E402
from nocturne.core.image import AstroImage                           # noqa: E402
from nocturne.core.stretch import apply_stretch                      # noqa: E402
from nocturne.steps.deconvolution_step import _LEVELS as _DECON_LEVELS  # noqa: E402
from nocturne.settings import (                                      # noqa: E402
    load_settings, resolve_settings_path,
)
from nocturne.steps.noise_sharpen import (                           # noqa: E402
    _GX_LEVELS, _NXT_LEVELS,
)


# ----------------------------------------------------------------- metrics
def _background_mask(lum: np.ndarray) -> np.ndarray:
    """Pixels that are sky, by sigma-clipping. Noise has to be measured where
    there is no object, or the object's own structure reads as noise."""
    m = lum.copy()
    keep = np.ones(m.shape, bool)
    for _ in range(5):
        med = float(np.median(m[keep]))
        sd = float(np.std(m[keep])) or 1e-9
        new = keep & (m < med + 2.0 * sd)
        if new.sum() == keep.sum() or new.sum() < 100:
            break
        keep = new
    return keep


def reference_stars(img: AstroImage, limit: int = 400):
    """Star positions detected ONCE, on the control, and reused for every
    variant.

    Detecting per variant is the trap. `sep.extract`'s threshold is a multiple
    of the frame's own background RMS, and denoising moves that RMS by a factor
    of two — so each variant finds a DIFFERENT set of stars, mostly fainter and
    broader ones, and the median radius rises. Measured on a real NGC 6888
    master: per-variant detection reported star radius growing 3.99 -> 5.51 px
    under a denoise, which would mean denoising made stars bigger. It did not;
    the metric had changed its mind about which objects were stars.

    Same family of error as the three sharpness metrics that failed before the
    stacking work (see the master-sharpness notes): a measurement that moves
    with the thing it is supposed to control for.
    """
    try:
        import sep
    except ImportError:                                  # pragma: no cover
        return None
    a = np.ascontiguousarray(img.data.mean(axis=2) if img.data.ndim == 3
                             else img.data, dtype=np.float32)
    bkg = sep.Background(a)
    srcs = sep.extract(a - bkg.back(), 8.0, err=bkg.globalrms)
    if len(srcs) < 20:
        return None
    srcs = srcs[np.argsort(srcs["flux"])[::-1][:limit]]   # brightest only
    return srcs["x"].copy(), srcs["y"].copy(), srcs["a"].copy()


def measure(img: AstroImage, stars=None) -> dict:
    d = np.clip(img.data.astype(np.float32), 0, 1)
    if d.ndim == 2:
        d = np.repeat(d[:, :, None], 3, axis=2)
    lum = d.mean(axis=2)
    bg = _background_mask(lum)

    # Luminance noise: MAD, not std — a std over the background is still pulled
    # by the faint outer signal the clip did not remove.
    lv = lum[bg]
    lum_noise = float(np.median(np.abs(lv - np.median(lv)))) * 1.4826

    # Chroma: distance from grey, per background pixel. This is what "colour
    # mottling" is, and it is the number NoiseXTerminator moves most.
    chroma = float(np.median(np.abs(d[bg] - lum[bg][:, None]).sum(axis=1)))

    star_r = _median_star_radius(lum, stars)
    return {"lumN": lum_noise, "chroma": chroma, "starR": star_r,
            "bg_frac": float(bg.mean())}


def _median_star_radius(lum: np.ndarray, stars) -> float:
    """Median half-light radius of THE SAME stars in every variant.

    The guard rail: a denoise that shrinks this is eating stars, not noise, and
    a cleaner picture with smaller stars is not the better picture. Positions
    come from `reference_stars` on the control — see there for why detecting
    per variant gives a number that moves on its own.
    """
    if stars is None:
        return float("nan")
    try:
        import sep
        x, y, a_ax = stars
        arr = np.ascontiguousarray(lum, dtype=np.float32)
        bkg = sep.Background(arr)
        r, _flag = sep.flux_radius(arr - bkg.back(), x, y, 6.0 * a_ax, 0.5, subpix=5)
        r = r[np.isfinite(r)]
        return float(np.median(r)) if r.size else float("nan")
    except Exception:                                    # pragma: no cover
        return float("nan")


# ----------------------------------------------------------------- pipeline
def denoise(img: AstroImage, step, option, passes: int,
            label: str, knobs: dict | None = None) -> AstroImage:
    """Run the real step `passes` times. AstroWizard runs NoiseXTerminator three
    times; whether repetition beats a single stronger pass is exactly what this
    script is for, so the passes go through the SAME code the app uses."""
    out = img
    for i in range(passes):
        t = time.time()
        if knobs:
            # Straight at the engine, so --iterations and --denoise-color can be
            # exercised. The STEP has no opinion on these — they are NXT's own —
            # and giving it one would mean shipping a setting before knowing
            # whether it is worth having.
            out = step._rc.denoise(out, knobs["strength"],
                                   iterations=knobs.get("iterations"),
                                   denoise_color=knobs.get("denoise_color"),
                                   runner=step._runner)
        else:
            out = step.apply(out, option)
        print(f"      {label} pass {i + 1}/{passes}  ({time.time() - t:.1f}s)")
    return out


def deconvolve(img: AstroImage, rc, strength: float) -> AstroImage:
    """BlurXTerminator, at the pipeline position the app uses: after colour,
    BEFORE the stretch. It is a linear-domain tool, which is the whole reason
    this cannot be tested by exporting a finished TIFF and working on that.

    Both sharpen knobs move together, matching DeconvolutionStep's own _LEVELS.
    """
    t = time.time()
    out = rc.deconvolve(img, sharpen_stars=strength, sharpen_nonstellar=strength)
    print(f"      deconvolution {strength}  ({time.time() - t:.1f}s)")
    return out


def run_variant(base: AstroImage, *, position: str, passes: int, option,
                stretch_amount: float, step, knobs=None, decon=None, rc=None
                ) -> AstroImage:
    """One variant. Identical to every other except the things being swept."""
    img = base
    if decon is not None:
        img = deconvolve(img, rc, decon)
    if position == "pre":
        img = denoise(img, step, option, passes, "linear NR", knobs)
    img = apply_stretch(img, stretch_amount)
    if position == "post":
        img = denoise(img, step, option, passes, "post-stretch NR", knobs)
    return img


def parse_crop(spec: str | None):
    """`SIZE` | `X,Y` | `X,Y,SIZE` -> (x, y, size) or (None, None, size) for a
    centred crop. Forgiving on purpose: a bare number is the obvious thing to
    type and there is no reason to refuse it."""
    if not spec:
        return None
    parts = [p.strip() for p in str(spec).split(",") if p.strip()]
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        raise ValueError(f"--crop wants whole numbers, got {spec!r}")
    if len(nums) == 1:
        return (None, None, nums[0])          # centred crop of this size
    if len(nums) == 2:
        return (nums[0], nums[1], 500)
    if len(nums) == 3:
        return (nums[0], nums[1], nums[2])
    raise ValueError(
        f"--crop takes SIZE, X,Y or X,Y,SIZE — got {len(nums)} values in {spec!r}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("master", help="a stacked FITS master")
    ap.add_argument("--out", default="nr_experiment", help="output directory")
    ap.add_argument("--engine", default="rcastro",
                    choices=("rcastro", "graxpert"),
                    help="denoise engine (default rcastro / NoiseXTerminator)")
    ap.add_argument("--level", default="medium",
                    choices=("light", "medium", "strong"))
    ap.add_argument("--passes", default="1,3",
                    help="comma-separated pass counts to try (default 1,3)")
    ap.add_argument("--positions", default="pre,post",
                    help="comma-separated: pre,post (default both)")
    ap.add_argument("--stretch", type=float, default=0.43,
                    help="stretch amount; default 0.43, the app's own default")
    ap.add_argument("--decon", default="",
                    help="Deconvolution strengths to sweep, comma-separated. "
                         "Level names (light/medium/strong = 0.3/0.5/0.7) or "
                         "bare numbers. Runs BEFORE the stretch, where the app "
                         "runs it. Omit for no deconvolution at all.")
    ap.add_argument("--iterations", default="",
                    help="NXT --iterations values to try, comma-separated. "
                         "NXT's own default is 2 and is used when this is "
                         "omitted. rcastro engine only.")
    ap.add_argument("--denoise-color", default="", dest="denoise_color",
                    help="NXT --denoise-color values to try, comma-separated. "
                         "Defaults to whatever --denoise is. rcastro only.")
    ap.add_argument("--crop", default=None, metavar="SPEC",
                    help="also write a 1:1 crop. SIZE (centred), X,Y (500 px "
                         "there) or X,Y,SIZE. e.g. --crop 600  or  --crop 2100,1400,600")
    args = ap.parse_args()

    # Validated HERE, before the minute of loading, calibrating and star
    # detection — a bad argument used to crash after all of that, on the first
    # _save. Cheap checks belong before expensive work, not after it.
    try:
        crop = parse_crop(args.crop)
    except ValueError as exc:
        ap.error(str(exc))

    # The SAME settings file the app uses, so the engines and their paths
    # are exactly what you get when you press the button in Nocturne.
    settings = load_settings(resolve_settings_path())
    from nocturne.steps.factory import make_step
    step = make_step("noise_sharpen", settings)
    option = {"engine": args.engine, "level": args.level}
    strength = (_NXT_LEVELS if args.engine == "rcastro" else _GX_LEVELS)[args.level]

    os.makedirs(args.out, exist_ok=True)
    print(f"loading {args.master}")
    raw = load_fits(args.master)
    print(f"  {raw.data.shape}  linear={raw.is_linear}")

    # One colour calibration, shared by every variant, so colour is not a
    # variable. Sky balance rather than photometric: no network, no catalogue,
    # and the same answer every run.
    base = apply_color(raw, ColorSettings(neutralize_background=True))

    rows = []
    # The control: no denoise at all. Without it "cleaner" has no zero point.
    print("\n--- control: no denoise ---")
    ctrl = apply_stretch(base, args.stretch)
    stars = reference_stars(ctrl)
    n = 0 if stars is None else len(stars[0])
    print(f"  {n} reference stars, measured at these positions in every variant")
    rows.append(("none", "-", 0, measure(ctrl, stars)))
    _save(ctrl, os.path.join(args.out, "none.png"), crop, args.out, "none")

    decons = []
    for v in (x.strip() for x in args.decon.split(",")):
        if not v:
            continue
        decons.append(_DECON_LEVELS[v][0] if v in _DECON_LEVELS else float(v))
    decons = decons or [None]
    if decons != [None] and getattr(step, "_rc", None) is None:
        raise SystemExit("--decon needs RC-Astro (BlurXTerminator); none configured.")

    iters = [int(v) for v in args.iterations.split(",") if v.strip()] or [None]
    colours = [float(v) for v in args.denoise_color.split(",") if v.strip()] or [None]
    if args.engine != "rcastro" and (iters != [None] or colours != [None]):
        print("note: --iterations and --denoise-color are NoiseXTerminator's "
              "own options and are ignored for graxpert.")
        iters, colours = [None], [None]

    for dec in decons:
      for position in [p.strip() for p in args.positions.split(",") if p.strip()]:
        for passes in [int(p) for p in args.passes.split(",") if p.strip()]:
            for it in iters:
                for dc in colours:
                    # Only reach past the step when there is something to say;
                    # otherwise go through step.apply, which is the app's path.
                    knobs = None
                    if it is not None or dc is not None:
                        knobs = {"strength": strength, "iterations": it,
                                 "denoise_color": dc}
                    name = f"{position}_x{passes}"
                    extra = ""
                    if dec is not None:
                        name += f"_bxt{dec}"; extra += f", deconvolution {dec}"
                    if it is not None:
                        name += f"_it{it}"; extra += f", --iterations {it}"
                    if dc is not None:
                        name += f"_dc{dc}"; extra += f", --denoise-color {dc}"
                    print(f"\n--- {name}: {args.engine} {args.level} "
                          f"(strength {strength}), {passes} pass(es), "
                          f"NR {position}-stretch{extra} ---")
                    t0 = time.time()
                    out = run_variant(base, position=position, passes=passes,
                                      option=option, stretch_amount=args.stretch,
                                      step=step, knobs=knobs, decon=dec,
                                      rc=getattr(step, "_rc", None))
                    took = time.time() - t0
                    m = measure(out, stars)
                    m["seconds"] = round(took, 1)
                    m["label"] = (f"bxt{dec} " if dec is not None else "") + \
                        f"{position}-stretch x{passes}" + (
                        f" it{it}" if it is not None else "") + (
                        f" dc{dc}" if dc is not None else "")
                    rows.append((position, args.level, passes, m))
                    _save(out, os.path.join(args.out, name + ".png"), crop,
                          args.out, name)

    _report(rows, args, strength)
    return 0


def _save(img: AstroImage, path: str, crop, out_dir: str, name: str) -> None:
    from PIL import Image
    from nocturne.ui.preview import to_rgb8
    rgb = to_rgb8(img)
    Image.fromarray(rgb).save(path)
    if crop:
        x, y, size = crop
        h, w = rgb.shape[:2]
        size = max(16, min(size, h, w))
        if x is None:
            x, y = (w - size) // 2, (h - size) // 2
        x = max(0, min(x, w - size)); y = max(0, min(y, h - size))
        Image.fromarray(rgb[y:y + size, x:x + size]).save(
            os.path.join(out_dir, f"crop_{name}.png"))


def _report(rows, args, strength) -> None:
    print("\n" + "=" * 78)
    print(f"{args.engine} {args.level} (strength {strength})   "
          f"stretch {args.stretch}   master {os.path.basename(args.master)}")
    print("=" * 78)
    print(f"{'variant':26s} {'lumN':>9s} {'chroma':>9s} {'starR':>8s} {'secs':>7s}")
    base_lum = rows[0][3]["lumN"]
    for position, level, passes, m in rows:
        label = "no denoise" if passes == 0 else m.get(
            "label", f"{position}-stretch x{passes}")
        drop = ("" if passes == 0 else
                f"   {(1 - m['lumN'] / base_lum) * 100:.0f}% less noise")
        print(f"{label:26s} {m['lumN']:9.5f} {m['chroma']:9.5f} "
              f"{m['starR']:8.3f} {m.get('seconds', 0):7.1f}{drop}")
    if any("bxt" in (m.get("label") or "") for *_x, m in rows):
        # The guard rail INVERTS when deconvolution is in play. BlurX exists to
        # tighten stars, so a falling starR is the intended effect here, not a
        # warning — measured on NGC 6888, bxt0.5 took 7.58 -> 5.52 and bxt0.7 to
        # 4.79. Printing "starR must stay FLAT" over that would have told
        # Andreas his good result was a bad one.
        print("\nstarR FALLING is the POINT here — that is what deconvolution")
        print("does. Watch instead for stars going hard-edged or dark-ringed,")
        print("and for nebulosity turning crunchy. Neither is in these numbers.")
    else:
        print("\nstarR must stay FLAT. A variant that wins on noise and loses star")
        print("radius has removed stars, and is not the better picture.")
    print(f"\nPNGs in {args.out}/ — look at them. The metrics cannot see 'plastic'.")
    with open(os.path.join(args.out, "results.json"), "w") as f:
        json.dump([{"position": p, "level": l, "passes": n, **m}
                   for p, l, n, m in rows], f, indent=2)


if __name__ == "__main__":
    raise SystemExit(main())
