"""Generate reproducible noisy/clean training pairs from Seestar subs.

The generator reuses Nocturne's own FITS loading, demosaic, registration,
normalisation, warping, and integration functions.  It intentionally does not
call :func:`nocturne.stacking.stacker.run_stack` twice for each pair because
that would register the same group repeatedly and, more importantly, would
force each stack's first frame to be both its registration reference and an
integrated pixel source.

The pair contract is:

* one reference frame is used for geometry only;
* noisy and clean frame lists are disjoint;
* both results are registered to the same reference canvas;
* both results are scaled by the clean result's shared scale;
* a manifest records every input, option, and random seed.

This is a dataset builder, not a model trainer.  It writes full-resolution FITS
pairs and can optionally materialise overlapping NumPy tile shards.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Sequence

import numpy as np
from astropy.io import fits

from ..core.export import save_fits
from ..core.image import AstroImage, finite_or_zero
from ..core.stretch import apply_stretch
from ..stacking.coverage import full_coverage_bounds
from ..stacking.frames import load_sub, luminance
from ..stacking.integrate import average_integrate, sigma_clip_integrate
from ..stacking.normalize import frame_stats, normalize_to
from ..stacking.parallel import ordered_results, plan_workers
from ..stacking.register import warp_with_validity
from ..stacking.register_pool import register_frames


Progress = Callable[[str, int, int], None]


def _float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _slug(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value).strip())
    return value.strip("._-") or "unknown"


def _sensor_name(telescope: str, instrument: str, shape: tuple[int, int]) -> str:
    text = f"{telescope} {instrument}".lower()
    if "s30" in text or shape == (2160, 3840):
        return "s30"
    if "s50" in text or shape == (1080, 1920):
        return "s50"
    return "unknown"


def _circular_span(values: Sequence[float]) -> float:
    """Smallest RA span in degrees, handling the 0/360 seam."""
    if len(values) < 2:
        return 0.0
    vals = sorted(float(v) % 360.0 for v in values)
    gaps = [b - a for a, b in zip(vals, vals[1:])]
    gaps.append(vals[0] + 360.0 - vals[-1])
    return 360.0 - max(gaps)


@dataclass(frozen=True)
class FrameInfo:
    """Header-only information used to group a source FITS frame."""

    path: str
    relative_path: str
    target_dir: str
    object_name: str
    sensor: str
    telescope: str
    instrument: str
    shape: tuple[int, int]
    filter_name: str
    exposure_s: float
    night: str
    date_obs: str
    ra_deg: float | None
    dec_deg: float | None
    gain: float | None

    def to_manifest(self, root: Path | None = None) -> dict:
        path = Path(self.path)
        if root is not None:
            try:
                path_value = str(path.relative_to(root))
            except ValueError:
                path_value = str(path)
        else:
            path_value = str(path)
        out = asdict(self)
        out["path"] = path_value
        out["shape"] = list(self.shape)
        return out


@dataclass(frozen=True)
class FrameGroup:
    """A homogeneous capture sequence suitable for pair generation."""

    sensor: str
    target_dir: str
    filter_name: str
    exposure_s: float
    night: str
    frames: tuple[FrameInfo, ...]
    ra_span_deg: float = 0.0
    dec_span_deg: float = 0.0

    @property
    def target(self) -> str:
        return self.target_dir

    @property
    def pointing_span_deg(self) -> float:
        return max(self.ra_span_deg, self.dec_span_deg)

    @property
    def mosaic(self) -> bool:
        # A normal Seestar sequence can drift by tenths of a degree; the M31
        # multi-panel capture in the supplied archive spans 2.8–6.5 degrees.
        # Keep the threshold high enough not to discard the real NGC7000
        # sequence, whose commanded pointing span is about 0.88 degrees.
        return self.pointing_span_deg > 1.5

    @property
    def slug(self) -> str:
        return _slug(
            f"{self.sensor}_{self.target_dir}_{self.night}_"
            f"{self.filter_name}_{self.exposure_s:g}s"
        )

    def to_manifest(self, root: Path | None = None) -> dict:
        return {
            "sensor": self.sensor,
            "target_dir": self.target_dir,
            "filter": self.filter_name,
            "exposure_s": self.exposure_s,
            "night": self.night,
            "frame_count": len(self.frames),
            "ra_span_deg": self.ra_span_deg,
            "dec_span_deg": self.dec_span_deg,
            "mosaic": self.mosaic,
            "frames": [f.to_manifest(root) for f in self.frames],
        }


def _read_frame_info(path: Path, root: Path) -> FrameInfo | None:
    """Read one FITS header without touching its pixel payload."""
    try:
        with fits.open(
            path,
            mode="readonly",
            memmap=False,
            lazy_load_hdus=True,
            do_not_scale_image_data=True,
        ) as hdul:
            header = hdul[0].header
            naxis = int(header.get("NAXIS", 0) or 0)
            if naxis != 2:
                return None
            width = int(header.get("NAXIS1", 0) or 0)
            height = int(header.get("NAXIS2", 0) or 0)
            if width <= 0 or height <= 0:
                return None

            image_type = str(
                header.get("IMAGETYP", header.get("FRAME", ""))
            ).lower()
            if "master" in image_type or any(
                key in header for key in ("NSUBS", "STACKCNT", "NCOMBINE")
            ):
                return None

            date_obs = str(header.get("DATE-OBS", header.get("DATE", ""))).strip()
            night = date_obs[:10] if len(date_obs) >= 10 else "unknown"
            telescope = str(header.get("TELESCOP", "")).strip()
            instrument = str(header.get("INSTRUME", "")).strip()
            shape = (height, width)
            object_name = str(header.get("OBJECT", "")).strip()
            relative_parts = path.relative_to(root).parts
            # The real archive has one target per top-level directory.  Using
            # OBJECT for a file placed directly under the input root keeps the
            # scanner useful for small exported/test datasets too.
            target_dir = (
                relative_parts[0]
                if len(relative_parts) > 1
                else (object_name or root.name)
            )
            return FrameInfo(
                path=str(path.resolve()),
                relative_path=str(path.relative_to(root)),
                target_dir=target_dir,
                object_name=object_name,
                sensor=_sensor_name(telescope, instrument, shape),
                telescope=telescope,
                instrument=instrument,
                shape=shape,
                filter_name=str(
                    header.get("FILTER", header.get("FILTER1", "unknown"))
                ).strip()
                or "unknown",
                exposure_s=float(
                    _float(header.get("EXPTIME", header.get("EXPOSURE"))) or 0.0
                ),
                night=night,
                date_obs=date_obs,
                ra_deg=_float(header.get("RA")),
                dec_deg=_float(header.get("DEC")),
                gain=_float(header.get("GAIN")),
            )
    except (OSError, ValueError, TypeError, fits.FitsException):
        return None


def scan_training_frames(root: str | os.PathLike[str]) -> list[FrameInfo]:
    """Discover readable light frames beneath ``root`` using headers only."""
    base = Path(root).expanduser().resolve()
    if not base.is_dir():
        raise FileNotFoundError(f"training input directory does not exist: {base}")
    paths = sorted(
        p
        for p in base.rglob("*")
        if p.is_file() and p.suffix.lower() in {".fit", ".fits", ".fts"}
    )
    frames = [_read_frame_info(p, base) for p in paths]
    return [f for f in frames if f is not None]


def discover_frame_groups(
    root: str | os.PathLike[str],
    *,
    sensor: str | None = None,
    filter_name: str | None = None,
    exposure_s: float | None = None,
    target: str | None = None,
    min_frames: int = 3,
) -> list[FrameGroup]:
    """Group frames by sensor, target, filter, exposure, and capture night.

    Groups are intentionally separated by night.  This prevents a first
    prototype from silently mixing different sky conditions while still
    leaving the caller free to combine sessions explicitly later.
    """
    frames = scan_training_frames(root)
    wanted_sensor = sensor.lower() if sensor else None
    wanted_filter = filter_name.lower() if filter_name else None
    wanted_target = target.lower() if target else None
    groups: dict[tuple, list[FrameInfo]] = defaultdict(list)
    for frame in frames:
        if wanted_sensor and frame.sensor.lower() != wanted_sensor:
            continue
        if wanted_filter and frame.filter_name.lower() != wanted_filter:
            continue
        if exposure_s is not None and not math.isclose(
            frame.exposure_s, float(exposure_s), rel_tol=0.0, abs_tol=1e-4
        ):
            continue
        if wanted_target and frame.target_dir.lower() != wanted_target:
            continue
        key = (
            frame.sensor,
            frame.target_dir,
            frame.filter_name,
            round(frame.exposure_s, 4),
            frame.night,
        )
        groups[key].append(frame)

    result: list[FrameGroup] = []
    for key, members in sorted(groups.items()):
        if len(members) < min_frames:
            continue
        ra = [f.ra_deg for f in members if f.ra_deg is not None]
        dec = [f.dec_deg for f in members if f.dec_deg is not None]
        ra_span = _circular_span(ra)
        dec_span = max(dec) - min(dec) if len(dec) > 1 else 0.0
        # Preserve the information even when the caller later decides to allow
        # mosaics; the threshold is applied by the generation command.
        result.append(
            FrameGroup(
                sensor=key[0],
                target_dir=key[1],
                filter_name=key[2],
                exposure_s=key[3],
                night=key[4],
                frames=tuple(sorted(members, key=lambda f: (f.date_obs, f.path))),
                ra_span_deg=ra_span,
                dec_span_deg=dec_span,
            )
        )
    return result


def _stable_seed(seed: int, group: FrameGroup, ordinal: int) -> int:
    text = (
        f"{seed}|{group.sensor}|{group.target_dir}|{group.filter_name}|"
        f"{group.exposure_s:.4f}|{group.night}|{ordinal}"
    )
    return int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "little")


def partition_pair(
    paths: Sequence[str],
    *,
    input_count: int,
    target_count: int,
    seed: int,
) -> tuple[list[str], list[str]]:
    """Return deterministic, disjoint noisy and clean frame lists."""
    available = list(dict.fromkeys(str(Path(p).resolve()) for p in paths))
    if input_count < 1 or target_count < 1:
        raise ValueError("input_count and target_count must be positive")
    if input_count + target_count > len(available):
        raise ValueError(
            f"need {input_count + target_count} frames, only {len(available)} available"
        )
    rng = np.random.default_rng(seed)
    permutation = rng.permutation(len(available))
    noisy = [available[int(i)] for i in permutation[:input_count]]
    clean = [
        available[int(i)]
        for i in permutation[input_count : input_count + target_count]
    ]
    return noisy, clean


@dataclass(frozen=True)
class PreparedFrame:
    path: str
    matrix: np.ndarray
    exposure_s: float
    stats: tuple[np.ndarray, np.ndarray]


@dataclass
class RawStack:
    """An integrated stack before the pair's shared scale is applied."""

    data: np.ndarray
    coverage: np.ndarray
    used: tuple[str, ...]
    integration_seconds: float


