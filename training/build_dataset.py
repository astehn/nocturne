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
from collections import defaultdict, namedtuple
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


Rung = namedtuple("Rung", "n_in n_tgt kind")

# The shallowest target a Noise2Noise rung may use. Deep enough that the
# target's per-pixel noise is roughly Gaussian -- the L2 minimiser argument
# wants a symmetric target distribution -- while leaving the input as deep as
# the group can possibly make it. REASONED, not measured: revisit if the deep
# rungs converge poorly.
_MIN_N2N_TARGET = 64


def _rung_kind(n_in: int, n_tgt: int, min_ratio: float) -> str:
    """"truth" if the target is genuinely deeper, else "n2n".

    The SAME rule nocturne.training.pairs.rung_kind applies when it stamps the
    manifest, and it has to be, because the manifest's answer is what picks the
    loss. Labelling a rung by where it sits in the plan instead of by its own
    ratio disagreed with that rule on the max-depth rung of a 74-frame group:
    n_in=9 against a 64-frame target is 7.1x deeper, a truth pair by any
    reading, but the planner called it n2n purely because it was the deep rung.
    """
    return "truth" if n_tgt >= n_in * min_ratio else "n2n"


def _powers_of_two_up_to(limit: int) -> list[int]:
    out, n = [], 1
    while n <= limit:
        out.append(n)
        n *= 2
    return out


def plan_ladder(
    n_frames: int,
    *,
    min_ratio: float = 4.0,
    min_target: int = 16,
    min_n2n_target: int = _MIN_N2N_TARGET,
    max_input: int | None = None,
) -> list[Rung]:
    """Every (input, target) depth this group can afford, by increasing input.

    Depths are DERIVED from n_frames, never taken from a fixed list. The old
    planner did `n_tgt = min(budget, max(depths))`, which held every target at
    128 frames however many the group had -- so the deepest INPUT anywhere was
    32, while the user's real images are 250-450. That single line is the cause
    of the M8 regression this spec exists to fix.

    Two kinds of rung:

    * "truth" -- a genuinely deeper target (min_ratio), as before. Better
      supervision, so it is used wherever the group can afford it.
    * "n2n" -- an independent noisy target, above the depth where a cleaner
      target could exist at all. Noise2Noise: the target does not have to be
      clean, only wrong in a way the input cannot predict.

    One frame is always reserved as the registration reference and belongs to
    neither side.
    """
    available = n_frames - 1
    if available < 2:
        return []
    cap = available if max_input is None else min(available, max_input)

    rungs: list[Rung] = []
    truth_ceiling = 0
    for n_in in _powers_of_two_up_to(cap):
        budget = available - n_in
        if budget < 1:
            continue
        candidates = _powers_of_two_up_to(budget)
        if not candidates:
            continue
        n_tgt = candidates[-1]
        if n_tgt < min_target or n_tgt < n_in * min_ratio:
            continue
        rungs.append(Rung(n_in, n_tgt, "truth"))
        truth_ceiling = max(truth_ceiling, n_in)

    seen = {(r.n_in, r.n_tgt) for r in rungs}
    n2n: list[Rung] = []
    for n_in in _powers_of_two_up_to(min(cap, available - min_n2n_target)):
        if n_in <= truth_ceiling:
            continue
        n_tgt = available - n_in
        if n_tgt < min_n2n_target:
            continue
        if (n_in, n_tgt) not in seen:
            n2n.append(Rung(n_in, n_tgt, _rung_kind(n_in, n_tgt, min_ratio)))
            seen.add((n_in, n_tgt))

    # The max-depth rung: everything the group has, minus the smallest target
    # allowed. This is the rung that actually reaches the user's own stack
    # depth -- 395 frames on M8's 460 -- and no power of two would land there.
    deep_in = min(cap, available - min_n2n_target)
    if deep_in > truth_ceiling and deep_in >= 1 and (deep_in, min_n2n_target) not in seen:
        n2n.append(Rung(deep_in, min_n2n_target,
                        _rung_kind(deep_in, min_n2n_target, min_ratio)))

    return rungs + sorted(n2n)


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

    # `depths` is retired: rungs are derived from each group's real frame count.
    # `max_input` remains only so a smoke config can keep a build small.
    min_n2n_target = int(cfg.get("min_n2n_target", 64))
    max_input = cfg.get("max_input")
    max_input = int(max_input) if max_input is not None else None
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
        ladder = plan_ladder(
            len(group.frames),
            min_ratio=min_ratio,
            min_target=min_target,
            min_n2n_target=min_n2n_target,
            max_input=max_input,
        )
        on_line(
            f"[{index}/{len(groups)}] {group.slug} ({len(group.frames)} frames): "
            + (", ".join(f"{r.n_in}->{r.n_tgt}[{r.kind}]" for r in ladder) if ladder else "no valid pairs, skipped")
        )
        processed_slugs.add(group.slug)
        summary["groups_seen"] += 1
        if not ladder:
            summary["groups_skipped_too_small"] += 1
            continue

        by_target: dict[int, list[int]] = defaultdict(list)
        for r in ladder:
            by_target[r.n_tgt].append(r.n_in)

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
            "ladder": [list(r) for r in ladder],
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
