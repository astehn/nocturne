"""Full-size 16-bit TIFFs of every engine, for judging by eye at 100%.

Every file gets the SAME stretch, computed once from the deep-stack truth, and
nothing else is applied — no levels, no curves, no saturation. So the only
difference between these files is the denoiser.

(In normal use each image would get its own autostretch, but that would make a
smoother image render differently for reasons unrelated to denoising, and the
point here is to compare engines rather than stretches.)
"""
from __future__ import annotations
import argparse, os, sys
import numpy as np
from astropy.io import fits

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import data as D
from evaluate import _hwc, apply_model
from model import DenoiseUNet
from nocturne.core.autostretch import _stretch_params, _apply_params
from nocturne.core.image import AstroImage
from nocturne.core.export import save_tiff

ap = argparse.ArgumentParser()
ap.add_argument("--pair", required=True)
ap.add_argument("--run", default=str(paths.RUNS / "s30_v2"))
ap.add_argument("--out", default="/Users/andreasstehn/Desktop/DenoiseComparison")
ap.add_argument("--strengths", default="0.75,1.0")
a = ap.parse_args()

os.makedirs(a.out, exist_ok=True)
cache = os.path.join(a.pair, "_variants")
inp = _hwc(fits.getdata(os.path.join(a.pair, "input.fits")))
tgt = _hwc(fits.getdata(os.path.join(a.pair, "target.fits")))

# one stretch for every file
shadow, m = _stretch_params(tgt.mean(axis=2).astype(np.float32))
print(f"shared stretch: shadow={shadow:.5f} midtones={m:.5f}")

def stretch(x):
    return np.stack([_apply_params(x[:, :, c].astype(np.float32), shadow, m)
                     for c in range(x.shape[2])], axis=2)

def write(name, arr):
    p = os.path.join(a.out, name + ".tif")
    save_tiff(AstroImage(np.clip(stretch(arr), 0, 1), is_linear=False), p)
    print(f"  {name:<34} {os.path.getsize(p)/1e6:>6.1f} MB")

import torch

import paths
dev = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
ck = torch.load(os.path.join(a.run, "best.pt"), map_location=dev)
net = DenoiseUNet(base=ck.get("args", {}).get("base", 32)).to(dev)
net.load_state_dict(ck["model"]); net.eval()
tag = os.path.basename(a.run)
print(f"model: {tag} epoch {ck.get('epoch')}\n")

write("1_INPUT_16frames_noisy", inp)
for s in [float(x) for x in a.strengths.split(",")]:
    asa = D._ASINH_A
    out = D.from_model_space(apply_model(D.to_model_space(inp, asa), net, dev, s), asa)
    write(f"2_OURS_{tag}_strength{s}", out)
for f, label in (("nxt_090", "3_NoiseXTerminator_0.90"),
                 ("graxpert_10", "4_GraXpert_1.0_max")):
    p = os.path.join(cache, f + ".npy")
    if os.path.exists(p):
        write(label, np.load(p))
    else:
        print(f"  {label}: no cached output — run compare_visual.py first")
write("5_TRUTH_128frames", tgt)
print(f"\nall files in {a.out}")