@dataclass
class PreparedStack:
    """Registration and normalisation context reusable across many subsets."""

    reference_path: str
    reference_image: AstroImage
    reference_stats: tuple[np.ndarray, np.ndarray]
    frames: dict[str, PreparedFrame]
    rejected: tuple[tuple[str, str], ...]

    @property
    def available_paths(self) -> tuple[str, ...]:
        return tuple(self.frames)

    def integrate(
        self,
        paths: Sequence[str],
        *,
        method: str = "average",
        kappa: float = 2.5,
        workers: int | None = None,
        autocrop: bool = False,
        on_progress: Progress | None = None,
        label: str = "stack",
    ) -> RawStack:
        """Integrate an already-registered subset.

        ``autocrop=False`` is the default because both sides of a training pair
        must share one canvas.  The coverage fraction is returned so tile
        materialisation can exclude low-coverage borders.
        """
        selected = [str(Path(p).resolve()) for p in paths]
        missing = [p for p in selected if p not in self.frames]
        if missing:
            raise ValueError(f"frames were not successfully registered: {missing[:3]}")
        if len(selected) < 3:
            raise ValueError("need at least 3 successfully registered frames to stack")
        if method not in {"average", "sigma_clip"}:
            raise ValueError("method must be 'average' or 'sigma_clip'")

        worker_count = workers if workers is not None else plan_workers().count
        total = len(selected)
        pass_number = 0

        def prepare(path: str):
            sub = load_sub(path, normalize=False)
            record = self.frames[path]
            data = normalize_to(sub.data, record.stats, self.reference_stats)
            return warp_with_validity(data, record.matrix)

        def frames_for_pass():
            nonlocal pass_number
            pass_number += 1
            for index, result in enumerate(
                ordered_results(selected, prepare, worker_count), start=1
            ):
                if on_progress is not None:
                    on_progress(f"{label} pass {pass_number}", index, total)
                yield result

        if method == "sigma_clip":
            data, coverage = sigma_clip_integrate(frames_for_pass, kappa)
        else:
            data, coverage = average_integrate(frames_for_pass())

        if autocrop:
            top, bottom, left, right = full_coverage_bounds(coverage, len(selected))
            data = data[top:bottom, left:right]
            coverage = coverage[top:bottom, left:right]

        return RawStack(
            data=np.asarray(data, dtype=np.float32),
            coverage=np.asarray(coverage, dtype=np.int32),
            used=tuple(selected),
            integration_seconds=sum(self.frames[p].exposure_s for p in selected),
        )


