"""One background stack at a time, each in its own process.

A stack holds ~8.7 GB for a 100 MB image (TODO:708, measured on a 1233-frame
run). Two at once would exceed 17 GB before the app's own footprint, so this
runs one and queues the rest — a memory guarantee, not a preference.

The child speaks the newline-delimited JSON protocol from `nocturne/stacking/
job.py` (v0.30.0), read here on a reader thread so the UI never waits on a pipe.
That thread **emits and nothing else**: every mutation of the queue, and every
spawn, happens on the GUI thread, reached through the private `_child_exited`
signal with a queued connection. The queue is therefore owned by one thread and
the one-at-a-time guard in `_pump` needs no lock — a lock would be a second
mechanism for the same invariant, and two mechanisms drift.

Cancellation goes through `kill_process`, which kills the process GROUP: the
stacker spawns its own worker pool, and killing only the direct child would
leave those workers holding the memory this whole design exists to reclaim.
That requires the child to be spawned with `start_new_session=True` so it (and
not Nocturne itself) leads its own process group.

`cancel` kills and then waits: SIGTERM does not reap, so the dying child still
holds its 8.7 GB. The slot stays occupied until the child's own death reaches
`_on_child_done`, which is the single path that promotes the next job.
"""
from __future__ import annotations

import dataclasses
import json
import subprocess
import tempfile
import threading
import time
import os

from PySide6.QtCore import QCoreApplication, QEventLoop, QObject, Qt, Signal

from ..core.tasks import kill_process
from ..stacking.job import job_command

# closeEvent's bound on waiting for a reader thread to finish at quit.
# Measured 2026-09-11 on a real 80-frame NGC 281 cancel: the child died under
# 1 s after SIGTERM. 5 s is generous headroom above that, short enough that a
# genuinely stuck child doesn't hang the app on quit forever. `cancel_all`
# only ever sends SIGTERM and `wait_for_shutdown` never escalates past it, so
# hitting this bound means the app can exit while that child is still alive,
# still holding its ~8.7 GB. See JobQueue.wait_for_shutdown.
_SHUTDOWN_TIMEOUT = 5.0


@dataclasses.dataclass
class StackJob:
    label: str
    options: object                 # StackOptions
    state: str = "queued"           # queued | running | done | failed | cancelled


def _event(line: str):
    """The line as a protocol event, or None if it is not one.

    Dependencies print to stdout, and `null`, `123` and `[1, 2]` are all valid
    JSON that is not an event. Returning None for them is what keeps a stray
    line from killing the reader — and a dead reader leaves its job "running"
    for ever, with no signal ever emitted for it.
    """
    try:
        obj = json.loads(line)
    except ValueError:
        return None
    return obj if isinstance(obj, dict) else None


