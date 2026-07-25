from __future__ import annotations

from ..recipe import serialize_option

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
