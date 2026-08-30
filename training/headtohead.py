"""Where does our model sit between GraXpert and NoiseXTerminator?

Every engine is given the SAME held-out noisy stack and measured against the
SAME 128-frame truth. That is the part no vendor benchmark can do: this is not
"which looks smoother", it is distance from what the sky actually was.
"""
from __future__ import annotations
import argparse, os, sys, time
import numpy as np, torch
from astropy.io import fits

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import data as D
from model import DenoiseUNet
from evaluate import _hwc, apply_model, background_noise, chroma_noise, star_table
from nocturne.core.image import AstroImage
from nocturne.settings import load_settings, resolve_binary, graxpert_valid, rcastro_valid
from nocturne.tools.rcastro import RCAstro
from nocturne.tools.graxpert import GraXpert
from nocturne.core.noise import reduce_noise
import sep

import paths

ap = argparse.ArgumentParser()
ap.add_argument("--pair", required=True)
ap.add_argument("--run", default=str(paths.RUNS / "s30_v1"))
ap.add_argument("--skip-graxpert", action="store_true")
a = ap.parse_args()

S = load_settings(os.path.expanduser("~/.nocturne/settings.json"))
dev = torch.device("mps" if torch.backends.mps.is_available() else "cpu")

inp = _hwc(fits.getdata(os.path.join(a.pair, "input.fits")))
tgt = _hwc(fits.getdata(os.path.join(a.pair, "target.fits")))
cov = np.asarray(fits.getdata(os.path.join(a.pair, "coverage.fits")), np.float32)
if cov.ndim == 3: cov = cov[0] if cov.shape[0] <= 3 else cov[:, :, 0]
full = cov >= cov.max()*0.999
lum_t = tgt.mean(axis=2)
sky = full & (lum_t <= np.percentile(lum_t[full], 60))

L = np.ascontiguousarray(lum_t)
b = sep.Background(L); o = sep.extract(L-b, 8.0, err=b.globalrms)
o = o[np.argsort(-o["flux"])][:600]
xs, ys = o["x"], o["y"]
f_t, r_t, c_t = star_table(lum_t, tgt, xs, ys)

ck = torch.load(os.path.join(a.run, "best.pt"), map_location=dev)
net = DenoiseUNet(base=ck.get("args", {}).get("base", 32)).to(dev)
net.load_state_dict(ck["model"]); net.eval()

def ours(strength):
    asa = D._ASINH_A
    return D.from_model_space(apply_model(D.to_model_space(inp, asa), net, dev, strength), asa)

variants = [("noisy (input)", lambda: inp, 0.0)]
for s in (0.5, 0.75, 1.0):
    variants.append((f"OURS strength {s}", (lambda s=s: ours(s)), 0.0))
if rcastro_valid(S):
    rc = RCAstro(resolve_binary(S.rcastro_path))
    for lv in (0.75, 0.90):
        variants.append((f"NoiseXTerminator {lv}",
                         (lambda lv=lv: rc.denoise(AstroImage(inp, is_linear=True), lv).data), 0.0))
if graxpert_valid(S) and not a.skip_graxpert:
    gx = GraXpert(resolve_binary(S.graxpert_path))
    for lv in (0.9, 1.0):
        variants.append((f"GraXpert {lv}",
                         (lambda lv=lv: gx.denoise(AstroImage(inp, is_linear=True), lv).data), 0.0))
variants.append(("free TV 0.7", lambda: reduce_noise(AstroImage(inp, is_linear=True), 0.7).data, 0.0))

print(f"pair: {os.path.basename(a.pair)}   {len(f_t)} stars   truth = 128-frame stack\n")
print(f"{'engine':<24} {'err vs truth':>12} {'noise':>9} {'chroma':>9} {'star flux':>10} {'radius':>8} {'colour':>8} {'sec':>6}")
print("-"*95)
tn = background_noise(tgt, sky); tc = chroma_noise(tgt, sky)[0]
for name, fn, _ in variants:
    t0 = time.time()
    try:
        im = np.asarray(fn(), np.float32)
    except Exception as e:
        print(f"{name:<24} FAILED: {type(e).__name__}: {str(e)[:40]}"); continue
    dt = time.time()-t0
    err = float(np.abs(im - tgt)[full].mean())
    n = background_noise(im, sky); ch = chroma_noise(im, sky)[0]
    f, r, c = star_table(lum_t, im, xs, ys)
    k = min(len(f), len(f_t)); ok = (f_t[:k] > 0) & np.isfinite(r[:k]) & np.isfinite(r_t[:k])
    fr = float(np.median(f[:k][ok]/f_t[:k][ok])); rr = float(np.median(r[:k][ok]/r_t[:k][ok]))
    cs = float(np.abs(c[:min(len(c),len(c_t))] - c_t[:min(len(c),len(c_t))]).mean()) if len(c) else float("nan")
    print(f"{name:<24} {err:>12.6f} {n:>9.6f} {ch:>9.6f} {fr:>10.3f} {rr:>8.3f} {cs:>8.4f} {dt:>6.0f}")
print("-"*95)
print(f"{'TRUTH (128 frames)':<24} {0.0:>12.6f} {tn:>9.6f} {tc:>9.6f} {1.0:>10.3f} {1.0:>8.3f} {0.0:>8.4f}")
