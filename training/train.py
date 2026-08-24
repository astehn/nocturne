"""Train the Nocturne denoiser.

Built around one requirement from Andreas: never start something that runs for
hours and fails silently. So:

  * --smoke runs the ENTIRE pipeline on a handful of tiles in seconds. If
    anything is broken, it breaks before you commit an evening.
  * every tile is opened and shape-checked BEFORE the first training step.
  * the config and the exact target split are printed up front, so a wrong
    split is visible immediately rather than after a night of work.
  * every epoch prints train loss, val loss, the denoising actually achieved,
    star-core error, seconds, and a real ETA.
  * a checkpoint is written every epoch and training is resumable; a crash at
    hour three costs one epoch.
  * sample crops are written as PNG so progress can be LOOKED at, not just read.
  * everything also goes to a log file, so a silent death leaves evidence.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict

import numpy as np
import torch
from torch.utils.data import DataLoader

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data as D
from model import DenoiseUNet
from noise import estimate_sigma


class Tee:
    """stdout and a log file, so an unattended run leaves a trace."""
    def __init__(self, path):
        self.f = open(path, "a", buffering=1)
    def write(self, s):
        sys.__stdout__.write(s); sys.__stdout__.flush(); self.f.write(s)
    def flush(self):
        sys.__stdout__.flush(); self.f.flush()


def masked_l1(pred, target, mask):
    m = mask.expand_as(pred)
    denom = m.sum().clamp(min=1.0)
    return ((pred - target).abs() * m).sum() / denom


def masked_l2(pred, target, mask):
    m = mask.expand_as(pred)
    denom = m.sum().clamp(min=1.0)
    return (((pred - target) ** 2) * m).sum() / denom


def _per_sample(err, mask):
    m = mask.expand_as(err)
    denom = m.sum(dim=(1, 2, 3)).clamp(min=1.0)
    return (err * m).sum(dim=(1, 2, 3)) / denom


def selected_loss(pred, target, mask, is_n2n):
    """L1 for truth pairs, L2 for Noise2Noise pairs, chosen per sample.

    L1's minimiser is the conditional median; Noise2Noise's unbiasedness
    argument requires the conditional MEAN, i.e. L2 -- see
    test_train_loss.py::test_l2_recovers_the_mean_and_l1_recovers_the_median
    for the demonstration. Truth pairs keep L1 because it is what ladder_v1
    was trained under and it holds fine detail well; whether they would also
    do better under L2 is an open measurement, not an assumption baked in
    here.

    Reduced per sample first, so a mixed batch does not let one kind's
    magnitude dominate the other's gradient.
    """
    l1 = _per_sample((pred - target).abs(), mask)
    l2 = _per_sample((pred - target) ** 2, mask)
    return torch.where(is_n2n > 0.5, l2, l1).mean()


@torch.no_grad()
def evaluate(model, loader, device):
    """Validation numbers that MEAN something.

    `denoised` is the fraction of the input's error that survives: 1.00 means
    the model did nothing, 0.00 means it reproduced the deep stack exactly.
    Loss alone cannot tell you that. `star_err` is the same error restricted to
    the brightest 1% of pixels, because a model that scores well overall while
    eating star cores is the failure this project has already been bitten by.
    """
    model.eval()
    tot = res = base = star_a = star_b = n = 0.0
    for noisy, clean, mask, sigma, _is_n2n in loader:
        noisy, clean, mask = noisy.to(device), clean.to(device), mask.to(device)
        sigma = sigma.to(device)
        out = model.denoise(noisy, sigma, 1.0)
        tot += masked_l1(out, clean, mask).item()
        m = mask.expand_as(clean)
        res += (((out - clean).abs()) * m).sum().item()
        base += (((noisy - clean).abs()) * m).sum().item()
        thr = torch.quantile(clean.flatten(), 0.99)
        bright = (clean >= thr) & (m > 0)
        if bright.any():
            star_a += ((out - clean).abs()[bright]).sum().item()
            star_b += ((noisy - clean).abs()[bright]).sum().item()
        n += 1
    model.train()
    return (tot / max(n, 1),
            res / max(base, 1e-12),
            star_a / max(star_b, 1e-12))


def save_samples(model, dataset, device, path, count=3):
    """Write noisy | denoised | clean strips as PNG, so progress is visible."""
    from PIL import Image
    model.eval()
    rows = []
    with torch.no_grad():
        for i in range(min(count, len(dataset))):
            noisy, clean, _, sigma, _ = dataset[i]
            out = model.denoise(noisy[None].to(device), sigma.to(device), 1.0)[0].cpu()
            strip = torch.cat([noisy, out.clamp(0, 1), clean], dim=2)
            rows.append((strip.permute(1, 2, 0).numpy() * 255).clip(0, 255).astype(np.uint8))
    model.train()
    Image.fromarray(np.concatenate(rows, axis=0)).save(path)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", default="/Volumes/Work2/Images/Astro/TrainingPairs")
    ap.add_argument("--out", default="/Volumes/Work2/Images/Astro/denoise_runs/s30_v1")
    # Two different things: --sensor names the RUN and the model Nocturne
    # ships (denoise_s30_v1 -- the S30 Pro is the camera the app targets),
    # while --sensors is the material trained on. The S50 groups are the
    # deep ones, so widening the material is the whole point; widening the
    # model name is not.
    ap.add_argument("--sensor", default="s30")
    ap.add_argument("--sensors", default=",".join(D.TRAINING_SENSORS),
                    help="comma-separated sensors whose tiles feed training")
    # Where a training PAIR comes from. "tiles" loads the ladder's real pairs;
    # "injection" manufactures them per sample from a clean target and that
    # camera's own noise (see data.InjectionDataset). Defaulting to "tiles"
    # keeps every existing config meaning exactly what it meant.
    ap.add_argument("--dataset", default="tiles", choices=("tiles", "injection"))
    ap.add_argument("--injection-tiles", default=None,
                    help="root of the injection tiles; default <pairs>/injection")
    ap.add_argument("--epochs", type=int, default=300)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--crop", type=int, default=256)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--base", type=int, default=32)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--sample-every", type=int, default=5)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--smoke", action="store_true",
                    help="whole pipeline on a few tiles, seconds — run this FIRST")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    sys.stdout = Tee(os.path.join(args.out, "train.log"))
    dev = torch.device("mps" if torch.backends.mps.is_available() else "cpu")

    print("=" * 74)
    print(f"Nocturne denoiser — {args.sensor}   {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 74)

    sensors = D.parse_sensors(args.sensors)
    injection = args.dataset == "injection"
    if injection:
        root = args.injection_tiles or os.path.join(args.pairs, "injection")
        train_t, val_t = D.split_injection_tiles(D.scan_injection_tiles(root), sensors)
        test_t = []
    else:
        tiles = D.scan_tiles(args.pairs)
        train_t, val_t, test_t = D.split_by_target(tiles, sensors)
    if args.smoke:
        train_t, val_t = train_t[:16], val_t[:8]
        args.epochs = 2

    def targets(ts): return ", ".join(sorted({t.target for t in ts})) or "(none)"
    print(f"device        : {dev}")
    print(f"dataset       : {args.dataset}"
          + (f"   {root}" if injection else ""))
    print(f"train         : {len(train_t):>5} tiles   {targets(train_t)}")
    print(f"val           : {len(val_t):>5} tiles   {targets(val_t)}")
    print(f"test (unseen) : {len(test_t):>5} tiles   {targets(test_t)}   <- NOT touched here")
    if injection:
        # The depth EACH GROUP's target actually has -- the ceiling on what it
        # can be asked to imitate, since the dataset never claims a stack
        # deeper than half of it.
        print(f"held out      : {', '.join(D.HELD_OUT)}   <- never training material")
    else:
        depths = sorted({(t.input_count, t.target_count) for t in train_t})
        print(f"depths        : {', '.join(f'{a}->{b}' for a, b in depths)}")
    print(f"crop {args.crop}  batch {args.batch}  lr {args.lr}  base {args.base}  epochs {args.epochs}")

    # Fail fast: touch every tile before committing hours to the run.
    print("\nchecking every tile opens and has the right shape...", end="", flush=True)
    t0 = time.time()
    for t in train_t + val_t:
        with np.load(t.path) as r:
            if injection:
                # A target that measures no noise at all cannot be asked for a
                # depth -- and would otherwise raise inside a DataLoader worker
                # mid-epoch, hours in, where the traceback is hardest to read.
                if r["target"].ndim != 3 or r["fields"].ndim != 4:
                    raise SystemExit(f"\nBAD TILE {t.path}: "
                                     f"{r['target'].shape} / {r['fields'].shape}")
                if int(r["depth"]) < 2 or not estimate_sigma(r["target"]) > 0:
                    raise SystemExit(f"\nBAD TILE {t.path}: depth {int(r['depth'])}, "
                                     f"sigma {estimate_sigma(r['target']):.6f}")
            elif r["input"].shape != r["target"].shape or r["input"].ndim != 3:
                raise SystemExit(f"\nBAD TILE {t.path}: {r['input'].shape} vs {r['target'].shape}")
    print(f" all {len(train_t)+len(val_t)} OK ({time.time()-t0:.0f}s)")

    cfg = D.DataConfig(crop=args.crop)
    if injection:
        ds_tr = D.InjectionDataset([t.path for t in train_t], cfg, train=True)
        ds_va = D.InjectionDataset([t.path for t in val_t], cfg, train=False)
    else:
        ds_tr = D.TileDataset(train_t, cfg, train=True)
        ds_va = D.TileDataset(val_t, cfg, train=False)
    dl_tr = DataLoader(ds_tr, batch_size=args.batch, shuffle=True,
                       num_workers=args.workers, drop_last=True, persistent_workers=args.workers > 0)
    dl_va = DataLoader(ds_va, batch_size=args.batch, shuffle=False, num_workers=args.workers,
                       persistent_workers=args.workers > 0)

    model = DenoiseUNet(base=args.base).to(dev)
    print(f"parameters    : {sum(p.numel() for p in model.parameters()):,}")
    opt = torch.optim.Adam(model.parameters(), lr=args.lr)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=args.epochs)

    start, best = 0, float("inf")
    ck = os.path.join(args.out, "last.pt")
    if args.resume and os.path.exists(ck):
        st = torch.load(ck, map_location=dev)
        model.load_state_dict(st["model"]); opt.load_state_dict(st["opt"])
        start, best = st["epoch"] + 1, st.get("best", float("inf"))
        print(f"resumed from epoch {start}")

    with open(os.path.join(args.out, "config.json"), "w") as fh:
        json.dump({**vars(args), "data": asdict(cfg),
                   "dataset": args.dataset,
                   "split": {"train": sorted({t.target for t in train_t}),
                             "val": sorted({t.target for t in val_t}),
                             "test": sorted({t.target for t in test_t})}}, fh, indent=2)

    print(f"\n{'epoch':>6} {'train':>9} {'val':>9} {'denoised':>9} {'star_err':>9} "
          f"{'sigma range':>15} {'sec':>6} {'ETA':>9}")
    print("-" * 74)
    t_start = time.time()
    for ep in range(start, args.epochs):
        te = time.time(); run = n = 0
        sig_min, sig_max = float("inf"), float("-inf")
        for noisy, clean, mask, sigma, is_n2n in dl_tr:
            noisy, clean, mask = noisy.to(dev), clean.to(dev), mask.to(dev)
            sigma = sigma.to(dev)
            is_n2n = is_n2n.to(dev)
            sig_min = min(sig_min, sigma.min().item())
            sig_max = max(sig_max, sigma.max().item())
            loss = selected_loss(model.denoise(noisy, sigma, 1.0), clean, mask, is_n2n)
            opt.zero_grad(); loss.backward(); opt.step()
            run += loss.item(); n += 1
        sched.step()
        vl, denoised, star = evaluate(model, dl_va, dev)
        dt = time.time() - te
        eta = (args.epochs - ep - 1) * (time.time() - t_start) / (ep - start + 1)
        # Printed every epoch, not just once, because a distribution that
        # collapses to a near-constant mid-training (e.g. a bad batch order,
        # or a bug that stops sigma from varying) means the fourth channel has
        # stopped carrying information -- that must be visible, not silent.
        sig_range = f"{sig_min:.4f}-{sig_max:.4f}"
        print(f"{ep:>6} {run/max(n,1):>9.5f} {vl:>9.5f} {denoised:>9.3f} {star:>9.3f} "
              f"{sig_range:>15} {dt:>6.0f} {time.strftime('%H:%M:%S', time.gmtime(eta)):>9}")

        torch.save({"model": model.state_dict(), "opt": opt.state_dict(),
                    "epoch": ep, "best": best, "args": vars(args)}, ck)
        if vl < best:
            best = vl
            torch.save({"model": model.state_dict(), "epoch": ep, "val": vl,
                        "args": vars(args)}, os.path.join(args.out, "best.pt"))
        if args.sample_every and ep % args.sample_every == 0:
            save_samples(model, ds_va, dev, os.path.join(args.out, f"sample_ep{ep:04d}.png"))

    print("-" * 74)
    print(f"done in {time.strftime('%H:%M:%S', time.gmtime(time.time()-t_start))}, best val {best:.5f}")
    print(f"artifacts in {args.out}")


if __name__ == "__main__":
    main()
