"""Training data for the Nocturne denoiser: tiles -> (noisy, clean, mask).

Lives OUTSIDE the `nocturne` package on purpose. Everything here imports torch,
and the shipped app must never depend on it — Nocturne gets an ONNX file and
onnxruntime, nothing more. `nocturne/training/pairs.py` is the other half and
stays inside the package because it drives the real stacking pipeline.
"""
from __future__ import annotations

import glob
import json
import os
import re
from dataclasses import dataclass, field

import numpy as np

from noise import estimate_sigma

# ---------------------------------------------------------------- transform

# A FIXED, image-independent nonlinearity. This is the whole reason the model
# is trained on linear pairs rather than stretched ones: `core.stretch` derives
# its parameters from each image's own median and MAD, so an 8-frame stack and
# a 128-frame stack get DIFFERENT transfer functions. Training on that teaches
# the model to undo a brightness mismatch as well as denoise, and it cannot
# reproduce the mapping at inference because it never sees the deep stack.
#
# asinh, because linear astro data is almost all background: on a real S30 tile
# the values run about 0.035-0.125, so a network trained under MSE on linear
# data spends its capacity on the handful of bright stars and ignores the sky,
# which is exactly where the noise the user complains about lives.
_ASINH_A = 0.01          # softening point; ~ the background level of a Seestar sub


def to_model_space(x: np.ndarray, a: float = _ASINH_A) -> np.ndarray:
    # float32 explicitly. np.arcsinh(1.0 / a) is a numpy FLOAT64 scalar, and
    # dividing a float32 array by it silently upcasts the whole array — which
    # MPS cannot execute at all, since Metal has no double precision.
    return (np.arcsinh(x / a) / np.arcsinh(1.0 / a)).astype(np.float32, copy=False)


def from_model_space(y: np.ndarray, a: float = _ASINH_A) -> np.ndarray:
    return (np.sinh(y * np.arcsinh(1.0 / a)) * a).astype(np.float32, copy=False)


# ---------------------------------------------------------------- splitting

# Split by TARGET, never by tile. Two tiles from the same nebula share its
# structure, so a random split lets the network memorise the scene and score
# beautifully on data it has effectively already seen. With six S30 targets
# there is exactly enough for one honest holdout.
# v2, 2026-08-22: M33, M45 and NGC7000 were sitting unused in the archive,
# excluded from the first generation run only by its --filter LP --exposure 10
# flags. Mixing IRCUT with LP and 20s with 10s is deliberate: the model predicts
# NOISE, which is a property of the sensor and the sky, not of the filter. Seeing
# both makes it harder to learn a filter-specific shortcut.
#
# NGC6888 stays the v1 reference holdout, so per-target metrics compare runs on
# exactly the same dark-sky test target and the only thing that moved is
# training data. NGC281 joins it rather than replacing it: the FITS site
# coordinates split this archive into Helsingborg (Bortle 6-7: NGC281, NGC7000)
# and Crete (Bortle 3-4: everything else), and until now BOTH val and test were
# dark-sky while most users are not. Task 2's combine-nights work exists
# precisely so NGC281's 46+63 frames form one 109-frame group and can serve as
# that light-polluted holdout -- a target that produces tiles but belongs to no
# split makes split_by_target raise, taking down train/evaluate/nightly.
S30_TRAIN = ("M16", "M17", "M8", "NGC6992", "M33", "M45", "NGC7000")
S30_VAL = ("M27",)
S30_TEST = ("NGC6888", "NGC281")   # untouched until the very end


@dataclass
class TileRef:
    path: str
    sensor: str
    target: str
    group: str
    input_count: int
    target_count: int
    # Defaults to "truth" so pairs built before the Noise2Noise work still load
    # -- and defaults to the kind whose loss (L1) those pairs were built for.
    kind: str = "truth"


def scan_tiles(root: str) -> list[TileRef]:
    """Every tile under a TrainingPairs root, tagged with the target it came from."""
    out: list[TileRef] = []
    for group in sorted(os.listdir(root)):
        m = re.match(r"(s30|s50)_([^_]+)_", group)
        if not m:
            continue
        sensor, target = m.groups()
        for pair_dir in sorted(glob.glob(os.path.join(root, group, "pair_*"))):
            man_path = os.path.join(pair_dir, "manifest.json")
            if not os.path.exists(man_path):
                continue
            with open(man_path) as fh:
                man = json.load(fh)
            if man.get("postprocess", {}).get("stretch_amount") is not None:
                raise ValueError(
                    f"{pair_dir} was generated WITH a stretch. Those pairs are unusable: "
                    "core.stretch derives its parameters per image, so the noisy and clean "
                    "sides received different transfer functions. Regenerate without --stretch."
                )
            pair = man["pair"]
            if not pair.get("disjoint"):
                raise ValueError(f"{pair_dir}: manifest does not claim disjoint frame sets")
            for tile in sorted(glob.glob(os.path.join(pair_dir, "tiles", "*.npz"))):
                out.append(TileRef(tile, sensor, target, group,
                                   pair["input_count"], pair["target_count"],
                                   pair.get("kind", "truth")))
    return out


