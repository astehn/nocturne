from __future__ import annotations

import os

from .core.crop import detect_content_bounds
from .core.export import save_fits, save_png, save_tiff
from .core.tasks import current as current_token
from .recipe import Recipe, deserialize_option
from .steps.factory import make_step
from .steps.load import load_fits
from .tools.base import run_cli

_EXPORTERS = {"TIFF": (save_tiff, ".tiff"), "PNG": (save_png, ".png"), "FITS": (save_fits, ".fits")}


def output_path(path: str, output_dir: str, fmt: str) -> str:
    """Where `path`'s processed result gets written. Shared with the dialog's
    pre-check so the two can never disagree about what collides."""
    stem = os.path.splitext(os.path.basename(path))[0]
    return os.path.join(output_dir, stem + _EXPORTERS[fmt][1])


def overwrites_source(path: str, output_dir: str, fmt: str) -> bool:
    """Would processing `path` write over `path` itself?

    The input glob accepts .fit/.fits/.fts and FITS export always writes .fits,
    so output folder = input folder + Format=FITS destroys the user's stacked
    master — hours of capture, no undo, no prompt.

    Not a string compare of folder names: the output folder can reach the input
    folder through a symlink, a `..`, or a trailing slash and still be the same
    directory, so both sides go through realpath. And realpath is not enough on
    its own — macOS APFS is case-insensitive by default, where m42.FITS and
    m42.fits are ONE file, which only an inode compare of a destination that
    already exists can see.
    """
    dest = output_path(path, output_dir, fmt)
    if os.path.exists(dest):
        try:
            return os.path.samefile(path, dest)
        except OSError:
            pass
    return os.path.realpath(dest) == os.path.realpath(path)


def apply_recipe(base, recipe: Recipe, settings, *, bg_runner=run_cli, rc_runner=run_cli):
    """Run a recipe's steps on a loaded image, headless. Crop auto-detects the
    border per image."""
    img = base
    for step in recipe.steps:
        sid = step["stage"]
        option = deserialize_option(sid, step["option"])
        if sid == "enhance":
            from .core.enhance import (ENHANCE_OPS, sharpen_nebulosity_layers,
                                       star_colour_layers)
            op = option
            # Two taps work on the SPLIT layers rather than the whole frame:
            # Star Colour lifts saturation on the stars, Sharpen Nebulosity
            # sharpens the starless layer. Neither is in ENHANCE_OPS, so both
            # need the split here — Sharpen Nebulosity was missing, and adding
            # it to the recipe registry without this branch would have turned
            # "this tap cannot be saved" into a KeyError mid-batch.
            layered = {"Star Colour": star_colour_layers,
                       "Sharpen Nebulosity": sharpen_nebulosity_layers}
            if op in layered:
                from .core.starless import split_stars
                starless, stars = split_stars(img)     # free split in batch (per spec)
                img = layered[op](starless, stars)
            else:
                img = ENHANCE_OPS[op](img)
            continue
        st = make_step(sid, settings, bg_runner=bg_runner, rc_runner=rc_runner)
        if sid == "crop":
            option.bounds = detect_content_bounds(img)
        img = st.apply(img, option)
    return img


def run_batch(recipe, input_paths, output_dir, fmt, settings, *,
              on_progress=None, bg_runner=run_cli, rc_runner=run_cli) -> list:
    exporter = _EXPORTERS[fmt][0]
    results = []
    n = len(input_paths)
    for i, path in enumerate(input_paths):
        # Between files, not inside one: a half-written export is worse than
        # finishing the frame in flight. Cancelled is a BaseException, so it
        # passes straight through the per-file `except Exception` below.
        token = current_token()
        if token is not None:
            token.check()
        try:
            # Before the recipe runs, not after: a guard that still burns a
            # GraXpert run per file before saying no costs most of what the bug
            # costs. One bad destination fails that file only — the rest of the
            # batch carries on, per the existing per-file results contract.
            if overwrites_source(path, output_dir, fmt):
                raise ValueError("would overwrite the source file — choose a "
                                 "different output folder or format")
            out = apply_recipe(load_fits(path), recipe, settings,
                               bg_runner=bg_runner, rc_runner=rc_runner)
            exporter(out, output_path(path, output_dir, fmt))
            results.append({"path": path, "ok": True, "message": ""})
        except Exception as exc:
            results.append({"path": path, "ok": False, "message": str(exc)})
        if on_progress is not None:
            on_progress(i + 1, n, path)
    return results
