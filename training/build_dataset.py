"""Turn a raw Seestar archive into a ladder of noisy/clean training pairs.

Lives OUTSIDE the `nocturne` package (see data.py's docstring) but drives
`nocturne.training.pairs`, which does the actual registration and stacking --
this file only plans WHICH (input, target) depths a group can afford and
records what noise reduction each pair actually achieved.

The ladder exists because a model trained only on 8-frame inputs damages a
400-frame master: it learns a correction sized for noise that a deep stack
does not have. Depths in the config span shallow to deep so the model sees
"already fairly clean" inputs too.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
from astropy.io import fits

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from noise import estimate_sigma  # noqa: E402
from nocturne.training.pairs import (  # noqa: E402
    PairConfig,
    discover_frame_groups,
    generate_training_pairs,
)

_DEFAULT_DATASET_ROOT = Path("/Volumes/Work2/Images/Astro/denoise/datasets")


def plan_ladder(
    n_frames: int,
    depths: list[int],
    min_ratio: float = 4.0,
    min_target: int = 16,
) -> list[tuple[int, int]]:
    """(input, target) depths this group can afford, by increasing input depth.

    One frame is always reserved as the registration reference and belongs to
    neither side; input and target must be disjoint. min_ratio exists because a
    256->300 pair has a noise ratio of 1.08 and teaches almost nothing -- the
    target has to be genuinely cleaner to be a target at all.

    min_target is a separate floor UNDER min_ratio: on a small group, a 1-frame
    input against a 4-frame target clears min_ratio=4.0 on paper, but a 4-frame
    stack is still mostly noise -- training against it would teach the model
    that noise is signal. 16 is the shallowest depth this project treats as a
    usable "clean" reference at all, independent of what ratio it happens to
    hit against a particular input.
    """
    out: list[tuple[int, int]] = []
    for n_in in sorted(depths):
        budget = n_frames - n_in - 1
        if budget < n_in:
            continue
        n_tgt = min(budget, max(depths))
        if n_tgt < min_target:
            continue
        if n_tgt < n_in * min_ratio:
            continue
        out.append((n_in, n_tgt))
    return out


def _pair_dir(dataset_dir: Path, group_slug: str, pair_index: int, n_in: int, n_tgt: int) -> Path:
    # Must match nocturne.training.pairs._write_pair's naming exactly, or the
    # resumability check below can never find a pair that generate_training_pairs
    # would recognise as already written.
    return dataset_dir / group_slug / f"pair_{pair_index:04d}_in{n_in}_target{n_tgt}"


def _read_pair_channel(path: Path) -> np.ndarray:
    with fits.open(path) as hdul:
        data = np.asarray(hdul[0].data, dtype=np.float32)
    # save_fits stores colour channels-first (C, H, W); estimate_sigma wants
    # channels-last, the same convention core/image.py uses everywhere else.
    if data.ndim == 3:
        data = np.transpose(data, (1, 2, 0))
    return data


def _noise_record(pair_dir: Path, n_in: int, n_tgt: int, status: str) -> dict:
    noisy = _read_pair_channel(pair_dir / "input.fits")
    clean = _read_pair_channel(pair_dir / "target.fits")
    sigma_in = estimate_sigma(noisy)
    sigma_tgt = estimate_sigma(clean)
    # Achieved ratio is MEASURED (sigma_in / sigma_tgt on the frames that were
    # actually written), not the theoretical sqrt(n_tgt / n_in). Frames get
    # dropped during registration and sky normalisation reweights each frame's
    # contribution, so the theoretical count-based ratio is an assumption, not
    # a fact about the pair on disk -- and noise.py's own docstring is explicit
    # that training and inference must be told the same, real, measured number.
    # The theoretical figure is kept alongside it purely as a sanity check.
    achieved_ratio = (sigma_in / sigma_tgt) if sigma_tgt > 0 else None
    return {
        "pair_dir": str(pair_dir),
        "status": status,
        "input_count": n_in,
        "target_count": n_tgt,
        "sigma_input": sigma_in,
        "sigma_target": sigma_tgt,
        "achieved_noise_ratio": achieved_ratio,
        "theoretical_noise_ratio": math.sqrt(n_tgt / n_in),
    }


def _pairs_fully_present(dataset_dir: Path, group_slug: str, n_in: int, n_tgt: int, pairs_per_depth: int) -> bool:
    return all(
        (_pair_dir(dataset_dir, group_slug, i, n_in, n_tgt) / "manifest.json").is_file()
        for i in range(pairs_per_depth)
    )


def build_dataset(cfg: dict, *, max_groups: int | None = None, on_line=print) -> dict:
    dataset_dir = _DEFAULT_DATASET_ROOT / cfg["name"]
    dataset_dir.mkdir(parents=True, exist_ok=True)

    depths = list(cfg["depths"])
    min_ratio = float(cfg.get("min_ratio", 4.0))
    min_target = int(cfg.get("min_target", 16))
    pairs_per_depth = int(cfg.get("pairs_per_depth", 2))
    combine_nights = bool(cfg.get("combine_nights", False))
    exclude_mosaics = bool(cfg.get("exclude_mosaics", True))
    min_frames = int(cfg.get("min_frames", 3))
    seed = int(cfg.get("seed", 20260821))
    method = cfg.get("method", "average")
    kappa = float(cfg.get("kappa", 2.5))
    workers = cfg.get("workers")
    write_tiles = bool(cfg.get("tiles", False))
    tile_size = int(cfg.get("tile_size", 512))
    tile_overlap = int(cfg.get("tile_overlap", 32))
    min_tile_coverage = float(cfg.get("min_tile_coverage", 0.9))

    groups = discover_frame_groups(
        cfg["source"],
        sensor=cfg.get("sensor"),
        min_frames=min_frames,
        combine_nights=combine_nights,
    )
    if exclude_mosaics:
        groups = [g for g in groups if not g.mosaic]
    if max_groups is not None:
        groups = groups[: max(0, int(max_groups))]

    dataset_manifest = {
        "format": "nocturne-denoise-dataset-v1",
        "created_utc": datetime.now().astimezone().isoformat(),
        "config": cfg,
        "min_target": min_target,
        "groups": [],
    }
    summary = defaultdict(int)

    processed_slugs: set[str] = set()
    for index, group in enumerate(groups, start=1):
        if group.slug in processed_slugs:
            continue
        ladder = plan_ladder(len(group.frames), depths, min_ratio, min_target)
        on_line(
            f"[{index}/{len(groups)}] {group.slug} ({len(group.frames)} frames): "
            + (", ".join(f"{n_in}->{n_tgt}" for n_in, n_tgt in ladder) if ladder else "no valid pairs, skipped")
        )
        processed_slugs.add(group.slug)
        summary["groups_seen"] += 1
        if not ladder:
            summary["groups_skipped_too_small"] += 1
            continue

        by_target: dict[int, list[int]] = defaultdict(list)
        for n_in, n_tgt in ladder:
            by_target[n_tgt].append(n_in)

        group_pairs: list[dict] = []
        for n_tgt in sorted(by_target, reverse=True):
            n_ins = sorted(by_target[n_tgt])
            need = [
                n_in for n_in in n_ins
                if not _pairs_fully_present(dataset_dir, group.slug, n_in, n_tgt, pairs_per_depth)
            ]
            if need:
                pair_config = PairConfig(
                    input_counts=tuple(need),
                    target_count=n_tgt,
                    pairs_per_group=pairs_per_depth,
                    seed=seed,
                    method=method,
                    kappa=kappa,
                    stretch_amount=None,  # pairs are linear; core.stretch derives per-image
                    tile_size=tile_size,
                    tile_overlap=tile_overlap,
                    min_tile_coverage=min_tile_coverage,
                    write_tiles=write_tiles,
                    overwrite=False,
                )
                results = generate_training_pairs(
                    cfg["source"],
                    dataset_dir,
                    config=pair_config,
                    sensor=group.sensor,
                    filter_name=group.filter_name,
                    exposure_s=group.exposure_s,
                    target=group.target_dir,
                    min_frames=min_frames,
                    include_mosaics=True,  # this group already passed the mosaic filter above
                    combine_nights=combine_nights,
                    workers=workers,
                    on_progress=on_line,
                )
                # combine_nights=False can make more than one FrameGroup match
                # the same (sensor, target, filter, exposure) filter -- one per
                # night. Any such group is recorded under its own slug so
                # nothing is silently dropped, but its pairs were only sized
                # for THIS group's ladder; a mismatched one fails per-pair
                # (partition_pair raises) rather than writing something wrong.
                for group_result in results:
                    processed_slugs.add(group_result["group"])
                    if group_result["group"] != group.slug:
                        summary["bystander_groups"] += 1
                        dataset_manifest["groups"].append(
                            {"group": group_result["group"], "note": "produced as a side effect "
                             "of this group's filter matching more than one session; see combine_nights"}
                        )

            for n_in in n_ins:
                for pair_index in range(pairs_per_depth):
                    pdir = _pair_dir(dataset_dir, group.slug, pair_index, n_in, n_tgt)
                    if not (pdir / "manifest.json").is_file():
                        summary["pairs_failed"] += 1
                        group_pairs.append({
                            "pair_dir": str(pdir), "status": "failed",
                            "input_count": n_in, "target_count": n_tgt,
                        })
                        continue
                    status = "generated" if n_in in need else "already_present"
                    record = _noise_record(pdir, n_in, n_tgt, status)
                    summary[f"pairs_{status}"] += 1
                    group_pairs.append(record)

        dataset_manifest["groups"].append({
            "group": group.slug,
            "target_dir": group.target_dir,
            "sensor": group.sensor,
            "filter": group.filter_name,
            "night": group.night,
            "frame_count": len(group.frames),
            "ladder": [list(pair) for pair in ladder],
            "pairs": group_pairs,
        })

    dataset_manifest["summary"] = dict(summary)
    _write_dataset_manifest(dataset_dir, dataset_manifest)

    on_line("")
    on_line("summary:")
    for key in sorted(summary):
        on_line(f"  {key:28s} {summary[key]}")
    on_line(f"manifest: {dataset_dir / 'dataset_manifest.json'}")
    return dataset_manifest


def _write_dataset_manifest(dataset_dir: Path, manifest: dict) -> None:
    (dataset_dir / "dataset_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a depth-ladder denoise training dataset from a raw Seestar archive."
    )
    parser.add_argument("--config", required=True, help="Path to a ladder config JSON file")
    parser.add_argument("--max-groups", type=int, default=None, help="Process at most N groups (smoke testing)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    cfg = json.loads(Path(args.config).read_text())
    manifest = build_dataset(cfg, max_groups=args.max_groups)
    return 1 if manifest["summary"].get("pairs_failed") else 0


if __name__ == "__main__":
    raise SystemExit(main())
