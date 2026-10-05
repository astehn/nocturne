"""Nocturne NR post-stretch models: discovery and inference per the NR contract
(/Volumes/Work/Code/Nocturne NR/docs/model-contract.md, 2026-10-05).

The fixture `tests/fixtures/nr/tile_noise.onnx` (233 bytes) is a real ONNX graph
whose "noise" is `x - mean(x over H,W)` per channel — a closed form the tests
recompute in NumPy, and one whose answer DEPENDS ON WHERE EACH TILE SITS (every
tile has its own mean), so a wrong origin or weight cannot pass. Generated once
under .venv-train (torch 2.13), never at test time:

    class TileNoise(torch.nn.Module):
        def forward(self, x):
            return x - x.mean(dim=(2, 3), keepdim=True)
    torch.onnx.export(TileNoise(), torch.zeros(1, 3, 256, 256),
                      "tests/fixtures/nr/tile_noise.onnx", input_names=["x"],
                      output_names=["noise"], opset_version=17, dynamo=False)

The expected results are computed by `_contract()` below, written from the
contract's text (§d) rather than from nocturne/core/nr_models.py.
"""
import json
import pathlib
import shutil
import sys

import numpy as np
import pytest

from nocturne.core import nr_models
from nocturne.core.image import AstroImage
from nocturne.core.tasks import Cancelled, CancelToken, clear_ambient, set_ambient

FIXTURE = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "nr" / "tile_noise.onnx"

pytest.importorskip("onnxruntime")


# --- the contract, written out independently --------------------------------

def _contract_origins(n: int) -> list[int]:
    # "y in range(0, max(H - 32, 1), 224), clamped to H - 256"
    return [min(v, n - 256) for v in range(0, max(n - 32, 1), 224)]


def _contract_ramp() -> np.ndarray:
    r = np.ones(256)
    edge = np.linspace(0, 1, 34)[1:-1]          # 32 values, never 0 or 1
    r[:32], r[-32:] = edge, edge[::-1]
    return r


def _contract(img: np.ndarray, s: float) -> np.ndarray:
    """out = Σ (tile − s·noise)·w / Σ w, clip [0,1]; noise = tile − tile mean."""
    H, W, _ = img.shape
    w2 = np.outer(_contract_ramp(), _contract_ramp())[:, :, None]
    num = np.zeros((H, W, 3))
    den = np.zeros((H, W, 1))
    for y in _contract_origins(H):
        for x in _contract_origins(W):
            t = img[y:y + 256, x:x + 256].astype(np.float64)
            noise = t - t.mean(axis=(0, 1), keepdims=True)
            num[y:y + 256, x:x + 256] += (t - s * noise) * w2
            den[y:y + 256, x:x + 256] += w2
    assert den.min() > 0, "a pixel no tile covers"
    return np.clip(num / den, 0, 1)


def _model(tmp_path, stem="tile-noise", meta=None) -> nr_models.NRModel:
    shutil.copy(FIXTURE, tmp_path / f"{stem}.onnx")
    (tmp_path / f"{stem}.json").write_text(json.dumps(
        meta if meta is not None else {"space": "stretched", "inputs": 3, "tile": 256}))
    [m] = [m for m in nr_models.discover([str(tmp_path)]) if m.path.endswith(f"{stem}.onnx")]
    return m


def _stretched(h, w, seed=1, mono=False):
    rng = np.random.default_rng(seed)
    shape = (h, w) if mono else (h, w, 3)
    # A gradient plus noise, so neighbouring tiles have DIFFERENT means.
    yy = np.linspace(0, 1, h)[:, None]
    base = 0.15 + 0.5 * yy * np.linspace(0.2, 1, w)[None, :]
    if not mono:
        base = base[:, :, None] * np.array([1.0, 0.8, 0.6])
    return AstroImage((base + rng.normal(0, 0.05, shape)).clip(0, 1).astype(np.float32),
                      is_linear=False, metadata={"k": "v"})