def _discard(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


class JobQueue(QObject):
    progress = Signal(object, int, str)      # job, percent, phase
    finished = Signal(object, dict)          # job, the "done" event
    failed = Signal(object, str)             # job, message
    changed = Signal()                       # the list or a state moved

    # Private: the reader thread's only way back into the queue.
    _child_exited = Signal(object, object, object)   # job, returncode, final

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._jobs: list[StackJob] = []
        self._running: StackJob | None = None
        self._proc = None
        # Reader threads still alive, tracked so quit can join them for real
        # instead of just marking jobs cancelled — see wait_for_shutdown.
        self._reader_threads: list[threading.Thread] = []
        self._child_exited.connect(self._on_child_done,
                                   Qt.ConnectionType.QueuedConnection)

    # --- model ---
    def jobs(self) -> list:
        return list(self._jobs)

    def running(self):
        return self._running

    def busy(self) -> bool:
        """True if a foreground stack anywhere in the app must not start —
        this job (or the next one in line) may still be writing a file a
        fresh dialog's own output-path guess could collide with. See
        StackDialog's `queue_busy`, the only consumer: `_set_busy`/mosaic
        already keep two clicks on ONE dialog from racing each other, but a
        FRESH StackDialog starts with `_busy = False` and knows nothing about
        this queue on its own."""
        return self._running is not None or any(
            j.state == "queued" for j in self._jobs)

    # --- control (GUI thread only) ---
    def enqueue(self, job: StackJob) -> None:
        self._jobs.append(job)
        self.changed.emit()
        self._pump()

    def cancel(self, job: StackJob) -> None:
        """Kill, and let the child's death drive the queue.

        Promoting the next job here instead would start it while the killed
        child still held its 8.7 GB — SIGTERM does not wait — and would give
        the queue two paths that spawn.
        """
        if job is self._running:
            job.state = "cancelled"
            self.changed.emit()
            if self._proc is not None:
                kill_process(self._proc)     # the GROUP: the stacker has workers
            return
        if job.state == "queued":
            job.state = "cancelled"
            self.changed.emit()

    def cancel_all(self) -> None:
        """Mark everything first, then kill once.

        Cancelling job by job let each cancellation promote the next one, so
        stopping a 5-deep queue launched four interpreters in order to kill
        them — in answer to the user asking it to stop.
        """
        running = self._running
        for job in self._jobs:
            if job.state in ("queued", "running"):
                job.state = "cancelled"
        self.changed.emit()
        if running is not None and self._proc is not None:
            kill_process(self._proc)

    def wait_for_shutdown(self, timeout: float = _SHUTDOWN_TIMEOUT) -> None:
        """For quit, after cancel_all(): join the live reader thread(s) and
        pump the queued `_child_exited` signal so it is DELIVERED — not just
        emitted — while this QObject is still alive.

        `_read`'s emit() can succeed and post the event, then have the event
        delivered after this object is torn down by the closing window; that
        is a use-after-free on the C++ side, not a Python exception, so no
        try/except anywhere can guard it. Joining the thread first guarantees
        the emit already happened before we pump events for it.

        Bounded: a child that ignores SIGTERM must not hang the app on quit
        forever. If the deadline passes we stop waiting and forget the slot
        locally anyway — nothing will call `_pump()` again once we're
        quitting, so there is no double-spawn risk, only the (rare, accepted)
        chance that thread's eventual emit lands after this object is gone.
        """
        deadline = time.monotonic() + timeout
        for t in list(self._reader_threads):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            t.join(remaining)
        app = QCoreApplication.instance()
        if app is not None:
            # Called from closeEvent, so this is also pumping whatever else
            # is queued (an update check landing, save-progress ticks) — not
            # just our own _child_exited. ExcludeUserInputEvents keeps a
            # stray click/keypress from being delivered mid-close; it does
            # not affect our own queued signal, which isn't user input.
            app.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
        self._running = None
        self._proc = None

    # --- running (GUI thread only) ---
    def _pump(self) -> None:
        while self._running is None:
            job = next((j for j in self._jobs if j.state == "queued"), None)
            if job is None:
                return
            job.state = "running"
            try:
                proc = self._spawn(job)
            except Exception as exc:
                # Popen fails with ENOMEM/EMFILE exactly when it is most
                # likely: right after 8.7 GB was resident. Letting that
                # propagate out of enqueue() left the queue believing for ever
                # that something was running.
                job.state = "failed"
                self.failed.emit(job, f"could not start stacking: {exc}")
                self.changed.emit()
                continue
            self._running = job
            self._proc = proc
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
        try:
            with os.fdopen(fd, "w") as f:
                f.write(json.dumps(dataclasses.asdict(job.options)))
            proc = subprocess.Popen(
                job_command(path),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, start_new_session=True)
        except BaseException:
            _discard(path)          # no reader will ever reach its cleanup
            raise
        try:
            t = threading.Thread(target=self._read, args=(job, proc, path),
                                 daemon=True)
            t.start()
            self._reader_threads.append(t)
        except BaseException:
            kill_process(proc)      # nothing would read it, reap it, or kill it
            _discard(path)
            raise
        return proc

    # --- the reader thread: emits, and nothing else ---
    def _read(self, job: StackJob, proc, opts_path: str) -> None:
        """Runs off the GUI thread, so it must not touch the queue's state.

        It reports the child's exit through `_child_exited`, a queued signal,
        and every guard below exists so that emit is always reached: a reader
        that dies wedges its job as "running" for ever.
        """
        last = None
        try:
            for line in proc.stdout:
                try:
                    obj = self._on_line(job, line.strip())
                except Exception:
                    continue        # one bad line costs one line, not the job
                if obj is not None and obj.get("event") in ("done", "error"):
                    last = obj
        except Exception:
            pass                    # a broken pipe, or the window closed on us
        code = None
        try:
            code = proc.wait()
        except Exception:
            pass
        _discard(opts_path)
        try:
            self._child_exited.emit(job, code, last)
        except RuntimeError:
            pass                    # the C++ JobQueue is gone; no one to tell

    def _on_line(self, job: StackJob, line: str):
        """Returns the parsed event so the reader parses each line once."""
        obj = _event(line)
        if obj is None:
            return None             # a stray print must not kill a job
        if obj.get("event") == "progress":
            self.progress.emit(job, int(obj.get("done", 0)),
                               str(obj.get("phase", "")))
        return obj

    # --- the single completion path (GUI thread, via _child_exited) ---
    def _on_child_done(self, job: StackJob, code, final) -> None:
        cancelled = job.state == "cancelled"
        if job is self._running:
            # Freed before the emits, so a handler asking running() during one
            # is told the truth. The child is reaped by now, so its memory has
            # actually gone.
            self._running = None
            self._proc = None
        if not cancelled:
            if code == 0 and final and final.get("event") == "done":
                job.state = "done"
                self.finished.emit(job, final)
            else:
                job.state = "failed"
                msg = ((final or {}).get("message")
                       or f"stacking stopped (exit {code})")
                self.failed.emit(job, msg)
        # The emit() that reaches this callback is `_read`'s LAST statement,
        # so its thread is normally already finished by now — but emit() on a
        # queued connection only posts the event and returns, so that is not
        # a hard guarantee, just the common case. Filtering on `is_alive()`
        # rather than assuming it means a thread that hasn't quite finished
        # yet is simply left for the next prune, and a long session still
        # doesn't accumulate one dead Thread object per stack ever run.
        self._reader_threads = [t for t in self._reader_threads if t.is_alive()]
        self.changed.emit()
        self._pump()
