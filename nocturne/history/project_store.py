from __future__ import annotations

import io
import json
import zipfile

import numpy as np

from ..recipe import _NAME_TO_STAGE, serialize_option

try:
    from .. import __version__ as _APP_VERSION
except ImportError:                    # pragma: no cover - defensive only
    _APP_VERSION = None

FORMAT_VERSION = 1

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


def _array_to_bytes(arr: np.ndarray) -> bytes:
    buf = io.BytesIO()
    np.save(buf, arr)
    return buf.getvalue()


def save_project(project, path, *, solve_state=None, source_label: str = "") -> None:
    """Write `project`'s full undo history (up to its current position) as a
    `.nocturne` zip bundle: the base image, a manifest describing every
    recorded step, and cached npy snapshots for the steps that aren't
    reproducibly re-runnable from their serialized option alone."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        base = project.state_at(0)
        zf.writestr("base.npy", _array_to_bytes(base.data))

        steps = []
        for i, (name, option) in enumerate(project.entries()):
            stage = _stage_for(name)
            ser = _ensure_serialized(stage, option)
            cached = not is_reproducible(stage, ser)
            entry = {"name": name, "stage": stage, "option": ser, "cached": cached, "cache": None}
            if cached:
                snapshot = project.state_at(i + 1)
                cache_name = f"cache/{i:03d}.npy"
                zf.writestr(cache_name, _array_to_bytes(snapshot.data))
                entry["cache"] = cache_name
                entry["is_linear"] = snapshot.is_linear
                entry["metadata"] = snapshot.metadata
            steps.append(entry)

        manifest = {
            "format_version": FORMAT_VERSION,
            "app_version": _APP_VERSION,
            "position": project.position,
            "source_label": source_label,
            "solve": solve_state,
            "base": {"is_linear": base.is_linear, "metadata": base.metadata},
            "steps": steps,
        }
        zf.writestr("manifest.json", json.dumps(manifest, default=str))
