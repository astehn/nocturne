"""Precompute what the injection dataset generates from: one clean target and
four real noise fields per group.

The ladder builder next door plans WHICH (input, target) depths a group can
afford and stacks a separate pair for each. This one stacks nothing per depth
at all. It integrates a group's frames as two disjoint halves, four times over,
and keeps

    M = (A + B) / 2         the deepest target the group can make
    D = (A - B) / sqrt(2)   that camera's own noise, on that real field

Every training example is then `M + k*D` for a `k` chosen at sample time, so a
group yields any stack depth we ask for instead of the handful its frame count
could afford as real pairs. Five integrations per group replace the 171 pair
builds of the n2n_v2 dataset, and the dataset stops being files-per-depth.

Nothing here decides the noise LEVEL -- that is data.InjectionDataset's job,
per sample. This file only makes the ingredients.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from collections import namedtuple
from datetime import datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import build_dataset  # noqa: E402
from data import HELD_OUT  # noqa: E402  -- re-exported; the split rules live there
from noise import estimate_sigma  # noqa: E402
from nocturne.training.inject import noise_field, target_from_halves  # noqa: E402
from nocturne.training.pairs import (  # noqa: E402
    _tile_starts,
    discover_frame_groups,
    partition_pair,
    prepare_stack,
    scene_scale,
)

__all__ = ["HELD_OUT", "plan_groups", "build_group", "write_group_tiles",
           "build_injection"]

# Four fields, not one. `k` and the choice of field both vary per sample, so
# four independent draws of the same group's noise are what stop a tile's
# examples from being one noise pattern at several volumes -- the model would
# otherwise have four thousand chances to memorise one speckle map.
_N_FIELDS = 4

# A group needs two halves deep enough for sigma_clip to mean anything (it
# degrades to a plain mean below 3 frames), plus the registration reference,
# which belongs to neither half. 16 is build_dataset's own min_target: eight
# frames a side is the shallowest half this project already calls a stack.
_MIN_FRAMES = 16

_DEFAULT_SEED = 20260824


GroupTiles = namedtuple("GroupTiles", "target fields coverage depth half scale")


def plan_groups(groups, min_frames: int = _MIN_FRAMES):
    """The groups this build may use as training material.

    Three exclusions, each for its own reason: HELD_OUT because a model trained
    on those targets cannot be judged by them; mosaics because their frames do
    not share a canvas, so subtracting one half from the other leaves the SKY
    behind rather than the noise; and small groups because two halves of four
    frames each is not a stack.
    """
    kept = []
    for group in groups:
        if group.target_dir in HELD_OUT:
            continue
        if getattr(group, "mosaic", False):
            continue
        if len(group.frames) < min_frames:
            continue
        kept.append(group)
    return kept


def _split_seed(seed: int, slug: str, index: int) -> int:
    """Key each half-split on its own identity, never on a running ordinal --
    the same reason pairs._stable_seed exists. A resumed build that skipped
    three groups must still give split 2 of group four the same halves."""
    text = f"{seed}|{slug}|split{index}"
    return int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "little")


def build_group(prepared, available, *, n_fields: int = _N_FIELDS,
                seed: int = _DEFAULT_SEED, slug: str = "", method: str = "sigma_clip",
                kappa: float = 2.5, workers: int | None = None,
                on_line=None) -> GroupTiles:
    """One target and `n_fields` noise fields, from ONE prepared registration.

    `prepare_stack` runs once per group, outside this function, and every
    integration below reuses it. Registering per split would repeat the mistake
    fixed in 7ee26be and cost hours on the big groups -- M42 has 2361 frames.

    The target comes from split 0 only. All four splits average to the same
    full stack up to rounding, so taking a target per split would be four names
    for one image; the fields are what actually differ.
    """
    say = on_line or (lambda _msg: None)
    half = len(available) // 2
    if half < 1:
        raise ValueError(f"need at least 2 registered frames, got {len(available)}")

    fields: list[np.ndarray] = []
    target_raw: np.ndarray | None = None
    coverage: np.ndarray | None = None
    for index in range(n_fields):
        a, b = partition_pair(
            available, input_count=half, target_count=half,
            seed=_split_seed(seed, slug, index),
        )
        t0 = time.time()
        ra = prepared.integrate(a, method=method, kappa=kappa, workers=workers,
                                autocrop=False, label=f"{slug} split{index} A")
        rb = prepared.integrate(b, method=method, kappa=kappa, workers=workers,
                                autocrop=False, label=f"{slug} split{index} B")
        fields.append(noise_field(ra.data, rb.data))
        if index == 0:
            target_raw = target_from_halves(ra.data, rb.data)
        frac = (ra.coverage.astype(np.float32) + rb.coverage.astype(np.float32)) / (2 * half)
        coverage = frac if coverage is None else np.minimum(coverage, frac)
        say(f"    split {index}: 2x{half} frames, {time.time() - t0:.0f}s")

    # The ladder pairs' 0..1 convention, and the SAME divisor for the target and
    # every field -- to_model_space and asinh_a=0.01 assume it, and a field
    # scaled differently from its own target would inject noise of the wrong
    # size while looking entirely plausible.
    scale = scene_scale(target_raw)
    if not np.isfinite(scale) or scale <= 0:
        raise ValueError("target has no positive finite scale")
    target = np.clip(target_raw / scale, 0.0, 1.0).astype(np.float32)
    stacked = (np.stack(fields, axis=0) / scale).astype(np.float32)
    return GroupTiles(target=target, fields=stacked,
                      coverage=np.asarray(coverage, np.float32),
                      depth=2 * half, half=half, scale=float(scale))


def write_group_tiles(output_dir, tiles: GroupTiles, *, tile_size: int,
                      overlap: int, min_coverage: float) -> int:
    """Write this group's tiles and return how many. Same geometry as
    pairs.materialize_tiles, and the same coverage rule: a frame-edge pixel was
    reached by only some frames, so the target is not clean there."""
    if tile_size <= 0 or overlap < 0 or overlap >= tile_size:
        raise ValueError("tile_size must be positive and overlap must be smaller")
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    height, width = tiles.target.shape[:2]
    step = tile_size - overlap
    count = 0
    for y in _tile_starts(height, tile_size, step):
        for x in _tile_starts(width, tile_size, step):
            y1, x1 = min(y + tile_size, height), min(x + tile_size, width)
            cov = tiles.coverage[y:y1, x:x1]
            if float(np.mean(cov)) < min_coverage:
                continue
            np.savez_compressed(
                output / f"tile_{count:06d}.npz",
                target=tiles.target[y:y1, x:x1],
                fields=tiles.fields[:, y:y1, x:x1],
                coverage=cov.astype(np.float32),
                # The depth the target actually has, which is what turns a
                # requested stack depth into a sigma. The group's raw frame
                # count is NOT it: the reference frame and every registration
                # failure are already gone by here.
                depth=np.int32(tiles.depth),
                origin=np.asarray([y, x], dtype=np.int32),
            )
            count += 1
    return count


def injection_root(cfg: dict) -> Path:
    """Where this config's injection tiles live.

    A subdirectory of the ladder dataset, not a sibling: the two belong to one
    config, and `injection` does not match data.scan_tiles' group pattern, so
    manufactured tiles can never be picked up as real held-out pairs by the
    gate.
    """
    return build_dataset._DEFAULT_DATASET_ROOT / cfg["name"] / "injection"


def build_injection(cfg: dict, *, max_groups: int | None = None, on_line=print) -> dict:
    root = injection_root(cfg)
    root.mkdir(parents=True, exist_ok=True)

    source = cfg["source"]
    sensors = set(cfg.get("sensors") or [cfg.get("sensor")])
    combine_nights = bool(cfg.get("combine_nights", False))
    min_frames = int(cfg.get("injection_min_frames", _MIN_FRAMES))
    seed = int(cfg.get("seed", _DEFAULT_SEED))
    method = cfg.get("method", "sigma_clip")
    kappa = float(cfg.get("kappa", 2.5))
    workers = cfg.get("workers")
    n_fields = int(cfg.get("fields_per_group", _N_FIELDS))
    tile_size = int(cfg.get("tile_size", 512))
    tile_overlap = int(cfg.get("tile_overlap", 32))
    min_tile_coverage = float(cfg.get("min_tile_coverage", 0.9))

    groups = discover_frame_groups(source, sensor=None, min_frames=3,
                                   combine_nights=combine_nights)
    if None not in sensors:
        groups = [g for g in groups if g.sensor in sensors]
    planned = plan_groups(groups, min_frames=min_frames)
    if max_groups is not None:
        planned = planned[: max(0, int(max_groups))]

    on_line(f"{len(planned)} groups planned "
            f"({len(groups) - len(planned)} held out, mosaic, or too small)")
    for g in planned:
        on_line(f"  {g.slug:<46}{len(g.frames):>6} frames")

    manifest = {
        "format": "nocturne-injection-dataset-v1",
        "created_utc": datetime.now().astimezone().isoformat(),
        "config": cfg,
        "held_out": list(HELD_OUT),
        "groups": [],
    }
    for index, group in enumerate(planned, start=1):
        out_dir = root / group.slug
        if any(out_dir.glob("tile_*.npz")):
            on_line(f"[{index}/{len(planned)}] {group.slug}: already built, skipping")
            manifest["groups"].append({"group": group.slug, "status": "already_present"})
            continue
        on_line(f"[{index}/{len(planned)}] {group.slug}: {len(group.frames)} frames")
        try:
            paths = [f.path for f in group.frames]
            reference = paths[len(paths) // 2]
            t0 = time.time()
            prepared = prepare_stack(paths, reference, workers=workers)
            available = [p for p in prepared.available_paths if p != reference]
            on_line(f"    registered {len(available)}/{len(paths) - 1} "
                    f"({len(prepared.rejected)} rejected) in {time.time() - t0:.0f}s")
            tiles = build_group(prepared, available, n_fields=n_fields, seed=seed,
                                slug=group.slug, method=method, kappa=kappa,
                                workers=workers, on_line=on_line)
            written = write_group_tiles(out_dir, tiles, tile_size=tile_size,
                                        overlap=tile_overlap,
                                        min_coverage=min_tile_coverage)
            sigma_target = estimate_sigma(tiles.target)
            sigma_fields = [estimate_sigma(f) for f in tiles.fields]
            on_line(f"    depth {tiles.depth} (2 x {tiles.half}), "
                    f"sigma(target) {sigma_target:.5f}, "
                    f"sigma(fields) {', '.join(f'{s:.5f}' for s in sigma_fields)}, "
                    f"{written} tiles")
            manifest["groups"].append({
                "group": group.slug, "status": "generated",
                "target_dir": group.target_dir, "sensor": group.sensor,
                "frame_count": len(group.frames), "registered": len(available),
                "depth": tiles.depth, "half": tiles.half, "scale": tiles.scale,
                "sigma_target": sigma_target, "sigma_fields": sigma_fields,
                "tiles": written,
            })
        except Exception as exc:  # keep the remaining groups usable
            on_line(f"    FAILED: {type(exc).__name__}: {exc}")
            manifest["groups"].append({"group": group.slug, "status": "failed",
                                       "error": f"{type(exc).__name__}: {exc}"})

    (root / "injection_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    built = sum(1 for g in manifest["groups"] if g["status"] == "generated")
    failed = sum(1 for g in manifest["groups"] if g["status"] == "failed")
    on_line(f"\n{built} groups built, {failed} failed; manifest: "
            f"{root / 'injection_manifest.json'}")
    return manifest


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Precompute injection targets and noise fields per group.")
    p.add_argument("--config", required=True, help="path to a training config JSON")
    p.add_argument("--max-groups", type=int, default=None,
                   help="process at most N groups (smoke testing)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    cfg = json.loads(Path(args.config).read_text())
    manifest = build_injection(cfg, max_groups=args.max_groups)
    return 1 if any(g["status"] == "failed" for g in manifest["groups"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
