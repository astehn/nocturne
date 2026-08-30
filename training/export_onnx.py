"""Export the trained model to ONNX, and PROVE it matches PyTorch.

Nocturne must never depend on torch. It gets this file and onnxruntime, so the
export is the handoff — and an export that quietly differs from what was
measured would invalidate every number we have. The parity check is the point.
"""
from __future__ import annotations
import argparse, json, os, sys
import numpy as np, torch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D
from model import DenoiseUNet, SIGMA_SCALE

ap = argparse.ArgumentParser()
ap.add_argument("--run", default=str(paths.RUNS / "s30_v2"))
ap.add_argument("--out", default="nocturne/assets/models/denoise_s30_v1.onnx")
ap.add_argument("--tile", type=int, default=256)
a = ap.parse_args()

ck = torch.load(os.path.join(a.run, "best.pt"), map_location="cpu")
net = DenoiseUNet(base=ck.get("args", {}).get("base", 32))
net.load_state_dict(ck["model"]); net.eval()

os.makedirs(os.path.dirname(a.out), exist_ok=True)
dummy = torch.randn(1, 4, a.tile, a.tile)
torch.onnx.export(
    net, dummy, a.out, input_names=["input"], output_names=["noise"],
    dynamic_axes={"input": {0: "batch", 2: "h", 3: "w"},
                  "noise": {0: "batch", 2: "h", 3: "w"}},
    opset_version=17,
)
# Collapse external weights back into ONE file. Torch's exporter splits tensors
# into a sibling .onnx.data by default, leaving a ~13 KB graph stub — ship that
# alone and the model fails to load at the user's machine while every local test
# passes, because the .data file is still sitting next to it here.
import onnx
m = onnx.load(a.out)                      # follows the external .data
onnx.save_model(m, a.out, save_as_external_data=False)
for stray in (a.out + ".data",):
    if os.path.exists(stray):
        os.remove(stray)
size = os.path.getsize(a.out) / 1e6
print(f"exported {a.out}  ({size:.1f} MB, self-contained)")
assert size > 5, "weights are not embedded — the file is a graph stub"

def _random_tile(h: int, w: int, rng: np.random.Generator) -> np.ndarray:
    """3 image channels + 1 constant sigma-map channel, matching what
    denoise() concatenates before calling forward() -- the exported graph's
    input IS this 4-channel tensor, not a bare RGB tile."""
    img = rng.random((1, 3, h, w), dtype=np.float32) * 0.6 + 0.2
    sigma = rng.uniform(0.0005, 0.0025)          # plausible real-tile range
    smap = np.full((1, 1, h, w), sigma / SIGMA_SCALE, dtype=np.float32)
    return np.concatenate([img, smap], axis=1)


import onnxruntime as ort

import paths
sess = ort.InferenceSession(a.out, providers=["CPUExecutionProvider"])
worst = 0.0
rng = np.random.default_rng(0)
for trial in range(5):
    x = _random_tile(a.tile, a.tile, rng)
    with torch.no_grad():
        ref = net(torch.from_numpy(x)).numpy()
    got = sess.run(["noise"], {"input": x})[0]
    worst = max(worst, float(np.abs(ref - got).max()))
print(f"PyTorch vs ONNX, worst absolute difference over 5 random tiles: {worst:.3e}")
assert worst < 1e-5, "ONNX output does not match PyTorch — do NOT ship this"

# a non-square, non-multiple-of-8 size, because tiling at image edges will hit one
x = _random_tile(200, 328, rng)
try:
    got = sess.run(["noise"], {"input": x})[0]
    with torch.no_grad():
        ref = net(torch.from_numpy(x)).numpy()
    print(f"odd size 200x328 OK, diff {float(np.abs(ref-got).max()):.3e}")
except Exception as e:
    print(f"odd size 200x328 FAILS: {type(e).__name__}: {str(e)[:90]}")

meta = {"model": os.path.basename(a.out), "sensor": "s30", "run": os.path.basename(a.run),
        "epoch": int(ck.get("epoch", -1)), "val": float(ck.get("val", float("nan"))),
        "asinh_a": D._ASINH_A, "space": "linear, pre-stretch",
        "predicts": "noise residual; result = input - strength * noise",
        "trained_on": list(D.S30_TRAIN), "validated_on": list(D.S30_VAL),
        "held_out": list(D.S30_TEST), "tile": a.tile,
        "in_channels": 4, "sigma_scale": SIGMA_SCALE,
        "input_layout": "[R,G,B,sigma_map] -- sigma_map is estimate_sigma(image)/sigma_scale"}
with open(os.path.splitext(a.out)[0] + ".json", "w") as fh:
    json.dump(meta, fh, indent=2)
print("metadata:", json.dumps(meta))
