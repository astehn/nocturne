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
    _tile_starts,
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

# Headroom for frames that plan fine and then fail to REGISTER.
#
# Every n2n rung consumed exactly all available frames -- n_tgt = available -
# n_in -- so a single registration failure killed every one of them. On
# 2026-08-24 s50_M101 lost 2 frames of 214 ("List of matching triangles
# exhausted": a galaxy field with few stars) and all NINE of its deep pairs
# failed. s50_M42's 512->1848 rung uses all 2360 of its frames and survived only
# because none of them failed, after a two-hour registration -- luck, not design.
#
# 3% is about 3x the worst loss measured across the archive (0.93%, M101; every
# other group lost none). The floor of 4 gives small groups absolute headroom
# where a percentage rounds to nothing. Cost is ~3% shallower targets, which is
# far cheaper than losing a group's entire deep end.
_RESERVE_FRACTION = 0.03
_MIN_RESERVE = 4


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
    reserve: int | None = None,
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
    if reserve is None:
        reserve = max(_MIN_RESERVE, math.ceil(n_frames * _RESERVE_FRACTION))
    available = n_frames - 1          # one frame is the registration reference
    # The reserve applies to n2n rungs ONLY. A truth rung takes the largest
    # POWER OF TWO that fits, which already leaves slack; an n2n rung takes
    # `available - n_in`, i.e. every remaining frame, which is the actual
    # fragility. Reserving on both would break the rule Andreas set on
    # 2026-08-23 -- "if a target has 260 it does 256 as well" -- since 260
    # frames minus a 3% reserve can no longer reach a 256-frame target.
    n2n_available = max(0, available - reserve)
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
    for n_in in _powers_of_two_up_to(min(cap, n2n_available - min_n2n_target)):
        if n_in <= truth_ceiling:
            continue
        n_tgt = n2n_available - n_in
        if n_tgt < min_n2n_target:
            continue
        if (n_in, n_tgt) not in seen:
            n2n.append(Rung(n_in, n_tgt, _rung_kind(n_in, n_tgt, min_ratio)))
            seen.add((n_in, n_tgt))

    # The max-depth rung: everything the group has, minus the smallest target
    # allowed. This is the rung that actually reaches the user's own stack
    # depth -- 395 frames on M8's 460 -- and no power of two would land there.
    deep_in = min(cap, n2n_available - min_n2n_target)
    if deep_in > truth_ceiling and deep_in >= 1 and (deep_in, min_n2n_target) not in seen:
        n2n.append(Rung(deep_in, min_n2n_target,
                        _rung_kind(deep_in, min_n2n_target, min_ratio)))

    return rungs + sorted(n2n)


# ------------------------------------------------ weighting the set by depth
#
# The ladder makes one rung per power of two, so every group -- however small --
# can afford the shallow end while only the biggest can afford the deep end.
# With a flat pairs_per_depth the shallow rungs are therefore replicated once
# per group. Measured on the finished n2n_v1 dataset (2026-08-24): 85% of its
# tiles had an input of fewer than 128 frames, roughly two thirds came from
# stacks of 32 or fewer, and the rungs matching how the user actually shoots
# (239/256/301/395) were 6.5% between them. Nobody chose that weighting.
#
# So: count pairs per RUNG, not per group. Deep rungs get several pairs each;
# shallow rungs get one, and only at the handful of depths worth keeping at all
# -- a brand-new Seestar owner does have a 30-frame stack, but the model should
# not be trained as though most users do.

_DEEP_FROM = 128
_PAIRS_DEEP = 4
_PAIRS_SHALLOW = 1
# One per octave rather than all seven powers of two: at one pair each, keeping
# every shallow rung still leaves shallow material near a third of the set.
_SHALLOW_DEPTHS = (1, 16, 64)

# Fraction of the geometrically possible tiles that actually clear
# min_tile_coverage -- the rest are frame-edge tiles the dither never fully
# covered. MEASURED on the completed n2n_v1 dataset (2026-08-24): 5040 tiles
# across 172 pairs is 29.3 per pair, against the 40 a 3840x2160 pair holds at
# tile 512 / overlap 32.
_TILE_COVERAGE_RETENTION = 0.73

GroupPlan = namedtuple("GroupPlan", "group ladder rungs")


