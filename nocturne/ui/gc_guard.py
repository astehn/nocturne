"""Cyclic garbage is collected on the GUI thread only.

Python runs a collection in whichever thread allocates past the threshold.
Live previews run Python on pool threads every slider tick, so a dialog left
in a reference cycle could be destroyed on a pool thread — Qt widgets must die
on the GUI thread. Shown 2026-10-06: a QDialog in a cycle, collected inside a
run_async job, was freed on the pool thread; the same off-thread destruction
segfaulted the test suite (crash report 162453: ~QDialog on a pool thread).

`install(app)` turns automatic collection off and runs CPython's own
generational rule from a GUI-thread timer instead: generation 0 when its count
passes threshold 0, escalating to 1 and 2 as CPython does. Never a full collect
per tick; one at quit. Only the GUI process installs it — a stacking child or
a --check-* run never creates the QApplication."""
from __future__ import annotations

import gc

from PySide6.QtCore import QObject, QTimer

_INTERVAL_MS = 500


class _GuiCollector(QObject):
    def __init__(self, app, interval_ms: int) -> None:
        super().__init__(app)
        self._thresholds = gc.get_threshold()
        self._was_enabled = gc.isenabled()
        gc.disable()
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self.check)
        self._timer.start()
        app.aboutToQuit.connect(self.collect_all)

    def check(self) -> None:
        """CPython's rule, run here: a generation is collected once the one
        below it has been collected `threshold` times."""
        c0, c1, c2 = gc.get_count()
        t0, t1, t2 = self._thresholds
        if c0 <= t0:
            return
        gen = 0
        if c1 > t1:
            gen = 1
            if c2 > t2:
                gen = 2
        gc.collect(gen)

    def collect_all(self) -> None:
        gc.collect()

    def release(self) -> None:
        self._timer.stop()
        if self._was_enabled:
            gc.enable()


def install(app, interval_ms: int = _INTERVAL_MS) -> _GuiCollector:
    """Once per application; a second call returns the first guard."""
    existing = getattr(app, "_nocturne_gc_guard", None)
    if existing is not None:
        return existing
    guard = _GuiCollector(app, interval_ms)
    app._nocturne_gc_guard = guard
    return guard


def uninstall(app):
    """Back to automatic collection (tests). Returns the guard removed, if any."""
    guard = getattr(app, "_nocturne_gc_guard", None)
    if guard is None:
        return None
    app._nocturne_gc_guard = None
    app.aboutToQuit.disconnect(guard.collect_all)
    guard.release()
    guard.deleteLater()
    return guard
