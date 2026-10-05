"""Nocturne NR post-stretch denoise models: which are installed, and running one.

The models come from the separate Nocturne NR project, which trains and delivers
them and never touches this code. What this module does at inference is fixed
by that project's contract (Nocturne NR/docs/model-contract.md, 2026-10-05),
written from the code that trained and judged the models: the app must feed
exactly what training saw, or the judged quality is not what the user gets.
Every number below is the contract's, not a choice made here.

Pure — no Qt. onnxruntime is imported lazily, because the installed app does not
carry it yet and a model is offered only where it can actually run.
"""
from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import dataclass

import numpy as np

from .image import AstroImage
from .tasks import current as _current_token
from .tasks import report_progress

# Models that ship inside the app (none yet; the folder need not exist). They
# win over a tray model with the same id, so a release never runs a stale copy.
_REAL_SHIPPED_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                 "assets", "models", "nr")
SHIPPED_DIR = _REAL_SHIPPED_DIR
# The testing tray the Nocturne NR session delivers to (<id>.onnx + <id>.json).
_REAL_TRAY_DIR = os.path.join(os.path.expanduser("~"), ".nocturne", "models")
TRAY_DIR = _REAL_TRAY_DIR
# Both are read at call time, so the test suite can point them at empty folders
# (tests/conftest.py) and never see the models on the developer's machine.

PREFIX = "nr:"          # an engine option naming a model by its stable id
LOG_PREFIX = "NR:"      # what NoiseSharpenStep.last_engine records

# Contract §d — as trained and judged.
TILE, OVERLAP = 256, 32
STEP = TILE - OVERLAP


@dataclass(frozen=True)
class NRModel:
    id: str          # stable; what history and recipes store
    name: str        # display name; may change between deliveries
    path: str        # the .onnx
    shipped: bool


def _natural(s: str):
    """v9 before v18 before v100 — the order the deliveries were made in."""
    return [(0, int(t), "") if t.isdigit() else (1, 0, t) for t in re.split(r"(\d+)", s) if t]


def _read(onnx_path: str, shipped: bool) -> NRModel | None:
    stem = os.path.basename(onnx_path)[:-len(".onnx")]
    try:
        with open(os.path.join(os.path.dirname(onnx_path), stem + ".json")) as fh:
            meta = json.load(fh)
    except (OSError, ValueError):
        return None          # no JSON = an older linear model; bad JSON = not offered
    # Contract §a: only a 3-input post-stretch model at the trained tile runs here.
    if (not isinstance(meta, dict) or meta.get("space") != "stretched"
            or meta.get("inputs") != 3 or meta.get("tile", TILE) != TILE):
        return None
    mid, name = meta.get("id"), meta.get("name")
    # Deliveries before v20 carry neither; the stem stands in for both.
    mid = mid if isinstance(mid, str) and mid else stem
    name = name if isinstance(name, str) and name else stem
    return NRModel(mid, name, onnx_path, shipped)


def discover(dirs=None) -> list[NRModel]:
    """Every post-stretch model on disk, earlier dirs first, natural order within.

    Reads only the JSON beside each file — no ONNX load — so listing stays cheap
    enough to do whenever a panel is built. The first model with an id wins.
    """
    shipped_dir = os.path.abspath(SHIPPED_DIR)
    if dirs is None:
        dirs = [SHIPPED_DIR, TRAY_DIR]
    seen: set[str] = set()
    out: list[NRModel] = []
    for d in dirs:
        try:
            names = os.listdir(d)
        except OSError:
            continue
        shipped = os.path.abspath(d) == shipped_dir
        found = [m for m in (_read(os.path.join(d, n), shipped)
                             for n in names if n.endswith(".onnx")) if m is not None]
        for m in sorted(found, key=lambda m: _natural(m.id)):
            if m.id not in seen:
                seen.add(m.id)
                out.append(m)
    return out


def runtime_available() -> bool:
    try:
        import onnxruntime  # noqa: F401
    except Exception:
        # Not just ImportError: a half-present native library raises OSError (or
        # worse) on import, and that must read as "not available", not crash
        # every panel build.
        return False
    return True


def available() -> list[NRModel]:
    """What Noise Reduction may offer: on disk AND runnable in this build."""
    return discover() if runtime_available() else []


def find(model_id: str) -> NRModel | None:
    return next((m for m in discover() if m.id == model_id), None)


