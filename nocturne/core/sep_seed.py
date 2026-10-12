"""Make sep's star detection repeatable on Windows.

sep reseeds its random generator to 1 on every extract() call (extract.c:296),
and its deblending step draws from it (deblend.c:366). On Windows a
compatibility macro (sepcore.h:102, `#define rand_r(SEED) rand()`) drops that
seed, so deblending draws from the thread's own C random stream, which nothing
resets: the same frame gave 758–764 stars from call to call on a reused thread,
grading metrics shifted by up to 0.35%, and stack masters were not bit-
reproducible (measured 2026-10-12, sep 1.3.8–1.4.1). The Mac gives 762 every
time.

Reseeding the C runtime to 1 before each call restores what sep itself intends.
Installed once, on Windows only, before anything uses sep — astroalign included,
since it looks `sep.extract` up at call time.
"""
from __future__ import annotations

import os

_installed = False


def install() -> bool:
    """Wrap sep.extract on Windows; a no-op elsewhere. True when wrapped."""
    global _installed
    if _installed or os.name != "nt":
        return _installed
    try:
        import ctypes

        import sep
        srand = ctypes.cdll.ucrtbase.srand
    except Exception:
        return False
    original = sep.extract

    def extract(*args, **kwargs):
        srand(1)
        return original(*args, **kwargs)

    extract.__wrapped__ = original
    extract.__doc__ = original.__doc__
    sep.extract = extract
    _installed = True
    return True
