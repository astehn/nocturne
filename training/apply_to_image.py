"""Run a trained denoise model over one of YOUR OWN images, and write the result.

Every other tool here takes a training *pair*, because they measure the model
against known truth. This one takes any linear FITS you have — a real master —
and hands back a file you can open in Nocturne beside the original.

That matters because of how this project's failures have actually been caught.
The v2 model passed every metric, beat two commercial engines on distance-to-
truth, and still broke a real 405-frame M 8 master into green and magenta
blotches. Nothing found that except Andreas opening the picture and looking at
it. A 700 px crop was not enough either: the damage was large-scale, so it only
showed at full frame.

    .venv-train/bin/python training/apply_to_image.py --image path/to/master.fits

Writes `<name>_denoised_<run>_s<strength>.fits` next to the input by default, so
several strengths can sit side by side without overwriting each other.

Output is LINEAR, like the input — no stretch is applied. Open it in Nocturne
and it goes through your normal pipeline, so what you judge is the denoising and
nothing else. (Stretching here would give a smoother image a different transfer
function and you would be comparing stretches, not denoisers — the same trap
compare_visual.py's docstring describes.)
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import numpy as np
from astropy.io import fits

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_RUN_ROOT = Path("/Volumes/Work2/Images/Astro/denoise_runs")
_DEFAULT_RUN = "n2n_v2"

# Matches nocturne.core.denoise_model.denoise's own default, so what you see
# here is what the app would do to the same image.
_DEFAULT_STRENGTH = 0.75


def output_path(image: str, run: str, strength: float, out: str | None = None) -> Path:
    """Name the result after the run AND the strength it was produced at.

    Both belong in the filename: comparing 0.5 against 1.0 is the usual way to
    judge a denoiser, and a fixed name would silently overwrite the previous
    answer half way through doing that.
    """
    if out:
        return Path(out)
    p = Path(image)
    tag = Path(run).name
    return p.with_name(f"{p.stem}_denoised_{tag}_s{strength:g}.fits")


def resolve_run(run: str) -> Path | None:
    """Accept a bare run NAME as well as a full path.

    Typing the whole /Volumes/... path to compare two models is friction that
    stops the comparison being made, and comparing models on a real master is
    the only check that has ever caught a bad one.
    """
    p = Path(run)
    if (p / "best.pt").is_file():
        return p
    candidate = _RUN_ROOT / run
    if (candidate / "best.pt").is_file():
        return candidate
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--image", required=True, help="a linear FITS master of yours")
    ap.add_argument("--run", default=_DEFAULT_RUN,
                    help="run NAME (e.g. n2n_v2) or a full path to a run directory")
    ap.add_argument("--checkpoint", default="best.pt")
    ap.add_argument("--strength", type=float, default=_DEFAULT_STRENGTH)
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    if not os.path.isfile(args.image):
        print(f"no such image: {args.image}", file=sys.stderr)
        return 2
    run_dir = resolve_run(args.run)
    if run_dir is None:
        names = sorted(d.name for d in _RUN_ROOT.iterdir()
                       if d.is_dir() and (d / "best.pt").is_file()) if _RUN_ROOT.is_dir() else []
        print(f"no run called {args.run!r}. Available: {', '.join(names) or '(none)'}",
              file=sys.stderr)
        return 2
    ck_path = run_dir / args.checkpoint
    if not ck_path.is_file():
        print(f"no checkpoint at {ck_path}", file=sys.stderr)
        return 2

    import torch

    import data as D
    from evaluate import _hwc, apply_model
    from model import DenoiseUNet
    from noise import estimate_sigma
    from nocturne.core.export import save_fits
    from nocturne.core.image import AstroImage

    ck = torch.load(str(ck_path), map_location="cpu")
    in_ch = ck["model"]["enc.0.0.weight"].shape[1]
    device = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
    model = DenoiseUNet(base=ck.get("args", {}).get("base", 32), in_ch=in_ch).to(device)
    model.load_state_dict(ck["model"])
    model.eval()

    with fits.open(args.image) as hdul:
        img = _hwc(np.asarray(hdul[0].data, np.float32))
        src_header = hdul[0].header
    before = estimate_sigma(img)
    print(f"{Path(args.image).name}: {img.shape[1]}x{img.shape[0]}, noise {before:.3e}")
    print(f"applying {ck_path.parent.name}/{args.checkpoint} at strength {args.strength:g} "
          f"on {device.type}...")

    a = D._ASINH_A
    out = D.from_model_space(
        apply_model(D.to_model_space(img, a), model, device, strength=args.strength), a)
    after = estimate_sigma(out)

    # Carry the capture metadata across. Without it the result opens in Nocturne
    # with no frame count and no integration time -- the Import panel goes from
    # "1h 07m (405 x 10s), Frames 405" to nothing, and the provenance report has
    # nothing to record. Structural keys are excluded because astropy writes
    # those itself from the array; passing stale ones would describe the wrong
    # shape.
    _STRUCTURAL = {"SIMPLE", "BITPIX", "EXTEND", "BSCALE", "BZERO",
                   "COMMENT", "HISTORY", ""}
    header = {k: src_header[k] for k in src_header
              if k not in _STRUCTURAL and not k.startswith("NAXIS")}
    header["DENOISE"] = f"{run_dir.name}/{args.checkpoint} @ {args.strength:g}"

    dest = output_path(args.image, str(run_dir), args.strength, args.out)
    save_fits(AstroImage(np.asarray(out, np.float32), is_linear=True), str(dest),
              header=header)
    print(f"noise {before:.3e} -> {after:.3e}  ({1 - after / before:.0%} removed)")
    print(f"\nwrote {dest}")
    print("Open it in Nocturne next to the original and look at the WHOLE frame — "
          "the v2 damage was invisible in a crop.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