# --- discovery ---------------------------------------------------------------

def _drop(d: pathlib.Path, stem: str, meta) -> None:
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{stem}.onnx").write_bytes(b"not read by discovery")
    if meta is not None:
        (d / f"{stem}.json").write_text(meta if isinstance(meta, str) else json.dumps(meta))


STRETCHED = {"space": "stretched", "inputs": 3, "tile": 256}


def test_review_focus_5_exactly_the_stretched_models_with_their_names(tmp_path):
    tray = tmp_path / "tray"
    _drop(tray, "v19p", STRETCHED)                                      # pre-v20: no id/name
    _drop(tray, "v20.0", {**STRETCHED, "id": "v20.0", "name": "Odin"})  # dotted id
    _drop(tray, "v15c", None)                                           # linear, no JSON
    _drop(tray, "v16", {"space": "linear, pre-stretch", "inputs": 4})
    found = nr_models.discover([str(tray)])
    assert [(m.id, m.name) for m in found] == [("v19p", "v19p"), ("v20.0", "Odin")]
    assert [m.path for m in found] == [str(tray / "v19p.onnx"), str(tray / "v20.0.onnx")]
    assert found == nr_models.discover([str(tray)]), "stable from call to call"


def test_order_is_natural_not_lexical(tmp_path):
    for stem in ("v9", "v20.0", "v18-4h", "v18", "v100"):
        _drop(tmp_path, stem, STRETCHED)
    assert [m.id for m in nr_models.discover([str(tmp_path)])] == \
        ["v9", "v18", "v18-4h", "v20.0", "v100"]


@pytest.mark.parametrize("meta", [
    None,                                                 # no JSON at all
    {"space": "linear", "inputs": 3},
    {"inputs": 3},                                        # no space
    {"space": "stretched", "inputs": 1},
    {"space": "stretched", "inputs": 4},
    {"space": "stretched"},                               # inputs missing
    {"space": "stretched", "inputs": 3, "tile": 512},
    "{not json",
    "[1, 2]",                                             # JSON, not an object
])
def test_anything_but_a_three_input_stretched_model_is_ignored(tmp_path, meta):
    _drop(tmp_path, "m", meta)
    assert nr_models.discover([str(tmp_path)]) == []


def test_json_without_its_onnx_is_ignored(tmp_path):
    (tmp_path / "ghost.json").write_text(json.dumps(STRETCHED))
    assert nr_models.discover([str(tmp_path)]) == []


def test_id_and_name_fall_back_to_the_stem_separately(tmp_path):
    _drop(tmp_path, "v21.0", {**STRETCHED, "name": "Frigg"})
    _drop(tmp_path, "v22.0", {**STRETCHED, "id": "v22.0"})
    found = {m.id: m.name for m in nr_models.discover([str(tmp_path)])}
    assert found == {"v21.0": "Frigg", "v22.0": "v22.0"}


def test_a_missing_directory_is_simply_empty(tmp_path):
    assert nr_models.discover([str(tmp_path / "nope")]) == []


def test_default_dirs_shipped_first_and_shipped_wins_an_id_clash(tmp_path, monkeypatch):
    shipped, tray = tmp_path / "shipped", tmp_path / "tray"
    _drop(shipped, "odin", {**STRETCHED, "id": "v20.0", "name": "Odin (shipped)"})
    _drop(tray, "v20.0", {**STRETCHED, "id": "v20.0", "name": "Odin (tray)"})
    _drop(tray, "v19p", STRETCHED)
    monkeypatch.setattr(nr_models, "SHIPPED_DIR", str(shipped))
    monkeypatch.setattr(nr_models, "TRAY_DIR", str(tray))
    found = nr_models.discover()
    assert [(m.id, m.name, m.shipped) for m in found] == [
        ("v20.0", "Odin (shipped)", True), ("v19p", "v19p", False)]
    assert found[0].path == str(shipped / "odin.onnx")


