"""PyInstaller entry point — imports the package properly and launches.

This file, not nocturne/__main__.py, is what the bundle runs: the spec names it
as SCRIPT. `from nocturne.__main__ import main` IMPORTS that module, so anything
guarded by its `if __name__ == "__main__"` block never executes in the shipped
app — which is how freeze_support() came to be present in the source and absent
from the bundle.
"""
import multiprocessing

# The only two module-level imports, and both are cheap by design: this file's
# BODY runs in every spawned pool worker, top to bottom, before the worker
# reaches the freeze_support() line that tells it what it is. `nocturne.dock`
# is ctypes and nothing else; `nocturne/__init__` is constants. `main` is
# imported further down, after that line — see there for why.

from nocturne.dock import leave_the_dock

if __name__ == "__main__":
    # BEFORE freeze_support(), which a spawned worker never returns from: it
    # runs the worker's task and exits. Anything below it protects the main app
    # only, and it is the WORKERS that were showing up in the Dock — eleven
    # Nocturne icons for one stack (see nocturne/dock.py). Decides for itself
    # whether this process is a headless child, so the app keeps its own tile.
    leave_the_dock()

    # MUST come before main() — before Qt, before any window. (The Dock
    # call above it does nothing but flip this process's LaunchServices
    # type; it starts nothing and cannot swallow a worker's task.)
    #
    # Stacking registers frames in a process pool and macOS SPAWNS rather than
    # forks, so each worker re-executes this bundle. Without freeze_support()
    # that means the app relaunching itself — a window per worker, recursively.
    # It fails ONLY in the built .app: a dev run and the whole test suite are
    # both silent about it.
    multiprocessing.freeze_support()

    # BELOW freeze_support, deliberately. `nocturne.__main__` imports
    # QApplication, QIcon and MainWindow at module level, so while this import
    # sat at the top of the file every registration worker built the entire GUI
    # — theme, panels, curve editor — and then exited without using any of it.
    # Measured 2026-09-17: 69 MB and ~0.5 s per worker, 551 MB across the eight
    # a stack uses here. On a 16 GB laptop the worker count is MEMORY-limited
    # (plan_workers reports its limiter), so that is not just waste, it is
    # fewer workers and a slower stack.
    #
    # Safe because a worker never gets here: freeze_support() runs its task and
    # calls sys.exit(). Order is the whole mechanism, so it is pinned by
    # tests/test_dock.py::test_the_entry_point_imports_the_gui_after_freeze_support.
    from nocturne.__main__ import main
    main()