def prepare_stack(
    paths: Sequence[str],
    reference_path: str,
    *,
    workers: int | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> PreparedStack:
    """Register ``paths`` once against a reference for repeated integration.

    The reference may be present in ``paths`` for convenience, but callers
    generating independent pairs should leave it out of both integration
    subsets.  Registration failures are retained in ``rejected`` rather than
    aborting the whole group.
    """
    source_paths = list(dict.fromkeys(str(Path(p).resolve()) for p in paths))
    reference_path = str(Path(reference_path).resolve())
    if len(source_paths) < 3:
        raise ValueError("prepare_stack needs at least 3 source frames")
    if not Path(reference_path).is_file():
        raise FileNotFoundError(reference_path)

    reference_image = load_sub(reference_path, normalize=False)
    reference_stats = frame_stats(reference_image.data)
    records: dict[str, PreparedFrame] = {}
    rejected: list[tuple[str, str]] = []

    if reference_path in source_paths:
        records[reference_path] = PreparedFrame(
            path=reference_path,
            matrix=np.eye(3, dtype=np.float64),
            exposure_s=float(reference_image.metadata.get("exposure", 0.0) or 0.0),
            stats=reference_stats,
        )

    to_register = [p for p in source_paths if p != reference_path]
    worker_count = workers if workers is not None else plan_workers().count

    def progress(index: int) -> None:
        if on_progress is not None:
            on_progress(index, len(to_register))

    for result in register_frames(
        to_register,
        reference_path,
        workers=worker_count,
        on_progress=progress,
    ):
        if result.reason is not None or result.matrix is None or result.stats is None:
            rejected.append((result.path, result.reason or "registration failed"))
            continue
        records[result.path] = PreparedFrame(
            path=result.path,
            matrix=np.asarray(result.matrix, dtype=np.float64),
            exposure_s=float(result.exposure or 0.0),
            stats=result.stats,
        )

    # Keep caller order stable; this also makes manifest diffs reproducible.
    ordered = {p: records[p] for p in source_paths if p in records}
    return PreparedStack(
        reference_path=reference_path,
        reference_image=reference_image,
        reference_stats=reference_stats,
        frames=ordered,
        rejected=tuple(rejected),
    )


@dataclass(frozen=True)
class PairConfig:
    input_counts: tuple[int, ...] = (16,)
    target_count: int = 128
    pairs_per_group: int = 4
    seed: int = 20260821
    method: str = "average"
    kappa: float = 2.5
    stretch_amount: float | None = None
    tile_size: int = 512
    tile_overlap: int = 32
    min_tile_coverage: float = 0.9
    write_tiles: bool = False
    overwrite: bool = False


def _scaled_pair(
    noisy: RawStack,
    clean: RawStack,
    *,
    stretch_amount: float | None,
) -> tuple[AstroImage, AstroImage, np.ndarray, float, float, float]:
    if noisy.data.shape != clean.data.shape:
        raise ValueError(
            f"pair geometry differs: noisy={noisy.data.shape}, clean={clean.data.shape}"
        )
    target = finite_or_zero(np.asarray(clean.data, dtype=np.float32))
    scale = float(np.max(target))
    if not np.isfinite(scale) or scale <= 0:
        raise ValueError("clean stack has no positive finite scale")

    noisy_data = np.clip(finite_or_zero(noisy.data) / scale, 0.0, 1.0)
    clean_data = np.clip(target / scale, 0.0, 1.0)
    coverage = np.minimum(
        noisy.coverage.astype(np.float32) / max(1, len(noisy.used)),
        clean.coverage.astype(np.float32) / max(1, len(clean.used)),
    )
    noisy_clip_fraction = float(np.mean((finite_or_zero(noisy.data) / scale) > 1.0))
    clean_clip_fraction = float(np.mean((target / scale) > 1.0))

    noisy_image = AstroImage(noisy_data, is_linear=True)
    clean_image = AstroImage(clean_data, is_linear=True)
    if stretch_amount is not None:
        noisy_image = apply_stretch(noisy_image, stretch_amount)
        clean_image = apply_stretch(clean_image, stretch_amount)
    return (
        noisy_image,
        clean_image,
        coverage,
        scale,
        noisy_clip_fraction,
        clean_clip_fraction,
    )


def _tile_starts(length: int, tile_size: int, step: int) -> list[int]:
    if length <= tile_size:
        return [0]
    starts = list(range(0, length - tile_size + 1, step))
    final = length - tile_size
    if starts[-1] != final:
        starts.append(final)
    return starts


def materialize_tiles(
    noisy: AstroImage,
    clean: AstroImage,
    coverage: np.ndarray,
    output_dir: str | os.PathLike[str],
    *,
    tile_size: int,
    overlap: int,
    min_coverage: float,
) -> int:
    """Write compressed ``.npz`` tiles and return the number written."""
    if tile_size <= 0 or overlap < 0 or overlap >= tile_size:
        raise ValueError("tile_size must be positive and overlap must be smaller")
    if noisy.data.shape != clean.data.shape:
        raise ValueError("noisy and clean tile sources must have equal geometry")
    if coverage.shape != noisy.data.shape[:2]:
        raise ValueError("coverage must be a 2D image matching the pair")
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    height, width = noisy.data.shape[:2]
    step = tile_size - overlap
    count = 0
    for y in _tile_starts(height, tile_size, step):
        for x in _tile_starts(width, tile_size, step):
            y1, x1 = min(y + tile_size, height), min(x + tile_size, width)
            cov = coverage[y:y1, x:x1]
            if float(np.mean(cov)) < min_coverage:
                continue
            np.savez_compressed(
                output / f"tile_{count:06d}.npz",
                input=noisy.data[y:y1, x:x1],
                target=clean.data[y:y1, x:x1],
                coverage=cov.astype(np.float32),
                origin=np.asarray([y, x], dtype=np.int32),
            )
            count += 1
    return count


def _write_coverage(path: Path, coverage: np.ndarray) -> None:
    fits.PrimaryHDU(np.asarray(coverage, dtype=np.float32)).writeto(
        path, overwrite=True
    )


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _group_pair_specs(
    group: FrameGroup,
    available: Sequence[str],
    config: PairConfig,
    reference: str,
) -> list[dict]:
    pool = list(available)
    specs: list[dict] = []
    ordinal = 0
    for input_count in config.input_counts:
        for pair_index in range(config.pairs_per_group):
            if input_count + config.target_count > len(pool):
                continue
            seed = _stable_seed(config.seed, group, ordinal)
            noisy, clean = partition_pair(
                pool,
                input_count=input_count,
                target_count=config.target_count,
                seed=seed,
            )
            specs.append(
                {
                    "pair_index": pair_index,
                    "input_count": input_count,
                    "target_count": config.target_count,
                    "seed": seed,
                    "reference": reference,
                    "noisy": noisy,
                    "clean": clean,
                }
            )
            ordinal += 1
    return specs


def _frame_lookup(group: FrameGroup) -> dict[str, FrameInfo]:
    return {f.path: f for f in group.frames}


def _write_pair(
    output_dir: Path,
    group: FrameGroup,
    spec: dict,
    noisy: AstroImage,
    clean: AstroImage,
    coverage: np.ndarray,
    scale: float,
    noisy_clip_fraction: float,
    clean_clip_fraction: float,
    config: PairConfig,
    root: Path,
    prepared: PreparedStack,
) -> dict:
    pair_dir = output_dir / group.slug / (
        f"pair_{spec['pair_index']:04d}_in{spec['input_count']}_"
        f"target{spec['target_count']}"
    )
    if pair_dir.exists() and not config.overwrite:
        return {"status": "exists", "path": str(pair_dir)}
    pair_dir.mkdir(parents=True, exist_ok=True)

    common_header = {
        "TRNPAIR": "nocturne",
        "SENSOR": group.sensor,
        "FILTER": group.filter_name,
        "EXPTIME": group.exposure_s,
        "INPUTN": spec["input_count"],
        "TARGETN": spec["target_count"],
        "SCALE": scale,
    }
    save_fits(noisy, str(pair_dir / "input.fits"), {**common_header, "ROLE": "input"})
    save_fits(clean, str(pair_dir / "target.fits"), {**common_header, "ROLE": "target"})
    _write_coverage(pair_dir / "coverage.fits", coverage)

    tile_count = 0
    if config.write_tiles:
        tile_count = materialize_tiles(
            noisy,
            clean,
            coverage,
            pair_dir / "tiles",
            tile_size=config.tile_size,
            overlap=config.tile_overlap,
            min_coverage=config.min_tile_coverage,
        )

    lookup = _frame_lookup(group)
    manifest = {
        "format": "nocturne-training-pair-v1",
        "created_utc": datetime.now().astimezone().isoformat(),
        "group": group.to_manifest(root),
        "pair": {
            "pair_index": spec["pair_index"],
            "input_count": spec["input_count"],
            "target_count": spec["target_count"],
            "seed": spec["seed"],
            "reference": lookup.get(spec["reference"], FrameInfo(
                spec["reference"], spec["reference"], group.target_dir, "",
                group.sensor, "", "", (0, 0), group.filter_name,
                group.exposure_s, group.night, "", None, None, None,
            )).to_manifest(root),
            "noisy_frames": [lookup[p].to_manifest(root) for p in spec["noisy"]],
            "clean_frames": [lookup[p].to_manifest(root) for p in spec["clean"]],
            "disjoint": not set(spec["noisy"]).intersection(spec["clean"]),
            "shared_reference_excluded": spec["reference"] not in set(spec["noisy"]) | set(spec["clean"]),
        },
        "stack": {
            "method": config.method,
            "kappa": config.kappa,
            "autocrop": False,
            "reference_path": str(Path(prepared.reference_path).relative_to(root))
            if Path(prepared.reference_path).is_relative_to(root)
            else prepared.reference_path,
            "rejected_during_registration": [list(x) for x in prepared.rejected],
        },
        "pair_scaling": {
            "shared_clean_peak": scale,
            "noisy_clip_fraction": noisy_clip_fraction,
            "clean_clip_fraction": clean_clip_fraction,
        },
        "postprocess": {
            "stretch_amount": config.stretch_amount,
        },
        "arrays": {
            "shape": list(noisy.data.shape),
            "dtype": str(noisy.data.dtype),
            "coverage_dtype": str(coverage.dtype),
            "tile_count": tile_count,
        },
    }
    _write_json(pair_dir / "manifest.json", manifest)
    return {"status": "written", "path": str(pair_dir), "tiles": tile_count}


def generate_training_pairs(
    input_root: str | os.PathLike[str],
    output_root: str | os.PathLike[str],
    *,
    config: PairConfig | None = None,
    sensor: str | None = None,
    filter_name: str | None = None,
    exposure_s: float | None = None,
    target: str | None = None,
    min_frames: int = 3,
    include_mosaics: bool = False,
    workers: int | None = None,
    max_groups: int | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> list[dict]:
    """Generate pair directories and return one result record per pair/group."""
    config = config or PairConfig()
    root = Path(input_root).expanduser().resolve()
    output = Path(output_root).expanduser().resolve()
    groups = discover_frame_groups(
        root,
        sensor=sensor,
        filter_name=filter_name,
        exposure_s=exposure_s,
        target=target,
        min_frames=min_frames,
    )
    if not include_mosaics:
        groups = [group for group in groups if not group.mosaic]
    if max_groups is not None:
        groups = groups[: max(0, int(max_groups))]

    results: list[dict] = []
    for group_index, group in enumerate(groups):
        if on_progress is not None:
            on_progress(
                f"preparing {group_index + 1}/{len(groups)} "
                f"{group.slug} ({len(group.frames)} frames)"
            )
        all_paths = [frame.path for frame in group.frames]
        reference = all_paths[len(all_paths) // 2]
        prepared = prepare_stack(all_paths, reference, workers=workers)
        available = [p for p in all_paths if p in prepared.frames and p != reference]
        specs = _group_pair_specs(group, available, config, reference)
        group_result = {
            "status": "prepared",
            "group": group.slug,
            "frame_count": len(group.frames),
            "registered_count": len(available),
            "rejected_count": len(prepared.rejected),
            "pairs_requested": len(specs),
            "pairs": [],
        }
        for spec in specs:
            try:
                noisy_raw = prepared.integrate(
                    spec["noisy"],
                    method=config.method,
                    kappa=config.kappa,
                    workers=workers,
                    autocrop=False,
                    label=f"{group.slug} noisy",
                )
                clean_raw = prepared.integrate(
                    spec["clean"],
                    method=config.method,
                    kappa=config.kappa,
                    workers=workers,
                    autocrop=False,
                    label=f"{group.slug} clean",
                )
                noisy, clean, coverage, scale, noisy_clip, clean_clip = _scaled_pair(
                    noisy_raw,
                    clean_raw,
                    stretch_amount=config.stretch_amount,
                )
                result = _write_pair(
                    output,
                    group,
                    spec,
                    noisy,
                    clean,
                    coverage,
                    scale,
                    noisy_clip,
                    clean_clip,
                    config,
                    root,
                    prepared,
                )
            except Exception as exc:  # keep other pairs/groups usable
                result = {
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {exc}",
                    "pair_index": spec["pair_index"],
                }
            group_result["pairs"].append(result)
        results.append(group_result)
    return results


def _parse_counts(value: str) -> tuple[int, ...]:
    counts = tuple(int(part.strip()) for part in value.split(",") if part.strip())
    if not counts or any(count < 1 for count in counts):
        raise argparse.ArgumentTypeError("expected positive comma-separated counts")
    return counts


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate reproducible Nocturne Seestar training pairs."
    )
    parser.add_argument("--input", required=True, help="Training FITS root")
    parser.add_argument("--output", required=True, help="Output pair root")
    parser.add_argument("--sensor", choices=("s30", "s50"))
    parser.add_argument("--filter", dest="filter_name")
    parser.add_argument("--exposure", type=float, dest="exposure_s")
    parser.add_argument("--target")
    parser.add_argument("--min-frames", type=int, default=3)
    parser.add_argument("--input-counts", type=_parse_counts, default=(16,))
    parser.add_argument("--target-count", type=int, default=128)
    parser.add_argument("--pairs-per-group", type=int, default=4)
    parser.add_argument("--seed", type=int, default=20260821)
    parser.add_argument("--method", choices=("average", "sigma_clip"), default="average")
    parser.add_argument("--kappa", type=float, default=2.5)
    parser.add_argument("--stretch", type=float, default=None)
    parser.add_argument("--workers", type=int, default=None)
    parser.add_argument("--max-groups", type=int, default=None)
    parser.add_argument("--include-mosaics", action="store_true")
    parser.add_argument("--tiles", action="store_true", help="Also write compressed training tiles")
    parser.add_argument("--tile-size", type=int, default=512)
    parser.add_argument("--tile-overlap", type=int, default=32)
    parser.add_argument("--min-tile-coverage", type=float, default=0.9)
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    config = PairConfig(
        input_counts=args.input_counts,
        target_count=args.target_count,
        pairs_per_group=args.pairs_per_group,
        seed=args.seed,
        method=args.method,
        kappa=args.kappa,
        stretch_amount=args.stretch,
        tile_size=args.tile_size,
        tile_overlap=args.tile_overlap,
        min_tile_coverage=args.min_tile_coverage,
        write_tiles=args.tiles,
        overwrite=args.overwrite,
    )
    results = generate_training_pairs(
        args.input,
        args.output,
        config=config,
        sensor=args.sensor,
        filter_name=args.filter_name,
        exposure_s=args.exposure_s,
        target=args.target,
        min_frames=args.min_frames,
        include_mosaics=args.include_mosaics,
        workers=args.workers,
        max_groups=args.max_groups,
        on_progress=print,
    )
    print(json.dumps(results, indent=2, sort_keys=True))
    return 0 if not any(
        pair.get("status") == "failed"
        for group in results
        for pair in group.get("pairs", [])
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