def test_the_default_tray_is_the_users_models_folder():
    import os
    assert nr_models._REAL_TRAY_DIR == os.path.join(os.path.expanduser("~"), ".nocturne", "models")
    assert nr_models._REAL_SHIPPED_DIR.endswith(os.path.join("nocturne", "assets", "models", "nr"))


def test_nothing_is_offered_without_onnxruntime(tmp_path, monkeypatch):
    _drop(tmp_path, "v19p", STRETCHED)
    monkeypatch.setattr(nr_models, "TRAY_DIR", str(tmp_path))
    assert [m.id for m in nr_models.available()] == ["v19p"]
    monkeypatch.setitem(sys.modules, "onnxruntime", None)        # import now fails
    assert nr_models.runtime_available() is False
    assert nr_models.available() == []


def test_engine_label_names_the_model_and_survives_its_removal(tmp_path, monkeypatch):
    _drop(tmp_path, "v20.0", {**STRETCHED, "id": "v20.0", "name": "Odin"})
    _drop(tmp_path, "v19p", STRETCHED)
    monkeypatch.setattr(nr_models, "TRAY_DIR", str(tmp_path))
    assert nr_models.engine_label("v20.0") == "Nocturne NR — Odin (v20.0)"
    assert nr_models.engine_label("v19p") == "Nocturne NR — v19p"
    (tmp_path / "v20.0.onnx").unlink()
    assert nr_models.engine_label("v20.0") == "Nocturne NR — v20.0"


# --- inference ---------------------------------------------------------------

def test_contract_origins_are_what_the_contract_says():
    """Literal values, so the independent helper above is itself pinned."""
    assert _contract_origins(600) == [0, 224, 344]
    assert _contract_origins(1000) == [0, 224, 448, 672, 744]
    assert _contract_origins(256) == [0]


def test_review_focus_1_tiles_and_weights_on_a_non_multiple_size(tmp_path):
    img = _stretched(600, 1000)
    got = nr_models.denoise(img, 0.75, _model(tmp_path)).data
    want = _contract(img.data, 0.75)
    assert got.shape == img.data.shape and got.dtype == np.float32
    np.testing.assert_allclose(got, want, atol=2e-6)
    # And the blend matters on this input: a plain average of overlapping
    # tiles (weight 1 everywhere) lands somewhere measurably different.
    assert np.abs(got - _contract_flat(img.data, 0.75)).max() > 1e-3


def _contract_flat(img, s):
    H, W, _ = img.shape
    num, den = np.zeros((H, W, 3)), np.zeros((H, W, 1))
    for y in _contract_origins(H):
        for x in _contract_origins(W):
            t = img[y:y + 256, x:x + 256].astype(np.float64)
            num[y:y + 256, x:x + 256] += t - s * (t - t.mean(axis=(0, 1), keepdims=True))
            den[y:y + 256, x:x + 256] += 1
    return np.clip(num / den, 0, 1)


def test_review_focus_2_smaller_than_a_tile_is_reflect_padded_and_cropped(tmp_path):
    img = _stretched(100, 400)
    got = nr_models.denoise(img, 1.0, _model(tmp_path)).data
    assert got.shape == (100, 400, 3)
    padded = np.pad(img.data, ((0, 156), (0, 0), (0, 0)), mode="reflect")
    np.testing.assert_allclose(got, _contract(padded, 1.0)[:100], atol=2e-6)


def test_smaller_than_a_tile_in_both_dimensions(tmp_path):
    img = _stretched(24, 30)
    got = nr_models.denoise(img, 0.5, _model(tmp_path)).data
    assert got.shape == (24, 30, 3)
    padded = np.pad(img.data, ((0, 232), (0, 226), (0, 0)), mode="reflect")
    np.testing.assert_allclose(got, _contract(padded, 0.5)[:24, :30], atol=2e-6)


