"""The morning report: what an unattended overnight run produced.

Verdict first, images second, tables last -- not alphabetical, deliberate. Numbers
alone have misled before: a change scored well on every metric while visibly
ruining every star in the image (see gate.py). So the reader gets the pass/fail
call in three seconds, then the same side-by-side crops that actually caught that
kind of damage, and only then the numbers for when the pictures raise a question.

The diff against the previous run is the point of the whole file. Without it
there is no way to tell whether last night was progress or just "a bit here, a
bit there" with no visible direction -- the exact complaint that started this
project.
"""
from __future__ import annotations

import os


def _fmt(v) -> str:
    """Small numbers (errors, ~1e-4) as scientific; everything else plain."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, float):
        return f"{v:.3e}" if 0 < abs(v) < 1e-2 else f"{v:.4f}"
    return str(v)


def _pct_change(previous_err: float, current_err: float) -> float:
    """Negative = error went down = improvement; matches "lower is better"."""
    if not previous_err:
        return float("nan")
    return (current_err - previous_err) / previous_err * 100.0


def _previous_key(metric: dict, previous: dict) -> str | None:
    """Prefer a target-qualified key so two targets at the same depth don't
    collide; fall back to plain depth, which is the only form a caller with a
    single target (the brief's own test) has any reason to produce."""
    target, depth = metric.get("target"), metric.get("depth")
    qualified = f"{target}:{depth}"
    if target is not None and qualified in previous:
        return qualified
    if str(depth) in previous:
        return str(depth)
    return None


def _diff_cell(metric: dict, previous: dict | None) -> str:
    if not previous or "model_err" not in metric:
        return ""
    key = _previous_key(metric, previous)
    if key is None:
        return ""
    prev = previous[key]
    if "model_err" not in prev:
        return ""
    pct = _pct_change(prev["model_err"], metric["model_err"])
    return f"{pct:.1f}%"


def render_comparison_sheet(rows, out_path: str, cell: int = 220) -> str:
    """One PNG: one row per (target, depth) comparison, panels side by side.

    Each row gets exactly ONE display stretch, derived once from that row's
    truth image and reused for every panel in the row -- noisy input, model
    output, and the truth panel itself all go through the identical transfer
    function. Nocturne's autostretch derives its parameters from each image's
    OWN median and MAD, so letting a smoother (denoised, or deeper-stack)
    panel stretch itself would render it differently for reasons that have
    nothing to do with the model -- the exact trap `compare_visual.py`
    documents and works around, reused here rather than reimplemented (an
    earlier reimplementation inverted the midtones solve and rendered every
    panel black).

    `rows`: list of (title, truth_hwc, panels), panels a list of
    (label, array_hwc_or_hw). Grid is one row per entry, one column per panel
    (rows may have different panel counts; the sheet is sized to the widest).
    """
    import numpy as np
    from PIL import Image, ImageDraw

    from nocturne.core.autostretch import _apply_params, _stretch_params

    def stretch(img, shadow, m):
        img = np.asarray(img, np.float32)
        if img.ndim == 2:
            return _apply_params(img, shadow, m)
        return np.stack(
            [_apply_params(img[..., c], shadow, m) for c in range(img.shape[2])],
            axis=2,
        )

    if not rows:
        raise ValueError("render_comparison_sheet needs at least one row")

    label_h = 18
    ncols = max(len(panels) for _, _, panels in rows)
    sheet = Image.new(
        "RGB", (cell * ncols, (cell + label_h) * len(rows)), (10, 12, 16)
    )
    dr = ImageDraw.Draw(sheet)

    for r, (title, truth, panels) in enumerate(rows):
        truth = np.asarray(truth, np.float32)
        lum = truth.mean(axis=2) if truth.ndim == 3 else truth
        shadow, m = _stretch_params(lum)
        y = r * (cell + label_h)
        for c, (label, arr) in enumerate(panels):
            disp = np.clip(stretch(arr, shadow, m), 0.0, 1.0)
            if disp.ndim == 2:
                disp = np.stack([disp] * 3, axis=2)
            pil = Image.fromarray((disp * 255 + 0.5).astype(np.uint8)).resize(
                (cell, cell), Image.NEAREST
            )
            x = c * cell
            sheet.paste(pil, (x, y))
            dr.text((x + 4, y + cell + 2), f"{title} — {label}", fill=(205, 212, 226))

    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    sheet.save(out_path)
    return out_path


def write_report(run_dir, gate, metrics, images, previous=None) -> str:
    """Assemble report.md: verdict, then images, then metrics tables.

    `gate`: a `gate.GateResult`. `metrics`: list of dicts (whatever keys the
    caller has -- typically target/depth/input_err/model_err, a DepthResult's
    fields as a dict). `images`: paths to already-rendered comparison PNGs
    (see `render_comparison_sheet`), embedded as markdown images relative to
    `run_dir`. `previous`: the prior run's metrics keyed by depth (or
    "target:depth" -- see `_previous_key`), or None for "no previous run",
    which is reported explicitly rather than silently omitted -- the first
    night of a new ladder is a legitimate state, not an error.
    """
    verdict = "PASS" if gate.passed else "FAIL"
    lines = [f"# VERDICT: {verdict}", ""]

    if gate.passed:
        lines.append("Do-no-harm gate passed at every depth checked. Safe to promote.")
    else:
        n = len(gate.failures)
        lines.append(
            f"Do-no-harm gate FAILED ({n} case{'s' if n != 1 else ''}) — "
            "do NOT promote this model."
        )
        lines.append("")
        lines.extend(f"- {f}" for f in gate.failures)
    lines.append("")

    lines.append("## Comparison")
    lines.append("")
    if images:
        for img in images:
            lines.append(f"![{os.path.basename(str(img))}]({img})")
            lines.append("")
    else:
        lines.append("_No comparison images for this run._")
        lines.append("")

    lines.append("## Metrics" + (" vs previous run" if previous is not None else ""))
    lines.append("")
    if metrics:
        cols: list[str] = []
        for m in metrics:
            for k in m:
                if k not in cols:
                    cols.append(k)
        header = cols + (["vs previous"] if previous is not None else [])
        lines.append("| " + " | ".join(header) + " |")
        lines.append("|" + "|".join(["---"] * len(header)) + "|")
        for m in metrics:
            row = [_fmt(m.get(c)) for c in cols]
            if previous is not None:
                row.append(_diff_cell(m, previous) or "—")
            lines.append("| " + " | ".join(row) + " |")
    else:
        lines.append("_No metrics recorded._")
    lines.append("")

    lines.append("## Previous run")
    lines.append("")
    if previous is None:
        lines.append("No previous run recorded — this is the first run of this ladder.")
    else:
        lines.append(f"Diffed against {len(previous)} depth(s) from the last run.")
    lines.append("")

    os.makedirs(run_dir, exist_ok=True)
    path = os.path.join(run_dir, "report.md")
    with open(path, "w") as fh:
        fh.write("\n".join(lines))
    return path
