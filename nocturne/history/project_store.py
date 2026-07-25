from __future__ import annotations

import io
import json
import os
import tempfile
import zipfile
from dataclasses import dataclass
from typing import Any

import numpy as np

from ..core.image import AstroImage
from ..core.tasks import current as _current_token
from ..recipe import _NAME_TO_STAGE, deserialize_option, serialize_option
from ..settings import Settings
from ..steps.factory import make_step

try:
    from .. import __version__ as _APP_VERSION
except ImportError:                    # pragma: no cover - defensive only
    _APP_VERSION = None

FORMAT_VERSION = 1


class NewerVersionError(Exception):
    """Raised when a `.nocturne` bundle's manifest format_version is newer than
    this build of Nocturne understands how to read."""


@dataclass
class LoadedProject:
    project: Any            # nocturne.history.project.Project
    solve_state: Any
    source_label: str

_REPRODUCIBLE_STAGES = {
    "stretch", "levels", "curves", "recover_core",
    "local_contrast", "remove_green", "rotate", "flip_h", "flip_v",
}   # NOTE: crop excluded — serialize_option drops its bounds.


def _ensure_serialized(stage, option):
    """Uniform JSON option, whether it came from run_step (native) or
    record_precomputed (already serialized)."""
    if option is None or isinstance(option, (int, float, str, bool)):
        return option
    if isinstance(option, dict):
        return option
    if isinstance(option, (list, tuple)):
        return list(option)
    return serialize_option(stage, option)     # native object (CropParams/ColorSettings/…)


def is_reproducible(stage, option) -> bool:
    if stage in _REPRODUCIBLE_STAGES:
        return True
    ser = _ensure_serialized(stage, option)
    if stage == "color":
        return isinstance(ser, dict) and ser.get("method") == "sky"
    if stage == "saturation":
        try:
            return float(ser[1]) == 0.0
        except Exception:
            return False
    return False       # crop, background, deconvolution, noise_sharpen, star-split steps, …


def _stage_for(name: str) -> str:
    """Map a record's display name (e.g. 'Stretch') to its stage id (e.g. 'stretch')."""
    return _NAME_TO_STAGE.get(name, name)


def _normalize_metadata(value):
    """Recursively coerce numpy scalar/array values in a metadata dict to plain
    JSON-safe Python types (float/int/list/...), so a value that happens to be a
    numpy type (e.g. computed by a processing step) survives save/load as the
    same type instead of falling back to `json.dumps(..., default=str)` and
    coming back as a string. Applied wherever metadata is written into the
    manifest (base + cached steps); non-numpy values pass through unchanged."""
    if isinstance(value, dict):
        return {k: _normalize_metadata(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize_metadata(v) for v in value]
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    return value


def _array_to_bytes(arr: np.ndarray) -> bytes:
    buf = io.BytesIO()
    np.save(buf, arr)
    return buf.getvalue()


def save_project(project, path, *, solve_state=None, source_label: str = "",
                  on_progress=None) -> None:
    """Write `project`'s full undo history (up to its current position) as a
    `.nocturne` zip bundle: the base image, a manifest describing every
    recorded step, and cached npy snapshots for the steps that aren't
    reproducibly re-runnable from their serialized option alone.

    Writes to a temp file in the same directory as `path` and atomically
    `os.replace`s it into place on success, so a slow, cancelled, or failed
    save can never corrupt (or even touch) an existing bundle at `path`.

    `on_progress(done, total)`, if given, is called after each zip member is
    written (base + one per cached step + manifest); `total` is fixed up
    front. Cancellation is checked (via the ambient `CancelToken`, if any)
    at the same points — a `Cancelled` raised there aborts the write and
    cleans up the temp file, leaving any pre-existing `path` untouched."""
    entries = list(project.entries())
    serialized = []   # [(stage, ser, cached), ...] computed once, reused for total + the write loop
    for name, option in entries:
        stage = _stage_for(name)
        ser = _ensure_serialized(stage, option)
        serialized.append((stage, ser, not is_reproducible(stage, ser)))
    total = 1 + sum(1 for _, _, cached in serialized if cached) + 1   # base + cached steps + manifest
    done = 0

    def _tick():
        nonlocal done
        done += 1
        if on_progress is not None:
            on_progress(done, total)
        tok = _current_token()
        if tok is not None:
            tok.check()

    directory = os.path.dirname(path) or "."
    fd, tmp_path = tempfile.mkstemp(prefix=".nocturne-save-", dir=directory)
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zf:
            base = project.state_at(0)
            zf.writestr("base.npy", _array_to_bytes(base.data))
            _tick()

            steps = []
            for i, (name, option) in enumerate(entries):
                stage, ser, cached = serialized[i]
                entry = {"name": name, "stage": stage, "option": ser, "cached": cached, "cache": None}
                if cached:
                    snapshot = project.state_at(i + 1)
                    cache_name = f"cache/{i:03d}.npy"
                    zf.writestr(cache_name, _array_to_bytes(snapshot.data))
                    entry["cache"] = cache_name
                    entry["is_linear"] = snapshot.is_linear
                    entry["metadata"] = _normalize_metadata(snapshot.metadata)
                    _tick()
                steps.append(entry)

            manifest = {
                "format_version": FORMAT_VERSION,
                "app_version": _APP_VERSION,
                "position": project.position,
                "source_label": source_label,
                "solve": solve_state,
                "base": {"is_linear": base.is_linear, "metadata": _normalize_metadata(base.metadata)},
                "steps": steps,
            }
            zf.writestr("manifest.json", json.dumps(manifest, default=str))
            _tick()
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


def _bytes_to_array(data: bytes) -> np.ndarray:
    return np.load(io.BytesIO(data))


def load_project(path: str, cache_dir: str) -> LoadedProject:
    """Read a `.nocturne` bundle and rebuild a live `Project`: the base image
    is loaded straight from its embedded npy, then each recorded step is
    either replayed (deterministic stages, re-run through `make_step` /
    `run_step` from the serialized option) or restored from its cached npy
    snapshot (`record_precomputed`) — reproducing every history position
    pixel-for-pixel."""
    from .project import Project  # local import: avoids a history/project_store <-> project cycle

    with zipfile.ZipFile(path) as zf:
        manifest = json.loads(zf.read("manifest.json"))

        format_version = manifest.get("format_version", 1)
        if format_version > FORMAT_VERSION:
            raise NewerVersionError(
                f"bundle format_version {format_version} is newer than this build "
                f"supports (max {FORMAT_VERSION})"
            )

        base_data = _bytes_to_array(zf.read("base.npy"))
        base_info = manifest["base"]
        base = AstroImage(base_data, is_linear=base_info["is_linear"], metadata=base_info["metadata"])
        project = Project(base, cache_dir)

        settings = Settings()
        for step in manifest["steps"]:
            if step["cached"]:
                data = _bytes_to_array(zf.read(step["cache"]))
                img = AstroImage(data, is_linear=step["is_linear"], metadata=step["metadata"])
                project.record_precomputed(step["name"], step["option"], img)
            else:
                native = deserialize_option(step["stage"], step["option"])
                step_obj = make_step(step["stage"], settings)
                project.run_step(step_obj, native)

        project.jump_back(manifest["position"])

    return LoadedProject(
        project=project,
        solve_state=manifest.get("solve"),
        source_label=manifest.get("source_label", ""),
    )
