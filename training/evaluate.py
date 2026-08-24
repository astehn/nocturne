"""Does the model help, and what does it cost? Measured on a HELD-OUT target.

This exists because a loss curve cannot answer either question. The recorded
failure in this project is a change that scored well on an image-quality metric
while visibly ruining every star, and the lesson written down at the time was
that averaging metrics cannot see structured damage — count extremes instead.

The unusual luxury here is GROUND TRUTH: the 128-frame stack is what the 8-frame
input should have looked like. So these are not proxies. Every number compares
against what the sky actually was.
"""
from __future__ import annotations

import argparse, glob, json, os, sys
import numpy as np
import torch
from astropy.io import fits

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D
from model import DenoiseUNet
from noise import estimate_sigma

try:
    import sep
except ImportError:
    sep = None


def _hwc(a):
    a = np.asarray(a, np.float32)
    return np.transpose(a, (1, 2, 0)) if a.ndim == 3 and a.shape[0] == 3 else a


@torch.no_grad()
def apply_model(img_hwc, model, device, strength=1.0, tile=256, overlap=32):
    """Tiled inference with a feathered blend, so tile seams cannot appear.

    Sigma is measured ONCE on the whole model-space image, not per tile --
    every tile must be told the same thing about how noisy the image is, or a
    clean edge would read as noisier than a busy centre for no real reason.
    """
    H, W, C = img_hwc.shape
    sigma = estimate_sigma(img_hwc)
    step = tile - overlap
    out = np.zeros((H, W, C), np.float32)
    wsum = np.zeros((H, W, 1), np.float32)
    ramp = np.minimum(np.arange(tile), np.arange(tile)[::-1]).astype(np.float32)
    ramp = np.clip(ramp / max(overlap, 1), 0, 1)
    win = (ramp[:, None] * ramp[None, :])[:, :, None] + 1e-6
    for y in range(0, max(H - overlap, 1), step):
        for x in range(0, max(W - overlap, 1), step):
            y0, x0 = min(y, max(H - tile, 0)), min(x, max(W - tile, 0))
            patch = img_hwc[y0:y0+tile, x0:x0+tile]
            if patch.shape[0] != tile or patch.shape[1] != tile:
                continue
            t = torch.from_numpy(np.ascontiguousarray(patch)).permute(2,0,1)[None].to(device)
            r = model.denoise(t, sigma, strength)[0].permute(1,2,0).cpu().numpy()
            out[y0:y0+tile, x0:x0+tile] += r * win
            wsum[y0:y0+tile, x0:x0+tile] += win
    return out / np.maximum(wsum, 1e-6)


def background_noise(x, mask):
    from scipy.ndimage import gaussian_filter
    lum = x.mean(axis=2) if x.ndim == 3 else x
    hp = lum - gaussian_filter(lum, 2.0)
    v = hp[mask]
    return float(1.4826 * np.median(np.abs(v - np.median(v))))


def chroma_noise(x, mask):
    r, g, b = x[:, :, 0], x[:, :, 1], x[:, :, 2]
    gm, rb = ((r + b) / 2 - g)[mask], (r - b)[mask]
    return float(gm.std()), float(rb.std())


def star_table(ref_lum, img, xs, ys):
    """Flux and half-light radius at FIXED positions taken from the truth image.

    Positions come from one source for every variant — the same trick that made
    scripts/compare_masters.py trustworthy. Re-detecting per image lets centroid
    error masquerade as a real difference.
    """
    lum = img.mean(axis=2) if img.ndim == 3 else img
    R = 6
    flux, rad, col = [], [], []
    H, W = lum.shape
    yy, xx = np.mgrid[-R:R+1, -R:R+1]
    rr = np.sqrt(yy**2 + xx**2)
    for x, y in zip(xs.astype(int), ys.astype(int)):
        if not (R < x < W-R-1 and R < y < H-R-1):
            continue
        cut = lum[y-R:y+R+1, x-R:x+R+1]
        bg = np.median(cut[rr > R-1])
        f = float((cut - bg).clip(0).sum())
        flux.append(f)
        prof = np.array([(cut - bg).clip(0)[rr <= k].sum() for k in range(1, R+1)])
        rad.append(float(np.interp(0.5*f, prof, np.arange(1, R+1))) if f > 0 else np.nan)
        if img.ndim == 3:
            px = img[y-1:y+2, x-1:x+2]
            s = px.sum(axis=(0,1)); s = s / max(s.sum(), 1e-9)
            col.append(s)
    return np.array(flux), np.array(rad), (np.array(col) if col else np.zeros((0,3)))