def engine_label(model_id: str, *, bare: bool = False) -> str:
    """How a log line or report names the model: "Nocturne NR — Odin (v20.0)".

    `bare` drops the id's own parentheses ("Nocturne NR — Odin v20.0") for the
    log line, which already wraps the engine in the step's own — three levels
    of brackets read as a bug.

    The name is looked up NOW, so a renamed model reads with its new name; a
    removed one still reads by its id, which is all the history ever stored.
    """
    m = find(model_id)
    if m is None or m.name == m.id:
        return f"Nocturne NR — {model_id}"
    return f"Nocturne NR — {m.name} {m.id}" if bare else f"Nocturne NR — {m.name} ({m.id})"


def not_installed(model_id: str) -> str:
    return f"Nocturne NR {model_id} is not installed"


_SESSIONS: dict = {}
_SESSIONS_LOCK = threading.Lock()


def _session(path: str):
    """One InferenceSession per model file; building one costs more than a tile."""
    st = os.stat(path)
    key = (path, st.st_mtime_ns, st.st_size)
    with _SESSIONS_LOCK:
        sess = _SESSIONS.get(key)
        if sess is None:
            import onnxruntime as ort
            sess = ort.InferenceSession(path, providers=["CPUExecutionProvider"])
            _SESSIONS[key] = sess
        return sess


def _feather() -> np.ndarray:
    """Contract §d: a ramp over 32 edge pixels per side that never reaches 0."""
    ramp = np.ones(TILE, np.float32)
    edge = np.linspace(0, 1, OVERLAP + 2, dtype=np.float32)[1:-1]
    ramp[:OVERLAP], ramp[-OVERLAP:] = edge, edge[::-1]
    return (ramp[:, None] * ramp[None, :])[:, :, None]


def _origins(n: int) -> list[int]:
    """Contract §d: the last tile sits flush with the edge."""
    return [min(v, n - TILE) for v in range(0, max(n - OVERLAP, 1), STEP)]


def denoise(img: AstroImage, strength: float, model: NRModel) -> AstroImage:
    """Contract §b–§d, exactly: raw stretched pixels in (no app-side
    normalisation — the graph does its own), `tile − strength·noise` out,
    feathered blend, clip [0, 1].

    Two things the contract leaves to the app: a mono image is repeated to three
    channels and averaged back, and an image smaller than a tile is reflect-padded
    to one and cropped back (the contract's recommendation — the reference would
    index out of range there).
    """
    if img.is_linear:
        raise ValueError("Nocturne NR runs after Stretch — it was trained on "
                         "stretched data, and this image is still linear")
    if not os.path.isfile(model.path):
        raise FileNotFoundError(not_installed(model.id))
    if strength <= 0:
        return AstroImage(img.data.copy(), is_linear=False, metadata=dict(img.metadata))
    if not runtime_available():
        raise RuntimeError("Nocturne NR needs onnxruntime, which this build does not include")

    sess = _session(model.path)
    inp = sess.get_inputs()[0]
    if list(inp.shape) != [1, 3, TILE, TILE]:
        raise RuntimeError(f"Nocturne NR {model.id}: expected a 1×3×256×256 input, "
                           f"the model takes {inp.shape}")

    src = np.ascontiguousarray(img.data, np.float32)
    mono = src.ndim == 2
    if mono:
        src = np.repeat(src[:, :, None], 3, axis=2)
    H, W, _ = src.shape
    if H < TILE or W < TILE:
        src = np.pad(src, ((0, max(TILE - H, 0)), (0, max(TILE - W, 0)), (0, 0)),
                     mode="reflect")
    h, w, _ = src.shape

    # float32 accumulators, as the reference does, so results match it bit for bit.
    out = np.zeros_like(src)
    wsum = np.zeros((h, w, 1), np.float32)
    win = _feather()
    ys, xs = _origins(h), _origins(w)
    total, done = len(ys) * len(xs), 0
    token = _current_token()
    for y0 in ys:
        for x0 in xs:
            if token is not None:
                token.check()
            patch = src[y0:y0 + TILE, x0:x0 + TILE]
            noise = sess.run(None, {inp.name: np.ascontiguousarray(
                patch.transpose(2, 0, 1)[None])})[0][0]
            out[y0:y0 + TILE, x0:x0 + TILE] += (patch - strength * noise.transpose(1, 2, 0)) * win
            wsum[y0:y0 + TILE, x0:x0 + TILE] += win
            done += 1
            report_progress(done, total)
    data = np.clip(out / np.maximum(wsum, 1e-6), 0, 1)[:H, :W]
    if mono:
        data = data.mean(axis=2)
    return AstroImage(data.astype(np.float32), is_linear=False, metadata=dict(img.metadata))
