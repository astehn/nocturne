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
import sys
from dataclasses import dataclass, field

import numpy as np

# The repo root, so `nocturne.training.inject` is importable from here.
# build_dataset.py and realism.py add it themselves because they are scripts;
# this module is a LIBRARY, and train.py -- which imports it -- puts only
# `training/` on the path. Without this line InjectionDataset dies on its first
# batch, inside a DataLoader worker, where the traceback is hardest to read.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from noise import estimate_sigma  # noqa: E402

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

# v3, 2026-08-24: the S50 half of the archive. n2n_v1 trained on 29% of what is
# on the drive -- 5596 of 8408 frames are S50 and were excluded outright -- and
# the S50 groups are the DEEP ones (M42 2361 frames, SH2-142 1357, NGC7023
# 821), which is exactly the range where the model's measured benefit decays to
# nothing. Andreas' ruling (2026-08-23): "different sensors and different FOV
# but still a Seestar".
#
# NGC7023 is val, not train, on purpose: 821 frames give it deep rungs
# (128/256/512/756), so it is the first deep validation signal this project has
# ever had. Everything before now validated on shallow stacks only.
#
# S30_TEST is deliberately NOT extended. It is the untouched holdout, and
# adding to it would move the baseline every per-target metric is compared
# against.
S50_TRAIN = ("M42", "SH2-142", "NGC6995", "M101")
S50_VAL = ("NGC7023",)
S50_TEST = ()

# Never training material, in ANY dataset this project builds.
#
# M8 and M45 are Andreas' own masters and the only honest tests this project
# has: a model that trained on them could not be judged by them, and every
# conclusion of the 2026-08-24 postmortem rests on that separation. NGC6888 and
# NGC281 are the do-no-harm gate's held-out pairs -- the one thing standing
# between an unattended run and the model the app ships.
#
# Deliberately NOT the same as S30_TEST: the ladder dataset trains on M8 and
# M45 tiles (S30_TRAIN), which is exactly the exposure the injection path must
# not repeat. Kept here rather than in build_injection.py because this is where
# the project's split rules already live.
HELD_OUT = ("M8", "M45", "NGC6888", "NGC281")

# The sensors whose tiles feed training. NOT the sensor the model ships as:
# Nocturne targets the S30 Pro and the exported model is still denoise_s30_v1.
# Only the training MATERIAL widens.
TRAINING_SENSORS = ("s30", "s50")

# Targets that are different catalogue numbers for the same patch of sky, and
# so must never land in different splits. Names alone cannot catch this.
# NGC6992 (S30) and NGC6995 (S50) are both the Eastern Veil: their FITS
# pointings are 314.350/+31.941 and 314.446/+31.486, 0.46 degrees apart, well
# inside a single Seestar frame (the S30 Pro's long axis is about 1.3 degrees).
# Scoring the model on one after training on the other would be scoring it on
# sky it had already memorised.
SAME_SKY = (("NGC6992", "NGC6995"),)


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


def parse_sensors(value) -> tuple[str, ...]:
    """A sensor list from a CLI flag ("s30,s50") or a config list."""
    if isinstance(value, str):
        value = value.split(",")
    return tuple(str(v).strip() for v in value if str(v).strip())


def _split_name(target: str) -> str | None:
    """Which split a target belongs to, or None. Reads the module globals on
    every call so a test can move a target and see the guards react."""
    for name, members in (("train", set(S30_TRAIN) | set(S50_TRAIN)),
                          ("val", set(S30_VAL) | set(S50_VAL)),
                          ("test", set(S30_TEST) | set(S50_TEST))):
        if target in members:
            return name
    return None


def split_by_target(tiles: list[TileRef], sensors: str | tuple[str, ...] = "s30"):
    """(train, val, test), partitioned by target with no overlap anywhere.

    ``sensors`` takes one sensor or several. It defaults to the historical
    single "s30" so an un-updated caller keeps its old behaviour rather than
    silently widening; the real callers pass TRAINING_SENSORS.
    """
    wanted = {sensors} if isinstance(sensors, str) else set(sensors)
    for region in SAME_SKY:
        homes = {t: _split_name(t) for t in region}
        distinct = {s for s in homes.values() if s is not None}
        if len(distinct) > 1:
            raise ValueError(
                f"these are the same sky and must share one split: {homes}")
    train_targets = set(S30_TRAIN) | set(S50_TRAIN)
    val_targets = set(S30_VAL) | set(S50_VAL)
    test_targets = set(S30_TEST) | set(S50_TEST)
    sel = [t for t in tiles if t.sensor in wanted]
    train = [t for t in sel if t.target in train_targets]
    val = [t for t in sel if t.target in val_targets]
    test = [t for t in sel if t.target in test_targets]
    seen = {t.target for t in sel}
    unassigned = seen - train_targets - val_targets - test_targets
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


# ------------------------------------------------- the generating dataset

