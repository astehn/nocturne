"""Unattended overnight runner: work a queue of training experiments end to
end (build -> train -> evaluate -> gate -> report) while nobody is watching,
and leave a report that says whether last night was progress.

Built for exactly one failure mode: an experiment crashing at 1am must cost
that ONE config, not the rest of the night.

  * `train.py` and `export_onnx.py` are run as SUBPROCESSES, not imported --
    both are scripts with their own sys.exit/SystemExit paths and a global
    stdout redirect (train.py's Tee), neither of which should be allowed to
    take this process down or bleed into the next config's log.
  * `run_queue` additionally wraps each `runner(cfg)` call in its own
    try/except, so even an in-process failure (a corrupt checkpoint, a
    missing file during evaluation) is caught and recorded as ONE failed
    experiment rather than a dead queue.

`stage()` is the other half of "unattended", and it deliberately stops one
step short of shipping. The 2026-08-23 run passed its own gate and promoted a
model that still damaged a real 405-frame master; the gate is stronger now,
but the deep-end proxy is explicitly blind to anything that is not
chroma-shaped, so "passed" still does not mean "safe". This runner therefore
has no destination to ship to at all -- it copies into run_dir/staged/ and a
person runs training/promote.py after reading the morning report. The copy is
still atomic, so a laptop going to sleep mid-copy cannot leave a half-written
.onnx for the promote step to pick up.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import build_dataset  # noqa: E402
import data as D  # noqa: E402
from gate import DepthResult, check_no_harm  # noqa: E402
from report import render_comparison_sheet, write_report  # noqa: E402

_TRAINING_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _TRAINING_DIR.parent
_DEFAULT_RUN_ROOT = Path("/Volumes/Work2/Images/Astro/denoise_runs")

# Subprocesses must run under the SAME interpreter this process was launched
# with (.venv-train, per CLAUDE.md) -- sys.executable IS that interpreter,
# since nightly.py is itself required to run under it.
_PYTHON = sys.executable

# The one real deep stack on this machine: no ground truth exists for it (it
# IS the deepest stack there is), and it is the exact master the 2026-08-22
# model damaged. Every run is checked against it, truth-free, via gate's
# chroma proxy -- a held-out-pair gate cannot reach this depth by construction.
_M8_MASTER = "/Volumes/Work2/Images/Astro/Work/M8 Total/lights/M8_405x10s_68min.fits"
_M8_DEPTH = 405

_PAIR_DIR_RE = re.compile(r"_in(\d+)_target(\d+)$")
_GROUP_DIR_RE = re.compile(r"^(?:s30|s50)_([^_]+)_")


@dataclass
class ExperimentResult:
    name: str
    status: str  # "ok" or "error"
    run_dir: str | None = None
    report_path: str | None = None
    gate_passed: bool | None = None
    staged: bool = False
    duration_s: float = 0.0
    error: str | None = None


# ----------------------------------------------------------------- staging

def _atomic_copy(src: Path, dst: Path) -> None:
    """Copy src to dst so a reader of dst never observes a partial file.

    Writes to a sibling temp name -- one that a glob for *.onnx/*.json would
    never match, so a crash mid-copy leaves debris the app's own lookups
    ignore -- then renames into place with os.replace, which POSIX guarantees
    is atomic on the same filesystem.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.parent / f".{dst.name}.tmp{os.getpid()}"
    try:
        shutil.copyfile(src, tmp)
        os.replace(tmp, dst)
    finally:
        if tmp.exists():
            tmp.unlink()


def stage(run_dir, gate_passed: bool, sensor: str = "s30") -> bool:
    """Put this run's ONNX where a human can promote it -- never where the app looks.

    The 2026-08-23 run passed its gate and shipped a model that still damaged a
    real 405-frame master. The gate is stronger now, but the deep-end proxy is
    explicitly blind to anything that is not chroma-shaped, so "passed" still
    does not mean "safe". Shipping is a decision a person makes after looking
    at the morning report; use training/promote.py.

    The gate is checked FIRST, before touching the filesystem at all, so a
    stale model.onnx left in run_dir by an earlier passing attempt cannot be
    staged on a later failing run's say-so.
    """
    if not gate_passed:
        return False
    run_dir = Path(run_dir)
    onnx_src = run_dir / "model.onnx"
    if not onnx_src.is_file():
        return False  # e.g. export never ran (smoke, or an earlier failure)
    staged = run_dir / "staged"
    json_src = run_dir / "model.json"
    if json_src.is_file():
        _atomic_copy(json_src, staged / f"denoise_{sensor}_v1.json")
    _atomic_copy(onnx_src, staged / f"denoise_{sensor}_v1.onnx")
    return True


# ----------------------------------------------------------- run history

def _metrics_path(run_dir) -> Path:
    return Path(run_dir) / "metrics.json"


def _load_previous_metrics(run_dir) -> dict | None:
    p = _metrics_path(run_dir)
    if not p.is_file():
        return None
    with open(p) as fh:
        return json.load(fh)


def _save_metrics(run_dir, metrics: list[dict]) -> None:
    """Persist this run's metrics, keyed ONLY as "target:depth".

    report._previous_key() prefers a target-qualified key and falls back to a
    plain depth for a caller that never had a target to qualify with. If a
    saved history ever carried BOTH forms for the same depth, that fallback
    could match the wrong entry when two targets share a depth. This is the
    one place that writes the history file nightly.py itself reads back as
    `previous`, and it emits the qualified form exclusively -- the ambiguity
    report.py's reviewer flagged can't arise because the fallback key never
    exists in anything nightly.py writes.
    """
    keyed = {f"{m['target']}:{m['depth']}": m for m in metrics}
    Path(run_dir).mkdir(parents=True, exist_ok=True)
    with open(_metrics_path(run_dir), "w") as fh:
        json.dump(keyed, fh, indent=2)


# ------------------------------------------------------------ pair identity

def _pair_identity(pair_dir: str) -> tuple[str, int]:
    """(target, input_depth) parsed from the directory layout build_dataset /
    nocturne.training.pairs writes -- must match build_dataset._pair_dir's
    naming and FrameGroup.slug's "sensor_target_..." convention exactly, or a
    gate result silently attaches to the wrong target.
    """
    pair_dir = str(pair_dir).rstrip("/")
    base = os.path.basename(pair_dir)
    group = os.path.basename(os.path.dirname(pair_dir))
    m_pair = _PAIR_DIR_RE.search(base)
    m_group = _GROUP_DIR_RE.match(group)
    if not (m_pair and m_group):
        raise ValueError(f"cannot parse target/depth from pair dir: {pair_dir}")
    return m_group.group(1), int(m_pair.group(1))


def select_gate_pairs(pair_dirs, max_pairs) -> list[str]:
    """The pairs the do-no-harm gate will actually be run on.

    The design's gate is "every held-out target at every depth", so
    `max_pairs=None` -- the default for a real run -- returns all of them. The
    gate is the only thing between an unattended run and overwriting the model
    the app ships, and a gate that samples is not a gate.

    A config that DOES cap the count (smoke runs, a quick look) gets a
    deliberate subset rather than an accident of string sorting: plain sorted()
    puts `in16` before `in1` ('6' < '_'), which handed all three slots of the
    old cap to one target at depths 16/1/2 and never evaluated the second
    held-out target at all. Instead spend the budget deepest-first -- the deep
    end is where the shipped model actually did harm -- while round-robining
    across targets so no held-out target is skipped entirely.
    """
    ordered = sorted(pair_dirs, key=lambda d: (_pair_identity(d)[0], _pair_identity(d)[1], d))
    if max_pairs is None:
        return ordered

    by_target: dict[str, list[str]] = {}
    for d in ordered:
        by_target.setdefault(_pair_identity(d)[0], []).append(d)
    # deepest first within each target, then take one target at a time in turn
    queues = [sorted(v, key=lambda d: (-_pair_identity(d)[1], d)) for _, v in sorted(by_target.items())]
    chosen: list[str] = []
    while len(chosen) < int(max_pairs) and any(queues):
        for q in queues:
            if not q:
                continue
            chosen.append(q.pop(0))
            if len(chosen) >= int(max_pairs):
                break
    return sorted(chosen, key=lambda d: (_pair_identity(d)[0], _pair_identity(d)[1], d))


def _evaluate_pair_with_images(pair_dir, model, device, strength):
    """metrics dict (evaluate.evaluate_pair) plus the raw linear-space images
    render_comparison_sheet needs -- evaluate_pair only returns numbers."""
    import evaluate as E
    from astropy.io import fits

    inp = E._hwc(fits.getdata(os.path.join(pair_dir, "input.fits")))
    tgt = E._hwc(fits.getdata(os.path.join(pair_dir, "target.fits")))
    a = D._ASINH_A
    out = D.from_model_space(E.apply_model(D.to_model_space(inp, a), model, device, strength), a)
    metrics = E.evaluate_pair(pair_dir, model, device, strength)
    return inp, out, tgt, metrics


# -------------------------------------------------------------- one config

def _train_command(cfg: dict, dataset_dir, run_dir, smoke: bool) -> list[str]:
    """Build train.py's argv. `--pairs` is ALWAYS explicit here: train.py's
    own default points at the old, superseded dataset
    (/Volumes/Work2/Images/Astro/TrainingPairs), not at what build_dataset.py
    produces -- omitting it would silently train on the wrong data."""
    cmd = [
        _PYTHON, str(_TRAINING_DIR / "train.py"),
        "--pairs", str(dataset_dir),
        "--out", str(run_dir),
        "--sensor", cfg.get("sensor", "s30"),
        "--epochs", str(cfg.get("epochs", 300)),
    ]
    for flag, key in (("--batch", "batch"), ("--crop", "crop"), ("--lr", "lr"),
                       ("--base", "base"), ("--workers", "workers"),
                       ("--sample-every", "sample_every")):
        if key in cfg:
            cmd += [flag, str(cfg[key])]
    if smoke:
        cmd.append("--smoke")
    elif cfg.get("resume", True):
        cmd.append("--resume")
    return cmd


def _run_subprocess(cmd: list[str], *, on_line=print) -> None:
    on_line("$ " + " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.stdout:
        on_line(proc.stdout.rstrip("\n"))
    if proc.returncode != 0:
        tail = "\n".join((proc.stdout + proc.stderr).splitlines()[-40:])
        raise RuntimeError(f"{os.path.basename(cmd[1])} exited {proc.returncode}\n{tail}")


# --------------------------------------------------------- the deep end

def _deep_end_result(model, device, strength: float):
    """The truth-free deep-end check, as a DepthResult the gate can consume.

    Returns None only if the master is not on this machine -- the caller must
    treat that as "not verified", never as a pass.

    The sky mask is taken from the INPUT and reused for the model output, so
    both sides are measured over the same pixels; a mask recomputed on the
    output would let a model that flattens the nebula move the goalposts under
    itself. The stretch matters too: the bias is invisible in linear data --
    that is what every prior relative-to-truth test missed -- and only becomes
    the visible blotching once stretched the way a user would see it.
    """
    if not os.path.isfile(_M8_MASTER):
        return None
    from astropy.io import fits

    import evaluate
    import gate
    from evaluate import _hwc
    from nocturne.core.autostretch import linked_stretch

    inp = _hwc(fits.getdata(_M8_MASTER))
    a = D._ASINH_A
    out = D.from_model_space(
        evaluate.apply_model(D.to_model_space(inp, a), model, device, strength=strength), a)
    sky = gate.sky_mask(inp)
    return DepthResult(
        "M8-deep-proxy", _M8_DEPTH,
        gate.patch_chroma_bias(linked_stretch(inp, 0.25), sky),
        gate.patch_chroma_bias(linked_stretch(out, 0.25), sky),
    )


def _with_deep_end(depth_results, deep, on_line=print):
    """The result set the gate is handed -- or nothing at all, if the deep end
    could not be measured.

    An unverified deep end must not be allowed to pass on the held-out pairs'
    say-so: those top out far below the depth the user actually works at, and
    that gap is precisely how the 2026-08-22 model shipped. check_no_harm
    refuses an empty set, so returning [] fails the run rather than skipping
    the check.
    """
    if deep is None:
        on_line("WARNING: deep-end proxy unavailable (M8 master not mounted) "
                "\u2014 gate cannot pass")
        return []
    return list(depth_results) + [deep]


def run_one(cfg: dict, *, on_line=print) -> ExperimentResult:
    """One experiment, end to end: build -> train -> evaluate -> gate -> report
    -> (export + stage iff the gate passed and this isn't a smoke run).

    Staging is as far as this goes: nothing here ships a model."""
    t0 = time.time()
    name = cfg["name"]
    smoke = bool(cfg.get("smoke", False))
    sensor = cfg.get("sensor", "s30")
    run_root = Path(cfg.get("run_root", _DEFAULT_RUN_ROOT))
    run_dir = run_root / name
    on_line(f"=== {name} ===  smoke={smoke}")

    dataset_dir = build_dataset._DEFAULT_DATASET_ROOT / cfg["name"]
    if smoke:
        # Real registration/stacking of raw frames is minutes to hours, not
        # the "whole pipeline in under a minute" a smoke run promises -- so
        # smoke assumes the dataset already exists (built by a prior REAL
        # run of this config) and only re-checks the fast half of the
        # pipeline: train -> evaluate -> gate -> report.
        if not dataset_dir.is_dir():
            raise RuntimeError(
                f"--smoke needs an already-built dataset at {dataset_dir}; "
                "run this config for real first (a non-smoke nightly run, "
                "or build_dataset.py directly).")
    else:
        build_dataset.build_dataset(cfg, max_groups=cfg.get("max_groups"), on_line=on_line)

    previous = _load_previous_metrics(run_dir)

    _run_subprocess(_train_command(cfg, dataset_dir, run_dir, smoke), on_line=on_line)

    import torch
    from model import DenoiseUNet

    device = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
    ck_name = "best.pt" if (run_dir / "best.pt").is_file() else "last.pt"
    ck = torch.load(run_dir / ck_name, map_location=device)
    model = DenoiseUNet(base=ck.get("args", {}).get("base", 32)).to(device)
    model.load_state_dict(ck["model"])
    model.eval()

    strength = float(cfg.get("strength", 1.0))
    max_pairs = cfg.get("max_pairs", 1 if smoke else None)
    tiles = D.scan_tiles(str(dataset_dir))
    _, _, test_tiles = D.split_by_target(tiles, sensor)
    pair_dirs = select_gate_pairs(
        {os.path.dirname(os.path.dirname(t.path)) for t in test_tiles}, max_pairs)
    if not pair_dirs:
        raise RuntimeError(f"no held-out (test-split) pairs found under {dataset_dir}")

    depth_results, metrics, rows = [], [], []
    for pd in pair_dirs:
        target, depth = _pair_identity(pd)
        inp, out, tgt, m = _evaluate_pair_with_images(pd, model, device, strength)
        dr = DepthResult(target, depth, m["noisy"]["err"], m["model"]["err"])
        depth_results.append(dr)
        metrics.append(dr._asdict())
        rows.append((f"{target} @ {depth}f", tgt, [("noisy", inp), ("model", out), ("truth", tgt)]))

    deep = _deep_end_result(model, device, strength)
    if deep is not None:
        metrics.append(deep._asdict())
    depth_results = _with_deep_end(depth_results, deep, on_line=on_line)

    gate_result = check_no_harm(depth_results, tolerance=float(cfg.get("gate_tolerance", 0.0)))

    images = []
    if rows:
        render_comparison_sheet(rows, str(run_dir / "comparison.png"))
        images.append("comparison.png")

    report_path = write_report(str(run_dir), gate_result, metrics, images, previous=previous)
    _save_metrics(run_dir, metrics)

    staged = False
    if not smoke and gate_result.passed:
        export_cmd = [
            _PYTHON, str(_TRAINING_DIR / "export_onnx.py"),
            "--run", str(run_dir),
            "--out", str(run_dir / "model.onnx"),
        ]
        _run_subprocess(export_cmd, on_line=on_line)
        staged = stage(str(run_dir), gate_result.passed, sensor=sensor)
        on_line(f"STAGED at {run_dir / 'staged'} \u2014 NOT shipped. "
                f"Review the report, then: "
                f".venv-train/bin/python training/promote.py --run {run_dir}")

    return ExperimentResult(
        name=name, status="ok", run_dir=str(run_dir), report_path=report_path,
        gate_passed=gate_result.passed, staged=staged, duration_s=time.time() - t0,
    )


# ------------------------------------------------------------------- queue

def run_queue(configs, runner=None, on_line=print) -> list[ExperimentResult]:
    """Run every config, isolating a crash to the one experiment it happened
    in -- the queue must reach config N even if config N-1 blew up at 1am."""
    runner = runner or run_one
    results: list[ExperimentResult] = []
    for cfg in configs:
        name = cfg.get("name", "?") if isinstance(cfg, dict) else getattr(cfg, "name", "?")
        t0 = time.time()
        try:
            result = runner(cfg)
        except Exception as exc:  # noqa: BLE001 -- this is the isolation boundary
            on_line(f"[{name}] FAILED: {type(exc).__name__}: {exc}")
            result = ExperimentResult(
                name=name, status="error", error=f"{type(exc).__name__}: {exc}",
                duration_s=time.time() - t0,
            )
        results.append(result)
    return results


def write_queue_summary(results: list[ExperimentResult], out_path) -> str:
    """The morning's punch list: one row per config, before anyone opens the
    per-config report.md files."""
    lines = ["# Nightly run summary", "", time.strftime("%Y-%m-%d %H:%M:%S"), ""]
    lines.append("| config | status | gate | staged | duration |")
    lines.append("|---|---|---|---|---|")
    for r in results:
        gate = "PASS" if r.gate_passed else ("FAIL" if r.gate_passed is False else "—")
        mins = r.duration_s / 60.0
        lines.append(f"| {r.name} | {r.status} | {gate} | {'yes' if r.staged else 'no'} | {mins:.1f} min |")
        if r.error:
            lines.append(f"|  | error: `{r.error[:200]}` | | | |")
        if r.report_path:
            lines.append(f"|  | [report]({r.report_path}) | | | |")
    lines.append("")
    ok = sum(1 for r in results if r.status == "ok")
    staged = sum(1 for r in results if r.staged)
    lines.append(f"{ok}/{len(results)} configs completed; {staged} staged "
                 "(staged is not shipped \u2014 promote with training/promote.py).")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n")
    return str(out_path)


# --------------------------------------------------------------------- CLI

def _load_config(path: str) -> dict:
    with open(path) as fh:
        return json.load(fh)


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Run one or a queue of denoise training experiments unattended."
    )
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--queue", help="directory of *.json configs, run in sorted filename order")
    g.add_argument("--config", help="a single config JSON file")
    ap.add_argument("--smoke", action="store_true",
                    help="fast pipeline sanity check on already-built data; never stages")
    ap.add_argument("--summary-out", default=None,
                    help="where to write the combined report (default: run_root/nightly_summary.md)")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)

    if args.queue:
        paths = sorted(Path(args.queue).glob("*.json"))
        if not paths:
            print(f"no configs found in {args.queue}")
            return 1
        configs = [_load_config(str(p)) for p in paths]
    else:
        configs = [_load_config(args.config)]

    if args.smoke:
        for cfg in configs:
            cfg["smoke"] = True

    results = run_queue(configs)

    summary_out = args.summary_out or str(_DEFAULT_RUN_ROOT / "nightly_summary.md")
    write_queue_summary(results, summary_out)

    for r in results:
        status = "OK" if r.status == "ok" else "ERROR"
        extra = f"  {r.error}" if r.error else ""
        print(f"{r.name}: {status}  gate={r.gate_passed}  staged={r.staged}  "
              f"({r.duration_s:.0f}s){extra}")
    print(f"summary: {summary_out}")

    return 0 if all(r.status == "ok" for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
