"""ctypes wrapper around the Nocturne NR engine library.

The engine opens signed, encrypted .nnr models and runs them a tile at a time.
It is optional: when the library is absent or will not load, `load()` returns
None and the app simply offers no engine models. Pure — no Qt.
"""
from __future__ import annotations

import ctypes
import json
import logging
import os
import sys
import threading

import numpy as np

_log = logging.getLogger("nocturne.nr_engine")

_SOURCE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "assets", "engine")


def _default_dir() -> str:
    """Frozen apps carry the engine beside the bundle; source runs use assets/."""
    if getattr(sys, "frozen", False):
        return os.path.join(getattr(sys, "_MEIPASS", ""), "nrengine")
    return _SOURCE_DIR


# Read at call time so tests can repoint it.
ENGINE_DIR = _default_dir()

TILE_SHAPE = (1, 3, 256, 256)
_TEXT_CAP = 4096          # version strings and open() error sentences
_INFO_CAP = 64 * 1024 + 1  # info() echoes a header, which nnr allows up to 64 KiB


class EngineError(RuntimeError):
    """Anything the engine refuses; callers show it, they do not branch on it."""


def _library_name() -> str:
    """The platform's file name; the engine is one flat C library per OS."""
    if sys.platform == "darwin":
        return "libnrengine.dylib"
    if sys.platform.startswith("win"):
        return "nrengine.dll"
    return "libnrengine.so"


_RUN_ERRORS = {
    -1: "the model handle is closed or invalid",
    -3: "the model refused the run",
    -4: "the engine failed unexpectedly",
}


class EngineModel:
    """One opened model. Safe to call from any thread; the engine serialises runs."""

    def __init__(self, lib, handle):
        self._lib = lib
        self._handle = ctypes.c_void_p(handle)
        self._closed = False
        self._lock = threading.Lock()

    def info(self) -> dict:
        buf = ctypes.create_string_buffer(_INFO_CAP)
        rc = self._lib.nr_info(self._handle, buf, _INFO_CAP)
        if rc != 0:
            raise EngineError(f"could not read model info (code {rc})")
        return json.loads(buf.value.decode("utf-8"))

    def run(self, tile: np.ndarray) -> np.ndarray:
        tile = np.asarray(tile)
        if tile.shape != TILE_SHAPE:
            raise EngineError(f"tile must be shaped {TILE_SHAPE}, got {tile.shape}")
        if tile.dtype != np.float32:
            raise EngineError(f"tile must be float32, got {tile.dtype}")
        tile = np.ascontiguousarray(tile)
        out = np.empty(TILE_SHAPE, dtype=np.float32)
        rc = self._lib.nr_run(
            self._handle,
            tile.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
            out.ctypes.data_as(ctypes.POINTER(ctypes.c_float)))
        if rc != 0:
            raise EngineError(_RUN_ERRORS.get(rc, f"engine error {rc}"))
        return out

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._lib.nr_close(self._handle)


class Engine:
    """The loaded library; binds the C signatures once so a bad pointer width cannot truncate."""

    def __init__(self, lib):
        self._lib = lib
        lib.nr_version.argtypes = [ctypes.c_char_p, ctypes.c_size_t]
        lib.nr_version.restype = ctypes.c_int
        lib.nr_open.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_size_t]
        lib.nr_open.restype = ctypes.c_void_p
        lib.nr_info.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t]
        lib.nr_info.restype = ctypes.c_int
        lib.nr_run.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_float),
                               ctypes.POINTER(ctypes.c_float)]
        lib.nr_run.restype = ctypes.c_int
        lib.nr_close.argtypes = [ctypes.c_void_p]
        lib.nr_close.restype = None

    def version(self) -> dict:
        buf = ctypes.create_string_buffer(_TEXT_CAP)
        rc = self._lib.nr_version(buf, _TEXT_CAP)
        if rc != 0:
            raise EngineError(f"could not read engine version (code {rc})")
        return json.loads(buf.value.decode("utf-8"))

    def open(self, path: str) -> EngineModel:
        err = ctypes.create_string_buffer(_TEXT_CAP)
        handle = self._lib.nr_open(os.fsencode(path), err, _TEXT_CAP)
        if not handle:
            msg = err.value.decode("utf-8", "replace") or "the engine could not open the model"
            raise EngineError(msg)
        return EngineModel(self._lib, handle)


_UNSET = object()
_cached = _UNSET
_error = ""               # why the cached None is None, when the library was there
_cache_lock = threading.Lock()


def load() -> Engine | None:
    """The engine, or None when it is absent or will not load. Never raises."""
    global _cached
    with _cache_lock:
        if _cached is not _UNSET:
            return _cached
        _cached = _load_uncached()
        return _cached


def load_error() -> str:
    """Why a present engine would not load ("" when it loaded or is absent).

    The user must not read "not installed" when the file is right there and
    something else stopped it — on Windows, a missing VC++ runtime.
    """
    load()
    return _error if _cached is None else ""


def usable() -> bool:
    """Whether opening a model can succeed in this process.

    A release engine opens models only inside the frozen app, so in a source run
    (a deploy leaves one in assets/engine/) it loads fine and then refuses every
    model. Offering those would fail on the first tile; only a dev engine runs
    from source.
    """
    engine = load()
    if engine is None:
        return False
    if getattr(sys, "frozen", False):
        return True
    try:
        return engine.version().get("variant") == "dev"
    except Exception:  # EngineError, bad JSON: not usable, never a crash
        return False


def _load_uncached() -> Engine | None:
    global _error
    _error = ""
    path = os.path.join(ENGINE_DIR, _library_name())
    if not os.path.isfile(path):
        return None
    try:
        if hasattr(os, "add_dll_directory"):  # Windows: find onnxruntime.dll beside it
            os.add_dll_directory(ENGINE_DIR)
        return Engine(ctypes.CDLL(path))
    except Exception as exc:  # OSError, AttributeError on a missing symbol
        _log.warning("NR engine present but not loadable: %s", exc)
        _error = str(exc) or type(exc).__name__
        return None