def split_by_target(tiles: list[TileRef], sensor: str = "s30"):
    """(train, val, test), partitioned by target with no overlap anywhere."""
    sel = [t for t in tiles if t.sensor == sensor]
    train = [t for t in sel if t.target in S30_TRAIN]
    val = [t for t in sel if t.target in S30_VAL]
    test = [t for t in sel if t.target in S30_TEST]
    seen = {t.target for t in sel}
    unassigned = seen - set(S30_TRAIN) - set(S30_VAL) - set(S30_TEST)
    if unassigned:
        raise ValueError(f"targets not assigned to any split: {sorted(unassigned)}")
    for a, b, name in ((train, val, "train/val"), (train, test, "train/test"), (val, test, "val/test")):
        shared = {t.target for t in a} & {t.target for t in b}
        if shared:
            raise ValueError(f"{name} share targets: {shared}")
    return train, val, test


# ---------------------------------------------------------------- dataset

@dataclass
class DataConfig:
    crop: int = 256              # random crop from each 512 tile
    min_coverage: float = 0.98   # below this a pixel had fewer frames -> its
                                 # "clean" target is not actually clean, so it
                                 # must not contribute to the loss
    augment: bool = True
    asinh_a: float = _ASINH_A


class TileDataset:
    """(noisy, clean, mask) in model space, as CHW float32 torch tensors.

    The mask is the point of the coverage map. Tiles near the frame edge have
    pixels that only some frames reached — the 128-frame "clean" target there is
    really a 40-frame stack, so training against it teaches the model that noise
    is signal. Observed coverage on a real tile ran down to 0.59.
    """

    def __init__(self, tiles: list[TileRef], cfg: DataConfig, train: bool = True):
        # Deliberately does NOT hold a reference to the torch module. DataLoader
        # workers are spawned, not forked, on macOS, so the dataset is pickled —
        # and a module attribute makes that fail with "cannot pickle 'module'
        # object". Import inside __getitem__ instead: it is a sys.modules lookup,
        # and it keeps this file importable from the app venv, which has no torch.
        self.tiles, self.cfg, self.train = tiles, cfg, train
        if not tiles:
            raise ValueError("no tiles — check the split and the pairs root")

    def __len__(self) -> int:
        return len(self.tiles)

    def __getitem__(self, i: int):
        import torch
        rec = np.load(self.tiles[i].path)
        noisy, clean, cov = rec["input"], rec["target"], rec["coverage"]

        c = self.cfg.crop
        H, W = noisy.shape[:2]
        if self.train:
            y = np.random.randint(0, H - c + 1); x = np.random.randint(0, W - c + 1)
        else:
            y, x = (H - c) // 2, (W - c) // 2      # deterministic, so val loss is comparable
        noisy = noisy[y:y+c, x:x+c]; clean = clean[y:y+c, x:x+c]; cov = cov[y:y+c, x:x+c]

        if self.train and self.cfg.augment:
            # Flips and 90-degree rotations only. The sky has no preferred
            # orientation, but anything that RESAMPLES (small rotations, scaling)
            # would blur the noise we are trying to model.
            k = np.random.randint(4)
            if k: noisy, clean, cov = (np.rot90(a, k, (0, 1)) for a in (noisy, clean, cov))
            if np.random.rand() < 0.5:
                noisy, clean, cov = (a[:, ::-1] for a in (noisy, clean, cov))

        a = self.cfg.asinh_a
        noisy = to_model_space(np.ascontiguousarray(noisy, np.float32), a)
        clean = to_model_space(np.ascontiguousarray(clean, np.float32), a)
        mask = (np.ascontiguousarray(cov, np.float32) >= self.cfg.min_coverage).astype(np.float32)

        # Measured on THIS tile, after transform and augmentation -- a crop of
        # empty sky and a crop of a bright core genuinely differ in noise, and
        # that's exactly what the model is being told.
        sigma = estimate_sigma(noisy)

        # Carried per TILE rather than per batch, because a batch mixes tiles
        # from both kinds of pair and each one needs its own loss.
        is_n2n = 1.0 if self.tiles[i].kind == "n2n" else 0.0

        return (torch.from_numpy(noisy).permute(2, 0, 1),
                torch.from_numpy(clean).permute(2, 0, 1),
                torch.from_numpy(mask)[None],
                torch.tensor(sigma, dtype=torch.float32),
                torch.tensor(is_n2n, dtype=torch.float32))