def test_review_focus_3_mono_repeats_in_and_averages_out(tmp_path):
    img = _stretched(300, 280, mono=True)
    out = nr_models.denoise(img, 0.75, _model(tmp_path))
    assert out.data.ndim == 2 and out.data.shape == (300, 280)
    rgb = np.repeat(img.data[:, :, None], 3, axis=2)
    np.testing.assert_allclose(out.data, _contract(rgb, 0.75).mean(axis=2), atol=2e-6)


def test_strength_zero_is_identity(tmp_path):
    img = _stretched(300, 300)
    before = img.data.copy()
    out = nr_models.denoise(img, 0.0, _model(tmp_path))
    np.testing.assert_array_equal(out.data, before)
    np.testing.assert_array_equal(img.data, before), "the input is never written"
    assert out.is_linear is False and out.metadata == {"k": "v"}


def test_the_result_is_clipped(tmp_path):
    """Strength 2 gives 2·mean − x: below zero where x is bright, above one
    where it is dark on a bright tile. Both ends must be clipped."""
    img = _stretched(300, 300)
    img.data[10:20, 10:20] = 1.0
    out = nr_models.denoise(img, 2.0, _model(tmp_path)).data
    assert out.min() == 0.0 and out.max() <= 1.0
    np.testing.assert_allclose(out, _contract(img.data, 2.0), atol=4e-6)


def test_linear_input_is_refused(tmp_path):
    img = AstroImage(np.full((300, 300, 3), 0.1, np.float32), is_linear=True)
    with pytest.raises(ValueError, match="after Stretch"):
        nr_models.denoise(img, 0.75, _model(tmp_path))


def test_a_model_that_is_gone_says_so(tmp_path):
    m = _model(tmp_path, stem="v20.0", meta={**STRETCHED, "id": "v20.0", "name": "Odin"})
    pathlib.Path(m.path).unlink()
    with pytest.raises(FileNotFoundError, match="Nocturne NR v20.0 is not installed"):
        nr_models.denoise(_stretched(300, 300), 0.75, m)


def test_progress_is_reported_and_cancel_is_honoured_between_tiles(tmp_path):
    model = _model(tmp_path)
    img = _stretched(600, 1000)                         # 3 x 5 = 15 tiles
    seen = []
    token = CancelToken()
    token.on_progress = lambda d, t: seen.append((d, t))
    set_ambient(token)
    try:
        nr_models.denoise(img, 0.75, model)
        assert seen[-1] == (15, 15) and len(seen) == 15
        seen.clear()

        def cancel_after_two(d, t):
            seen.append((d, t))
            if d == 2:
                token.cancel()
        token.on_progress = cancel_after_two
        with pytest.raises(Cancelled):
            nr_models.denoise(img, 0.75, model)
        assert seen == [(1, 15), (2, 15)], "stopped before the third tile"
    finally:
        clear_ambient()


def test_the_session_is_built_once_per_model_file(tmp_path, monkeypatch):
    import onnxruntime as ort
    built = []
    real = ort.InferenceSession

    def counting(*a, **k):
        built.append(a[0])
        return real(*a, **k)
    monkeypatch.setattr(ort, "InferenceSession", counting)
    nr_models._SESSIONS.clear()
    model = _model(tmp_path)
    nr_models.denoise(_stretched(300, 300), 0.5, model)
    nr_models.denoise(_stretched(300, 300), 1.0, model)
    assert built == [model.path]


def test_a_model_whose_graph_is_not_three_by_256_is_refused(tmp_path, monkeypatch):
    model = _model(tmp_path)

    class _In:
        name, shape = "x", [1, 4, 256, 256]

    class _Sess:
        def get_inputs(self):
            return [_In()]
    monkeypatch.setattr(nr_models, "_session", lambda path: _Sess())
    with pytest.raises(RuntimeError, match="1×3×256×256"):
        nr_models.denoise(_stretched(300, 300), 0.75, model)