# The depth mixture. Not one distribution: "log-uniform, weighted towards the
# deep end" would be two contradictory instructions.
#
# Which examples dominate is the whole game, and it is what sank both previous
# runs in opposite directions. s30_v2 trained mostly on shallow stacks (85% of
# n2n_v1's tiles had an input below 128 frames) and over-corrected until it
# damaged a real 405-frame master; n2n_v2 trained mostly on deep, already-clean
# targets and learned to do nothing, removing 55% of the noise on M45 where
# GraXpert removes 85%. So the proportion is named, not buried: 200-500 frames
# is the range Andreas' own masters occupy, and the shallow tail is there so a
# newcomer's 30-frame stack still works.
#
# A STARTING POINT, and the first thing to vary if the model comes out timid or
# aggressive -- which is why it is one number in one place.
#
# MEASURED, 2026-08-24, and it is NOT what comes out the other end. Weighted by
# each group's expected tile count over the 12 groups this archive plans, the
# REALISED depth of a training sample is:
#
#     1-16   6.2% | 16-64  13.0% | 64-128  54.2%
#     128-200 11.3% | 200-300 10.5% | 300-500  4.9%     median 107 frames
#
# The 70% asked for at 200-500 arrives as 15%. The cause is _MAX_DEPTH_FRACTION
# below meeting the shape of the archive: the six S30 groups are 76% of all
# tiles (a 3840x2160 frame holds 29 usable tiles against the S50's 9) and their
# targets are 162-364 frames deep, so their ceilings are 81-182 and every deep
# draw lands on one. Only M42, SH2-142, NGC7023 and NGC6995 -- all S50 -- can
# honestly reach 200+, and they are outnumbered 3:1.
#
# Left as it is, deliberately: the alternative is claiming depths the group's
# own frames cannot back. But it means the deep end is taught mostly by S50
# material, and it is the first thing to look at if the model comes out timid.
_DEEP_BAND = (200, 500)
_SHALLOW_BAND = (8, 200)
_DEEP_SHARE = 0.70

# The deepest stack a group may be asked to imitate, as a fraction of its own
# target's depth.
#
# At exactly half, `target + k*field` IS a real half-stack of that group (k
# works out to 1/sqrt(2)), so this is the deepest claim the group's own noise
# field actually backs. It also guarantees every example's input is at least
# sqrt(2) noisier than its target. Above it the lesson thins towards a target
# no cleaner than the input, which is precisely the emptiness this design
# exists to fix -- a 366-frame group cannot teach anything useful about a
# 350-frame stack, and pretending otherwise is how the last run went timid.
_MAX_DEPTH_FRACTION = 0.5

# Validation must not redraw its depth every epoch: train.py keeps the best
# checkpoint by val loss, and a val set that moves makes "best" mean "luckiest".
# Keyed per tile index, so val still spans the mixture instead of one depth.
_VAL_SEED = 20260824


def _log_uniform(rng, lo: int, hi: int) -> int:
    return int(round(float(np.exp(rng.uniform(np.log(lo), np.log(hi))))))


def _clamp_depth(depth: int, tile_depth: int) -> int:
    """The requested depth, held to what this tile's own frames can back."""
    return max(1, min(int(depth), max(1, int(tile_depth * _MAX_DEPTH_FRACTION))))