def pairs_for_rung(
    n_in: int,
    *,
    deep_from: int = _DEEP_FROM,
    pairs_deep: int = _PAIRS_DEEP,
    pairs_shallow: int = _PAIRS_SHALLOW,
    shallow_depths=_SHALLOW_DEPTHS,
    is_deepest: bool = False,
) -> int:
    """How many pairs this rung is worth. 0 means do not build it at all.

    `is_deepest` keeps a group's deepest affordable rung whatever its depth,
    even when the weighting would otherwise drop it. Without it, thinning the
    shallow end silently guts the GATE: neither held-out target is big enough
    for a 128-frame rung, so NGC6888 would lose 118->64 and NGC281 both 44->64
    and 32->76, taking the deepest truth-checked input from 118 frames down to
    64. The do-no-harm gate is the only thing standing between an unattended run
    and the model the app ships, and a group's deepest rung is the closest that
    group can get to a real user's stack -- exactly what the gate needs to see.
    """
    if n_in >= deep_from:
        return pairs_deep
    if n_in in set(shallow_depths) or is_deepest:
        return pairs_shallow
    return 0


def _tiles_per_pair(shape, tile_size: int, tile_overlap: int) -> float:
    """Expected tiles from one pair of this frame geometry.

    Uses materialize_tiles' own _tile_starts so the estimate cannot drift from
    what the build actually writes. The two geometries in the archive are very
    different -- the S30 Pro's 3840x2160 holds 40 tiles, the S50's 1920x1080
    only 12 -- and since every deep group is an S50 one, a single flat
    tiles-per-pair number would overstate the deep share about threefold.
    """
    step = tile_size - tile_overlap
    rows = len(_tile_starts(int(shape[0]), tile_size, step))
    cols = len(_tile_starts(int(shape[1]), tile_size, step))
    return rows * cols * _TILE_COVERAGE_RETENTION


def _depth_band(n_in: int, deep_from: int) -> tuple[int, str]:
    """(sort key, label). Shallow rungs are named by their exact depth -- there
    are only a handful by construction -- while deep inputs are arbitrary
    integers (available - min_n2n_target), so they are bucketed by octave."""
    if n_in < deep_from:
        return n_in, str(n_in)
    lo = deep_from
    while lo * 2 <= n_in:
        lo *= 2
    return lo, f"{lo}-{lo * 2 - 1}"


def tile_share_estimate(plans, *, deep_from: int, tile_size: int, tile_overlap: int) -> list[dict]:
    """One row per depth band: how much of the finished set it will be."""
    bands: dict[int, dict] = {}
    for plan in plans:
        per_pair = _tiles_per_pair(plan.group.frames[0].shape, tile_size, tile_overlap)
        for rung, n_pairs in plan.rungs:
            key, label = _depth_band(rung.n_in, deep_from)
            row = bands.setdefault(key, {
                "depth": label, "deep": rung.n_in >= deep_from,
                "rungs": 0, "pairs": 0, "tiles": 0.0,
            })
            row["rungs"] += 1
            row["pairs"] += n_pairs
            row["tiles"] += n_pairs * per_pair
    rows = [bands[k] for k in sorted(bands)]
    total = sum(r["tiles"] for r in rows)
    for row in rows:
        row["share"] = row["tiles"] / total if total else 0.0
    return rows


