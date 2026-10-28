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
    if getattr(sys, "frozen", False):
        return os.path.join(getattr(sys, "_MEIPASS", ""), "nrengine")
    return _SOURCE_DIR


# Read at call time so tests can repoint it.
ENGINE_DIR = _default_dir()

TILE_SHAPE = (1, 3, 256, 256)
_TEXT_CAP = 4096


class EngineError(RuntimeError):
    pass


def _library_name() -> str:
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
        buf = ctypes.create_string_buffer(_TEXT_CAP)
        rc = self._lib.nr_info(self._handle, buf, _TEXT_CAP)
        if rc != 0:
            raise EngineError(f"could not read model info (code {rc})")
        return json.loads(buf.value.decode("utf-8"))

    def run(self, tile: np.ndarray) -> np.ndarray:
        tile = np.asarray(tile)
        if tile.shape != TILE_SHAPE:
            raise EngineError(f"tile must be shaped {TILE_SHAPE}, got {tile.shape}")
        if tile.dtype != np.float32:
            raise EngineError(f"tile must be float32, got {tile.dtype}")
        tile = np.ascontiguousarray(tile, dtype=np.float32)
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
_cache_lock = threading.Lock()


def load() -> Engine | None:
    """The engine, or None when it is absent or will not load. Never raises."""
    global _cached
    with _cache_lock:
        if _cached is not _UNSET:
            return _cached
        _cached = _load_uncached()
        return _cached


def _load_uncached() -> Engine | None:
    path = os.path.join(ENGINE_DIR, _library_name())
    if not os.path.isfile(path):
        return None
    try:
        return Engine(ctypes.CDLL(path))
    except Exception as exc:  # OSError, AttributeError on a missing symbol
        _log.warning("NR engine present but not loadable: %s", exc)
        return None