class InjectionDataset:
    """Training pairs manufactured per sample, not loaded from disk.

    Each tile carries one clean target `M` (a `depth`-frame stack) and four
    real noise fields `D` built by cancelling the sky between two disjoint
    half-stacks -- see nocturne/training/inject.py and build_injection.py. A
    sample is `M + k*D` with `k` solved so the result measures the noise of a
    stack of the depth we asked for. The same tile therefore yields a different
    lesson every epoch, which is why the dataset is a generator and the ladder's
    files-per-depth are gone.

    Returns TileDataset's exact 5-tuple with `is_n2n = 0.0`: the target here is
    genuinely cleaner than the input, so these are ordinary supervised pairs and
    train.py's existing selection routes them to L1. L2 exists for Noise2Noise's
    conditional mean and is not what they need.
    """

    def __init__(self, tiles: list[str], cfg: DataConfig, train: bool = True):
        # Paths, not arrays, and no module reference -- DataLoader workers are
        # spawned on macOS and the dataset is pickled. Same reason as
        # TileDataset; see its note.
        self.tiles, self.cfg, self.train = list(tiles), cfg, train
        if not self.tiles:
            raise ValueError("no injection tiles — run build_injection.py first")

    def __len__(self) -> int:
        return len(self.tiles)

    def sample_depth(self, rng=None) -> int:
        """A stack depth in frames, drawn from the mixture above."""
        rng = np.random if rng is None else rng
        lo, hi = _DEEP_BAND if rng.random() < _DEEP_SHARE else _SHALLOW_BAND
        return _log_uniform(rng, lo, hi)

    def __getitem__(self, i: int):
        import torch

        from nocturne.training.inject import inject, scale_for_sigma

        rng = np.random if self.train else np.random.default_rng(_VAL_SEED + i)
        with np.load(self.tiles[i]) as rec:
            target, fields = rec["target"], rec["fields"]
            cov, tile_depth = rec["coverage"], int(rec["depth"])

        c = self.cfg.crop
        H, W = target.shape[:2]
        if self.train:
            y = rng.randint(0, H - c + 1) if hasattr(rng, "randint") else int(rng.integers(0, H - c + 1))
            x = rng.randint(0, W - c + 1) if hasattr(rng, "randint") else int(rng.integers(0, W - c + 1))
        else:
            y, x = (H - c) // 2, (W - c) // 2      # deterministic, so val loss is comparable
        which = int(rng.integers(len(fields))) if hasattr(rng, "integers") else rng.randint(len(fields))
        target = target[y:y+c, x:x+c]
        field = fields[which][y:y+c, x:x+c]
        cov = cov[y:y+c, x:x+c]

        if self.train and self.cfg.augment:
            # Applied to the target and its field TOGETHER. D carries
            # signal-dependent shot noise measured on those exact intensities;
            # rotating one and not the other lays bright-pixel noise over dark
            # sky, leaving every shape and every summary statistic intact.
            # Flips and 90-degree rotations only -- anything that RESAMPLES
            # would blur the very noise being modelled.
            k = rng.randint(4) if hasattr(rng, "randint") else int(rng.integers(4))
            if k:
                target, field, cov = (np.rot90(a, k, (0, 1)) for a in (target, field, cov))
            if rng.random() < 0.5:
                target, field, cov = (a[:, ::-1] for a in (target, field, cov))

        target = np.ascontiguousarray(target, np.float32)
        field = np.ascontiguousarray(field, np.float32)

        # depth -> sigma by the sqrt(n) law, off the target's OWN measured
        # noise: this crop is a `tile_depth`-frame stack, so an n-frame one
        # carries sqrt(tile_depth / n) times as much. Then solve for k
        # numerically against the same estimator the app uses at inference --
        # estimate_sigma is a MAD over a masked high-pass, not a closed form.
        depth = _clamp_depth(self.sample_depth(rng), tile_depth)
        floor = estimate_sigma(target)
        if not floor > 0:
            raise ValueError(
                f"{self.tiles[i]}: the target crop measures no noise at all, so "
                "no depth can be asked of it — the tile is empty or clipped")
        k = scale_for_sigma(field, floor * float(np.sqrt(tile_depth / depth)),
                            estimate_sigma, base=target)
        noisy = np.clip(inject(target, field, k), 0.0, 1.0)

        a = self.cfg.asinh_a
        noisy = to_model_space(noisy, a)
        clean = to_model_space(target, a)
        mask = (np.ascontiguousarray(cov, np.float32) >= self.cfg.min_coverage).astype(np.float32)
        sigma = estimate_sigma(noisy)

        return (torch.from_numpy(noisy).permute(2, 0, 1),
                torch.from_numpy(clean).permute(2, 0, 1),
                torch.from_numpy(mask)[None],
                torch.tensor(sigma, dtype=torch.float32),
                torch.tensor(0.0, dtype=torch.float32))


# ------------------------------------------------- the injection split

# The injection path's own validation target. Deliberately NOT S30_VAL/S50_VAL:
# NGC7023 validates the ladder because 821 frames give it deep RUNGS, but here
# that same depth is what makes it one of only three groups able to supply a
# genuinely clean TARGET -- so it moves into training and M27 validates alone.
INJECTION_VAL = ("M27",)


@dataclass
class InjectionTileRef:
    path: str
    sensor: str
    target: str
    group: str


def scan_injection_tiles(root: str) -> list[InjectionTileRef]:
    """Every tile build_injection.py wrote under an injection root."""
    out: list[InjectionTileRef] = []
    for group in sorted(os.listdir(root)):
        m = re.match(r"(s30|s50)_([^_]+)_", group)
        if not m:
            continue
        sensor, target = m.groups()
        for tile in sorted(glob.glob(os.path.join(root, group, "tile_*.npz"))):
            out.append(InjectionTileRef(tile, sensor, target, group))
    return out


def split_injection_tiles(tiles: list[InjectionTileRef],
                          sensors: str | tuple[str, ...] = TRAINING_SENSORS):
    """(train, val) for the injection path, by target.

    The held-out check is the second line of defence, not the first:
    build_injection refuses to BUILD those targets. But a directory copied in
    by hand or a renamed group would otherwise put Andreas' own test masters
    into training, and nothing downstream would notice -- the model would still
    train, still pass its gate, and still be judged on sky it had memorised.
    """
    wanted = {sensors} if isinstance(sensors, str) else set(sensors)
    held = sorted({t.target for t in tiles} & set(HELD_OUT))
    if held:
        raise ValueError(
            f"held-out targets found in the injection tiles: {', '.join(held)}. "
            "These are the only honest tests this project has; a model trained "
            "on them cannot be judged by them.")
    sel = [t for t in tiles if t.sensor in wanted]
    val = [t for t in sel if t.target in INJECTION_VAL]
    train = [t for t in sel if t.target not in INJECTION_VAL]
    if not train:
        raise ValueError("no injection tiles left for training — check the "
                         "sensor filter and that build_injection.py has run")
    if not val:
        raise ValueError(
            f"no injection tiles for validation ({', '.join(INJECTION_VAL)}) — "
            "without them 'best checkpoint' means nothing")
    return train, val