def _tile_share_lines(rows, *, deep_from: int) -> list[str]:
    head = (f"tile-share estimate ({_TILE_COVERAGE_RETENTION:.2f} of a pair's "
            f"geometric tiles clear coverage; measured on n2n_v1)")
    lines = ["", head, "",
             f"  {'depth':>14}  {'rungs':>6}  {'pairs':>6}  {'tiles':>7}  {'share':>7}"]
    for row in rows:
        lines.append(f"  {row['depth']:>14}  {row['rungs']:>6}  {row['pairs']:>6}  "
                     f"{row['tiles']:>7.0f}  {row['share']:>6.1%}")
    lines.append("  " + "-" * 48)
    for deep, label in ((False, f"shallow (<{deep_from})"), (True, f"deep (>={deep_from})")):
        part = [r for r in rows if r["deep"] is deep]
        lines.append(
            f"  {label:>14}  {sum(r['rungs'] for r in part):>6}  "
            f"{sum(r['pairs'] for r in part):>6}  {sum(r['tiles'] for r in part):>7.0f}  "
            f"{sum(r['share'] for r in part):>6.1%}")
    lines.append("")
    return lines


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
    deep_from = int(cfg.get("deep_from", _DEEP_FROM))
    pairs_deep = int(cfg.get("pairs_deep", _PAIRS_DEEP))
    pairs_shallow = int(cfg.get("pairs_shallow", _PAIRS_SHALLOW))
    shallow_depths = tuple(int(d) for d in cfg.get("shallow_depths", _SHALLOW_DEPTHS))
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

    # `sensors` is the training MATERIAL; `sensor` is the model's identity --
    # stage() writes denoise_{sensor}_v1.onnx and Nocturne targets the S30 Pro.
    # They were one key, which is why n2n_v1 trained on 29% of the archive: the
    # 5596 S50 frames, and with them every deep group on the drive, were
    # excluded by the same string that names the shipped file.
    sensors = set(cfg.get("sensors") or [cfg.get("sensor")])
    groups = discover_frame_groups(
        cfg["source"],
        sensor=None,
        min_frames=min_frames,
        combine_nights=combine_nights,
    )
    # Filtering groups, not frames: a group's key includes its sensor, so every
    # frame in one shares it and the two are equivalent -- but only this way can
    # more than one sensor be asked for in a single scan of the archive.
    if None not in sensors:
        groups = [g for g in groups if g.sensor in sensors]
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

    # Plan every group BEFORE building any of it. The ladder follows from frame
    # counts alone, so the whole weighting is knowable up front -- and it has to
    # be printed up front, or it is discovered only after the hours are spent.
    plans: list[GroupPlan] = []
    planned_slugs: set[str] = set()
    for index, group in enumerate(groups, start=1):
        if group.slug in planned_slugs:
            continue
        planned_slugs.add(group.slug)
        ladder = plan_ladder(
            len(group.frames),
            min_ratio=min_ratio,
            min_target=min_target,
            min_n2n_target=min_n2n_target,
            max_input=max_input,
        )
        deepest = max((r.n_in for r in ladder), default=None)
        selected = [
            (rung, n_pairs)
            for rung in ladder
            for n_pairs in [pairs_for_rung(
                rung.n_in, deep_from=deep_from, pairs_deep=pairs_deep,
                pairs_shallow=pairs_shallow, shallow_depths=shallow_depths,
                is_deepest=(rung.n_in == deepest))]
            if n_pairs > 0
        ]
        plans.append(GroupPlan(group, ladder, selected))
        if selected:
            detail = ", ".join(f"{r.n_in}->{r.n_tgt}[{r.kind}]x{n}" for r, n in selected)
        elif ladder:
            detail = "no rung survived the depth weighting, skipped"
        else:
            detail = "no valid pairs, skipped"
        on_line(f"[{index}/{len(groups)}] {group.slug} ({len(group.frames)} frames): {detail}")

    for line in _tile_share_lines(
        tile_share_estimate(plans, deep_from=deep_from, tile_size=tile_size,
                            tile_overlap=tile_overlap),
        deep_from=deep_from,
    ):
        on_line(line)

    processed_slugs: set[str] = set()
    for plan in plans:
        group, ladder = plan.group, plan.ladder
        if group.slug in processed_slugs:
            continue
        processed_slugs.add(group.slug)
        summary["groups_seen"] += 1
        if not plan.rungs:
            summary["groups_skipped_too_small" if not ladder
                    else "groups_skipped_by_weighting"] += 1
            continue

        # ALL of the group's missing rungs in ONE call, whatever their target
        # depths. generate_training_pairs registers the group once per call, so
        # the previous grouping by target cost a full re-registration of the
        # same frames per distinct target -- four of them on a 366-frame group
        # under the derived ladder, where the old fixed ladder had only ever
        # produced one. PreparedStack was built for exactly this reuse.
        need = [
            (r.n_in, r.n_tgt, n_pairs) for r, n_pairs in plan.rungs
            if not _pairs_fully_present(
                dataset_dir, group.slug, r.n_in, r.n_tgt, n_pairs
            )
        ]
        group_pairs: list[dict] = []
        if need:
            pair_config = PairConfig(
                rungs=tuple(need),
                pairs_per_group=pairs_per_depth,
                seed=seed,
                method=method,
                kappa=kappa,
                # The same ratio plan_ladder used above. _write_pair
                # recomputes each pair's kind from it, so a config that
                # moved min_ratio off 4.0 would otherwise have the planner
                # and the manifest labelling the same pair differently.
                min_ratio=min_ratio,
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

        requested = {(n_in, n_tgt) for n_in, n_tgt, _ in need}
        for rung, n_pairs in plan.rungs:
            n_in, n_tgt = rung.n_in, rung.n_tgt
            for pair_index in range(n_pairs):
                pdir = _pair_dir(dataset_dir, group.slug, pair_index, n_in, n_tgt)
                if not (pdir / "manifest.json").is_file():
                    summary["pairs_failed"] += 1
                    group_pairs.append({
                        "pair_dir": str(pdir), "status": "failed",
                        "input_count": n_in, "target_count": n_tgt,
                    })
                    continue
                status = "generated" if (n_in, n_tgt) in requested else "already_present"
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
            # The rungs actually built, each with the pair count the depth
            # weighting gave it -- the plain ladder no longer describes the set.
            "ladder": [list(r) + [n_pairs] for r, n_pairs in plan.rungs],
            "ladder_planned": [list(r) for r in ladder],
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