def evaluate_pair(pair_dir, model, device, strength=1.0):
    inp = _hwc(fits.getdata(os.path.join(pair_dir, "input.fits")))
    tgt = _hwc(fits.getdata(os.path.join(pair_dir, "target.fits")))
    cov = np.asarray(fits.getdata(os.path.join(pair_dir, "coverage.fits")), np.float32)
    if cov.ndim == 3:
        cov = cov[0] if cov.shape[0] <= 3 else cov[:, :, 0]
    full = cov >= cov.max() * 0.999

    a = D._ASINH_A
    out = D.from_model_space(apply_model(D.to_model_space(inp, a), model, device, strength), a)

    lum_t = tgt.mean(axis=2)
    sky = full & (lum_t <= np.percentile(lum_t[full], 60))

    res = {}
    for name, im in (("noisy", inp), ("model", out), ("truth", tgt)):
        gm, rb = chroma_noise(im, sky)
        res[name] = {"noise": background_noise(im, sky), "chroma_gm": gm, "chroma_rb": rb,
                     "err": float(np.abs(im - tgt)[full].mean())}

    if sep is not None:
        L = np.ascontiguousarray(lum_t)
        b = sep.Background(L)
        o = sep.extract(L - b, 8.0, err=b.globalrms)
        o = o[np.argsort(-o["flux"])][:600]
        xs, ys = o["x"], o["y"]
        f_t, r_t, c_t = star_table(lum_t, tgt, xs, ys)
        for name, im in (("noisy", inp), ("model", out)):
            f, r, c = star_table(lum_t, im, xs, ys)
            n = min(len(f), len(f_t))
            ok = (f_t[:n] > 0) & np.isfinite(r[:n]) & np.isfinite(r_t[:n])
            res[name]["star_flux_ratio"] = float(np.median(f[:n][ok] / f_t[:n][ok]))
            res[name]["star_radius_ratio"] = float(np.median(r[:n][ok] / r_t[:n][ok]))
            if len(c) and len(c_t):
                m = min(len(c), len(c_t))
                res[name]["star_colour_shift"] = float(np.abs(c[:m] - c_t[:m]).mean())
        res["stars_measured"] = int(len(f_t))
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="/Volumes/Work2/Images/Astro/denoise_runs/s30_v1")
    ap.add_argument("--pairs", default="/Volumes/Work2/Images/Astro/TrainingPairs")
    # --sensor is the model/run identity; --sensors is the material. See
    # train.py for why they are not the same knob.
    ap.add_argument("--sensor", default="s30")
    ap.add_argument("--sensors", default=",".join(D.TRAINING_SENSORS),
                    help="comma-separated sensors whose tiles feed the split")
    ap.add_argument("--strength", type=float, default=1.0)
    ap.add_argument("--max-pairs", type=int, default=3)
    ap.add_argument("--checkpoint", default="best.pt")
    args = ap.parse_args()

    dev = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
    ck = torch.load(os.path.join(args.run, args.checkpoint), map_location=dev)
    model = DenoiseUNet(base=ck.get("args", {}).get("base", 32)).to(dev)
    model.load_state_dict(ck["model"]); model.eval()
    print(f"checkpoint epoch {ck.get('epoch')}  val {ck.get('val', float('nan')):.5f}  strength {args.strength}")

    tiles = D.scan_tiles(args.pairs)
    sensors = D.parse_sensors(args.sensors)
    _, _, test = D.split_by_target(tiles, sensors)
    test_targets = sorted({t.target for t in test})
    pair_dirs = sorted({os.path.dirname(os.path.dirname(t.path)) for t in test})[:args.max_pairs]
    print(f"HELD-OUT target(s): {', '.join(test_targets)} — never seen in training\n")

    for pd in pair_dirs:
        r = evaluate_pair(pd, model, dev, args.strength)
        print(f"--- {os.path.basename(pd)}   ({r.get('stars_measured','?')} stars)")
        print(f"{'':>8} {'err':>9} {'noise':>9} {'chr_gm':>8} {'chr_rb':>8} "
              f"{'flux':>7} {'radius':>7} {'colour':>7}")
        for k in ("noisy", "model", "truth"):
            v = r[k]
            print(f"{k:>8} {v['err']:>9.5f} {v['noise']:>9.5f} {v['chroma_gm']:>8.5f} "
                  f"{v['chroma_rb']:>8.5f} {v.get('star_flux_ratio', float('nan')):>7.3f} "
                  f"{v.get('star_radius_ratio', float('nan')):>7.3f} "
                  f"{v.get('star_colour_shift', float('nan')):>7.4f}")
        imp = (1 - r["model"]["err"] / r["noisy"]["err"]) * 100
        print(f"   -> error vs truth reduced {imp:.1f}%   "
              f"noise {r['noisy']['noise']/max(r['model']['noise'],1e-12):.2f}x lower\n")


if __name__ == "__main__":
    main()
