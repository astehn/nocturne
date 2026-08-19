"""PyInstaller entry point — imports the package properly and launches.

This file, not nocturne/__main__.py, is what the bundle runs: the spec names it
as SCRIPT. `from nocturne.__main__ import main` IMPORTS that module, so anything
guarded by its `if __name__ == "__main__"` block never executes in the shipped
app — which is how freeze_support() came to be present in the source and absent
from the bundle.
"""
import multiprocessing

from nocturne.__main__ import main

if __name__ == "__main__":
    # MUST be first, before Qt or anything else.
    #
    # Stacking registers frames in a process pool and macOS SPAWNS rather than
    # forks, so each worker re-executes this bundle. Without freeze_support()
    # that means the app relaunching itself — a window per worker, recursively.
    # It fails ONLY in the built .app: a dev run and the whole test suite are
    # both silent about it.
    multiprocessing.freeze_support()
    main()
