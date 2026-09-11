"""Stack in a child process and report over stdout.

A stack holds ~8.7 GB for a 100 MB image and the app may run several in a night;
in a child, that memory returns to the OS on exit instead of sitting in the app's
heap for the session. The deliverable is a FILE — `run_stack` writes the master
to `output_path` — so the only thing that has to cross the boundary is a summary,
never pixels.

The protocol is the one RC-Astro progress introduced in v0.30.0: one JSON object
per line on stdout, read by the parent with `run_cli(on_line=...)`.
"""
from __future__ import annotations

import dataclasses
import json
import sys

from .stacker import StackOptions, run_stack


def options_from_json(text: str) -> StackOptions:
    """Rebuild StackOptions from the parent's JSON.

    Unknown keys RAISE rather than being dropped: a silently ignored option
    would stack with a setting the user did not choose and say nothing.
    """
    data = json.loads(text)
    known = {f.name for f in dataclasses.fields(StackOptions)}
    unknown = set(data) - known
    if unknown:
        raise ValueError(f"unknown stack options: {', '.join(sorted(unknown))}")
    return StackOptions(**data)


def emit(event: dict, out=None) -> None:
    """One JSON object per line, flushed — the parent reads this as it arrives,
    and a buffered stream would deliver an hour of progress at the end."""
    stream = sys.stdout if out is None else out
    stream.write(json.dumps(event) + "\n")
    stream.flush()


def run_job(text: str, out=None) -> int:
    """Run one stack. Returns the process exit code."""
    try:
        opts = options_from_json(text)
    except Exception as exc:                      # noqa: BLE001 - reported as data
        emit({"event": "error", "message": str(exc)}, out)
        return 2

    def on_progress(i: int, n: int, label: str) -> None:
        emit({"event": "progress", "done": int(i * 100 / n) if n else 0,
              "phase": label}, out)

    try:
        result = run_stack(opts, on_progress=on_progress)
    except Exception as exc:                      # noqa: BLE001 - reported as data
        emit({"event": "error", "message": str(exc)}, out)
        return 1
    emit({"event": "done", "output": result.output_path,
          "frames": result.frame_count,
          "seconds": float(result.integration_seconds),
          "rejected": [list(r) for r in result.rejected]}, out)
    return 0


def main(argv: list[str], out=None) -> int:
    """`--stack-job <options.json>`; the path holds the serialised StackOptions."""
    try:
        path = argv[argv.index("--stack-job") + 1]
        with open(path) as f:
            return run_job(f.read(), out)
    except Exception as exc:                      # noqa: BLE001 - reported as data
        emit({"event": "error", "message": str(exc)}, out)
        return 1


def job_command(options_path: str, frozen: bool | None = None) -> list[str]:
    """The other end of `main`'s argv contract — kept here so the two cannot drift.

    Frozen, `sys.executable` IS the app binary and knows `--stack-job`; `-m`
    there would re-launch the whole of Nocturne instead of running a job. From
    source `sys.executable` is a bare interpreter, which knows neither, so the
    module has to be named. The two cases are opposites, and getting the frozen
    one wrong is invisible until the packaged build ships.
    """
    if frozen is None:
        frozen = bool(getattr(sys, "frozen", False))
    head = [sys.executable] if frozen else [sys.executable, "-m", "nocturne"]
    return [*head, "--stack-job", options_path]
