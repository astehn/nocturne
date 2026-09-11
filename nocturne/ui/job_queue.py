"""One background stack at a time, each in its own process.

A stack holds ~8.7 GB for a 100 MB image (TODO:708, measured on a 1233-frame
run). Two at once would exceed 17 GB before the app's own footprint, so this
runs one and queues the rest — a memory guarantee, not a preference.

The child speaks the newline-delimited JSON protocol from `nocturne/stacking/
job.py` (v0.30.0), read here on a reader thread so the UI never waits on a pipe.
Cancellation goes through `kill_process`, which kills the process GROUP: the
stacker spawns its own worker pool, and killing only the direct child would
leave those workers holding the memory this whole design exists to reclaim.
That requires the child to be spawned with `start_new_session=True` so it (and
not Nocturne itself) leads its own process group.
"""
from __future__ import annotations

import dataclasses
import json
import subprocess
import sys
import tempfile
import threading
import os

from PySide6.QtCore import QObject, Signal

from ..core.tasks import kill_process
from ..stacking.job import job_command


@dataclasses.dataclass
class StackJob:
    label: str
    options: object                 # StackOptions
    state: str = "queued"           # queued | running | done | failed | cancelled


class JobQueue(QObject):
    progress = Signal(object, int, str)      # job, percent, phase
    finished = Signal(object, dict)          # job, the "done" event
    failed = Signal(object, str)             # job, message
    changed = Signal()                       # the list or a state moved

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._jobs: list[StackJob] = []
        self._running: StackJob | None = None
        self._proc = None

    # --- model ---
    def jobs(self) -> list:
        return list(self._jobs)

    def running(self):
        return self._running

    # --- control ---
    def enqueue(self, job: StackJob) -> None:
        self._jobs.append(job)
        self.changed.emit()
        self._pump()

    def cancel(self, job: StackJob) -> None:
        if job is self._running:
            job.state = "cancelled"
            self._running = None
            if self._proc is not None:
                kill_process(self._proc)     # the GROUP: the stacker has workers
                self._proc = None
            self.changed.emit()
            self._pump()
            return
        if job.state == "queued":
            job.state = "cancelled"
            self.changed.emit()

    def cancel_all(self) -> None:
        for job in list(self._jobs):
            if job.state in ("queued", "running"):
                self.cancel(job)

    # --- running ---
    def _pump(self) -> None:
        if self._running is not None:
            return                            # ONE at a time; see the module docstring
        for job in self._jobs:
            if job.state == "queued":
                job.state = "running"
                self._running = job
                self._proc = self._spawn(job)
                self.changed.emit()
                return

    def _spawn(self, job: StackJob):
        """Command built by `job_command`, not assembled here.

        `job_command` branches on `sys.frozen`: in the shipped .app
        `sys.executable` IS the app binary and knows `--stack-job` directly,
        but from source it's a bare interpreter that needs `-m nocturne`
        first. Building `[sys.executable, "--stack-job", path]` unconditionally
        would die on an unknown option before Nocturne is even imported when
        run from source.
        """
        fd, path = tempfile.mkstemp(prefix="nocturne_job_", suffix=".json")
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps(dataclasses.asdict(job.options)))
        proc = subprocess.Popen(
            job_command(path),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, start_new_session=True)
        threading.Thread(target=self._read, args=(job, proc, path),
                         daemon=True).start()
        return proc

    def _read(self, job: StackJob, proc, opts_path: str) -> None:
        last = None
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            self._on_line(job, line)
            try:
                obj = json.loads(line)
            except ValueError:
                continue                      # a stray print from a dependency
            if obj.get("event") in ("done", "error"):
                last = obj
        proc.wait()
        try:
            os.unlink(opts_path)
        except OSError:
            pass
        self._on_child_done(job, proc.returncode, last)

    def _on_line(self, job: StackJob, line: str) -> None:
        try:
            obj = json.loads(line)
        except ValueError:
            return                            # a stray print must not kill a job
        if obj.get("event") == "progress":
            self.progress.emit(job, int(obj.get("done", 0)),
                               str(obj.get("phase", "")))

    def _on_child_done(self, job: StackJob, code, final) -> None:
        if job.state == "cancelled":
            return                            # the user already dealt with it
        if code == 0 and final and final.get("event") == "done":
            job.state = "done"
            self.finished.emit(job, final)
        else:
            job.state = "failed"
            msg = (final or {}).get("message") or f"stacking stopped (exit {code})"
            self.failed.emit(job, msg)
        if job is self._running:
            self._running = None
            self._proc = None
        self.changed.emit()
        self._pump()
