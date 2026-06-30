from __future__ import annotations

import os

from .core.crop import detect_content_bounds
from .core.export import save_fits, save_png, save_tiff
from .recipe import Recipe, deserialize_option
from .steps.factory import make_step
from .steps.load import load_fits
from .tools.base import run_cli

_EXPORTERS = {"TIFF": (save_tiff, ".tiff"), "PNG": (save_png, ".png"), "FITS": (save_fits, ".fits")}


def apply_recipe(base, recipe: Recipe, settings, *, bg_runner=run_cli, rc_runner=run_cli):
    """Run a recipe's steps on a loaded image, headless. Crop auto-detects the
    border per image."""
    img = base
    for step in recipe.steps:
        sid = step["stage"]
        option = deserialize_option(sid, step["option"])
        st = make_step(sid, settings, bg_runner=bg_runner, rc_runner=rc_runner)
        if sid == "crop":
            option.bounds = detect_content_bounds(img)
        img = st.apply(img, option)
    return img


def run_batch(recipe, input_paths, output_dir, fmt, settings, *,
              on_progress=None, bg_runner=run_cli, rc_runner=run_cli) -> list:
    exporter, ext = _EXPORTERS[fmt]
    results = []
    n = len(input_paths)
    for i, path in enumerate(input_paths):
        try:
            out = apply_recipe(load_fits(path), recipe, settings,
                               bg_runner=bg_runner, rc_runner=rc_runner)
            stem = os.path.splitext(os.path.basename(path))[0]
            exporter(out, os.path.join(output_dir, stem + ext))
            results.append({"path": path, "ok": True, "message": ""})
        except Exception as exc:
            results.append({"path": path, "ok": False, "message": str(exc)})
        if on_progress is not None:
            on_progress(i + 1, n, path)
    return results
