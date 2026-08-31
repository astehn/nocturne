"""Side-by-side crops: noisy | ours | NoiseXTerminator | GraXpert | truth.

THE ONE THING THAT MAKES THIS FAIR: every variant is displayed through the SAME
stretch, computed once from the truth image. Nocturne's autostretch derives its
parameters from each image's own median and MAD, so a smoother image would get a
DIFFERENT transfer function and appear brighter or flatter for reasons that have
nothing to do with denoising. Letting each panel stretch itself would produce a
comparison of the stretch, not of the engines.

Variants are cached as .npy, because GraXpert takes ~4.5 minutes per level and
nobody should pay that twice to re-crop an image.
"""
from __future__ import annotations
import argparse, os, sys
import numpy as np
from astropy.io import fits
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import data as D
from evaluate import _hwc, apply_model
from model import DenoiseUNet

import paths


def display_params(truth):
    """Shadow clip and midtone from the TRUTH, used for every panel.

    Uses Nocturne's OWN autostretch rather than a reimplementation. The first
    version of this function inverted the midtones solve — it wrote
    (median-1)*target where the real form is (target-1)*median — which produced
    m = 0.985 and rendered every panel pure black. Borrowing the app's code also
    means the crops look like what the user actually sees on the canvas.
    """
    from nocturne.core.autostretch import _stretch_params
    return _stretch_params(truth.mean(axis=2).astype(np.float32))


def show(img, shadow, m):
    from nocturne.core.autostretch import _apply_params
    if img.ndim == 2:
        return _apply_params(img.astype(np.float32), shadow, m)
    return np.stack([_apply_params(img[:, :, c].astype(np.float32), shadow, m)
                     for c in range(img.shape[2])], axis=2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pair", required=True)
    ap.add_argument("--run", default=str(paths.RUNS / "s30_v2"))
    ap.add_argument("--out", default="/Users/andreasstehn/Desktop/denoise_comparison.png")
    ap.add_argument("--strength", type=float, default=1.0)
    ap.add_argument("--zoom", type=int, default=2)
    ap.add_argument("--crop", type=int, default=340)
    ap.add_argument("--skip-slow", action="store_true", help="use cached GraXpert/NXT only")
    args = ap.parse_args()

    import torch
    from nocturne.core.image import AstroImage
    from nocturne.settings import load_settings, resolve_binary, graxpert_valid, rcastro_valid
    from nocturne.tools.rcastro import RCAstro
    from nocturne.tools.graxpert import GraXpert

    cache = os.path.join(args.pair, "_variants")
    os.makedirs(cache, exist_ok=True)
    S = load_settings(os.path.expanduser("~/.nocturne/settings.json"))
    dev = torch.device("mps" if torch.backends.mps.is_available() else "cpu")

    inp = _hwc(fits.getdata(os.path.join(args.pair, "input.fits")))
    tgt = _hwc(fits.getdata(os.path.join(args.pair, "target.fits")))

    def cached(name, fn):
        p = os.path.join(cache, name + ".npy")
        if os.path.exists(p):
            return np.load(p)
        if args.skip_slow:
            return None
        print(f"  computing {name} ...", flush=True)
        a = np.asarray(fn(), np.float32); np.save(p, a); return a

    ck = torch.load(os.path.join(args.run, "best.pt"), map_location=dev)
    net = DenoiseUNet(base=ck.get("args", {}).get("base", 32)).to(dev)
    net.load_state_dict(ck["model"]); net.eval()
    tag = os.path.basename(args.run)

    def ours():
        asa = D._ASINH_A
        return D.from_model_space(apply_model(D.to_model_space(inp, asa), net, dev, args.strength), asa)

    panels = [("noisy input", inp)]
    o = cached(f"ours_{tag}_{args.strength}", ours)
    if o is not None: panels.append((f"OURS ({tag}, {args.strength})", o))
    if rcastro_valid(S):
        rc = RCAstro(resolve_binary(S.rcastro_path))
        v = cached("nxt_090", lambda: rc.denoise(AstroImage(inp, is_linear=True), 0.90).data)
        if v is not None: panels.append(("NoiseXTerminator 0.90", v))
    if graxpert_valid(S):
        gx = GraXpert(resolve_binary(S.graxpert_path))
        v = cached("graxpert_10", lambda: gx.denoise(AstroImage(inp, is_linear=True), 1.0).data)
        if v is not None: panels.append(("GraXpert 1.0 (max)", v))
    panels.append(("TRUTH: 128 frames", tgt))

    shadow, m = display_params(tgt)
    H, W = tgt.shape[:2]
    regions = {"star field": (H//2 - args.crop//2, W//2 - args.crop//2),
               "faint background": (int(H*0.22), int(W*0.25))}

    c, z = args.crop, args.zoom
    tile = c * z
    sheet = Image.new("RGB", (tile*len(panels) + 20*(len(panels)-1), (tile+34)*len(regions)), (10,12,16))
    dr = ImageDraw.Draw(sheet)
    y = 0
    for rname, (y0, x0) in regions.items():
        for i, (label, im) in enumerate(panels):
            crop = show(im[y0:y0+c, x0:x0+c], shadow, m)
            pil = Image.fromarray((crop*255+0.5).astype(np.uint8)).resize((tile, tile), Image.NEAREST)
            x = i*(tile+20)
            sheet.paste(pil, (x, y))
            dr.text((x+6, y+tile+8), f"{rname} — {label}", fill=(205,212,226))
        y += tile + 34
    sheet.save(args.out)
    print("wrote", args.out, sheet.size)


if __name__ == "__main__":
    main()
