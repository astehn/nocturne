""".nnr models in nr_models: listed only where the engine runs them, and fed to
`denoise` through the same `run(tile) -> noise` as a tray .onnx.

Separate from test_nr_models.py because that file skips without onnxruntime,
and the shipped app has none: everything here must run without it.
"""
import json
import os
import struct
import sys

import numpy as np
import pytest

from nocturne.core import nr_engine, nr_models
from nocturne.core.image import AstroImage
from nocturne.core.nr_engine import EngineError

GOOD = {"id": "v23.0", "name": "Freja", "credit_line": "Trained on donated Seestar subs",
        "space": "stretched", "inputs": 3, "tile": 256, "contract": 1}


def _nnr(path, header):
    raw = json.dumps(header).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"NNR1" + struct.pack("<HHI", 1, 1, len(raw)) + raw + os.urandom(64))


def _noise(tile):
    """Depends on the tile's content, so a wrong origin or weight changes the result."""
    return (0.3 * tile - tile.mean(axis=(2, 3), keepdims=True)).astype(np.float32)


class _FakeModel:
    def __init__(self, fail=None):
        self.calls, self.fail = 0, fail

    def run(self, tile):
        assert tile.shape == (1, 3, 256, 256) and tile.dtype == np.float32
        self.calls += 1
        if self.fail:
            raise EngineError(self.fail)
        return _noise(tile)


class _FakeEngine:
    def __init__(self, open_error=None, run_error=None, variant="dev"):
        self.opened, self.open_error, self.run_error = [], open_error, run_error
        self.variant = variant

    def version(self):
        return {"engine": "1.0.0", "variant": self.variant}

    def open(self, path):
        self.opened.append(path)
        if self.open_error:
            raise EngineError(self.open_error)
        return _FakeModel(self.run_error)


@pytest.fixture
def shipped(tmp_path, monkeypatch):
    d = tmp_path / "shipped"
    d.mkdir()
    monkeypatch.setattr(nr_models, "SHIPPED_DIR", str(d))
    monkeypatch.setattr(nr_models, "TRAY_DIR", str(tmp_path / "tray"))
    nr_models._SESSIONS.clear()
    yield d
    nr_models._SESSIONS.clear()


def _engine(monkeypatch, engine):
    monkeypatch.setattr(nr_engine, "load", lambda: engine)
    return engine


def _img(h=300, w=500, seed=3):
    rng = np.random.default_rng(seed)
    base = np.linspace(0.1, 0.7, w)[None, :, None] * np.array([1.0, 0.8, 0.6])
    data = (base + rng.normal(0, 0.05, (h, w, 3))).clip(0, 1).astype(np.float32)
    return AstroImage(data, is_linear=False)


def test_nnr_listed_when_engine_present(shipped, monkeypatch):
    _nnr(shipped / "freja.nnr", GOOD)
    _engine(monkeypatch, _FakeEngine())
    [m] = nr_models.available()
    assert (m.id, m.name, m.kind, m.credit, m.shipped) == (
        "v23.0", "Freja", "nnr", GOOD["credit_line"], True)
    assert nr_models.find("v23.0") == m


def test_nnr_hidden_without_engine(shipped, monkeypatch):
    _nnr(shipped / "freja.nnr", GOOD)
    _engine(monkeypatch, None)
    assert nr_models.available() == []
    assert nr_models.find("v23.0") is None


@pytest.mark.parametrize("change", [
    {"contract": 2}, {"contract": True}, {"contract": [1]}, {"contract": None},
    {"space": "linear"}, {"inputs": 1}, {"tile": 512}, {"tile": None},
])
def test_unknown_contract_not_listed(shipped, monkeypatch, change):
    _nnr(shipped / "m.nnr", {**GOOD, **change})
    _engine(monkeypatch, _FakeEngine())
    assert nr_models.discover() == [] and nr_models.available() == []


def test_a_file_that_is_not_nnr_is_not_listed(shipped, monkeypatch):
    (shipped / "junk.nnr").write_bytes(b"not a model at all")
    _engine(monkeypatch, _FakeEngine())
    assert nr_models.available() == []


def test_shipped_nnr_wins_over_a_tray_onnx_with_the_same_id(shipped, tmp_path, monkeypatch):
    _nnr(shipped / "freja.nnr", GOOD)
    tray = tmp_path / "tray"
    tray.mkdir()
    (tray / "v23.0.onnx").write_bytes(b"unread")
    (tray / "v23.0.json").write_text(json.dumps(
        {"space": "stretched", "inputs": 3, "tile": 256, "id": "v23.0"}), encoding="utf-8")
    _engine(monkeypatch, _FakeEngine())
    [m] = nr_models.discover()
    assert m.kind == "nnr" and m.path == str(shipped / "freja.nnr")


def test_in_one_folder_the_nnr_beats_an_onnx_with_the_same_id(shipped, monkeypatch):
    (shipped / "a.onnx").write_bytes(b"unread")       # sorts before "freja.nnr"
    (shipped / "a.json").write_text(json.dumps(
        {"space": "stretched", "inputs": 3, "tile": 256, "id": "v23.0"}), encoding="utf-8")
    _nnr(shipped / "freja.nnr", GOOD)
    _engine(monkeypatch, _FakeEngine())
    [m] = nr_models.discover()
    assert m.kind == "nnr"


def test_denoise_via_engine_matches_onnx_path(shipped, tmp_path, monkeypatch):
    """`denoise` depends only on `run`: the same noise through either kind of
    runner gives the same pixels, bit for bit."""
    _nnr(shipped / "freja.nnr", GOOD)
    _engine(monkeypatch, _FakeEngine())
    [nnr_model] = nr_models.available()

    onnx_path = tmp_path / "x.onnx"
    onnx_path.write_bytes(b"unread")
    onnx_model = nr_models.NRModel("x", "x", str(onnx_path), False)

    class _In:
        name, shape = "x", [1, 3, 256, 256]

    class _Sess:
        def get_inputs(self):
            return [_In()]

        def run(self, _outputs, feeds):
            return [_noise(feeds["x"])]
    monkeypatch.setattr(nr_models, "_ort_session", lambda path: _Sess())
    monkeypatch.setattr(nr_models, "runtime_available", lambda: True)

    img = _img()
    a = nr_models.denoise(img, 0.75, nnr_model).data
    b = nr_models.denoise(img, 0.75, onnx_model).data
    assert a.dtype == np.float32 and np.array_equal(a, b)
    assert not np.array_equal(a, img.data), "the fake noise must actually change pixels"


def test_engine_model_is_opened_once_per_file(shipped, monkeypatch):
    _nnr(shipped / "freja.nnr", GOOD)
    engine = _engine(monkeypatch, _FakeEngine())
    [m] = nr_models.available()
    nr_models.denoise(_img(), 0.5, m)
    nr_models.denoise(_img(), 1.0, m)
    assert engine.opened == [m.path]


@pytest.mark.parametrize("where", ["open", "run"])
def test_damaged_nnr_reports_plainly(shipped, monkeypatch, where):
    _nnr(shipped / "freja.nnr", GOOD)
    msg = "this model file is damaged"
    _engine(monkeypatch, _FakeEngine(**{f"{where}_error": msg}))
    [m] = nr_models.available()
    with pytest.raises(EngineError) as exc:
        nr_models.denoise(_img(), 0.75, m)
    assert str(exc.value) == msg


def test_recipe_with_nnr_model_in_source_build(shipped, monkeypatch):
    """A source checkout has no engine: a recipe naming a shipped model says
    the model is not installed, exactly as for a missing tray model."""
    from nocturne.recipe import _nr_plan
    from nocturne.steps.noise_sharpen import NoiseSharpenStep
    _nnr(shipped / "freja.nnr", GOOD)
    _engine(monkeypatch, None)
    plan = _nr_plan("Noise Reduction", "nr:v23.0")
    assert (plan.outcome, plan.reason) == ("fail", nr_models.not_installed("v23.0"))
    with pytest.raises(FileNotFoundError, match="^Nocturne NR v23.0 is not installed$"):
        NoiseSharpenStep().apply(_img(), _option("nr:v23.0"))


def test_recipe_runs_an_nnr_model_without_onnxruntime(shipped, monkeypatch):
    """The shipped app has the engine and no onnxruntime; an .nnr must plan to run."""
    from nocturne.recipe import _nr_plan
    _nnr(shipped / "freja.nnr", GOOD)
    _engine(monkeypatch, _FakeEngine())
    monkeypatch.setattr(nr_models, "runtime_available", lambda: False)
    assert _nr_plan("Noise Reduction", "nr:v23.0").outcome == "run"


def _option(engine):
    return {"engine": engine, "level": "medium"}


def _tray_onnx(tmp_path, mid="v23.0"):
    tray = tmp_path / "tray"
    tray.mkdir(exist_ok=True)
    (tray / f"{mid}.onnx").write_bytes(b"unread")
    (tray / f"{mid}.json").write_text(json.dumps(
        {"space": "stretched", "inputs": 3, "tile": 256, "id": mid}), encoding="utf-8")
    return tray / f"{mid}.onnx"


@pytest.mark.parametrize("engine", [None, _FakeEngine(variant="release")])
def test_an_unrunnable_nnr_does_not_hide_the_tray_onnx(shipped, tmp_path, monkeypatch, engine):
    """A release drops v23.0.nnr into the checkout he also runs from source; his
    tray v23.0.onnx must stay the one that runs, by listing and by recipe."""
    from nocturne.recipe import _nr_plan
    _nnr(shipped / "freja.nnr", GOOD)
    onnx = _tray_onnx(tmp_path)
    _engine(monkeypatch, engine)
    monkeypatch.setattr(nr_models, "runtime_available", lambda: True)
    assert [(m.kind, m.path) for m in nr_models.available()] == [("onnx", str(onnx))]
    assert nr_models.find("v23.0").path == str(onnx)
    assert _nr_plan("Noise Reduction", "nr:v23.0").outcome == "run"


def test_without_onnxruntime_the_tray_onnx_still_names_the_missing_runtime(
        shipped, tmp_path, monkeypatch):
    from nocturne.recipe import _nr_plan
    _nnr(shipped / "freja.nnr", GOOD)
    _tray_onnx(tmp_path)
    _engine(monkeypatch, None)
    monkeypatch.setattr(nr_models, "runtime_available", lambda: False)
    assert nr_models.available() == []
    assert "needs onnxruntime" in _nr_plan("Noise Reduction", "nr:v23.0").reason


def test_a_release_engine_is_not_offered_in_a_source_run(shipped, monkeypatch):
    """It loads, then refuses every model outside the bundle: offering its
    models would fail on the first tile (and Auto Enhance picks them itself)."""
    _nnr(shipped / "freja.nnr", GOOD)
    _engine(monkeypatch, _FakeEngine(variant="release"))
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert nr_engine.usable() is False
    assert nr_models.available() == [] and nr_models.find("v23.0") is None


def test_a_release_engine_is_offered_in_the_frozen_app(shipped, monkeypatch):
    _nnr(shipped / "freja.nnr", GOOD)
    _engine(monkeypatch, _FakeEngine(variant="release"))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert nr_engine.usable() is True
    assert [m.kind for m in nr_models.available()] == ["nnr"]


def test_a_dev_engine_is_offered_from_source(shipped, monkeypatch):
    _nnr(shipped / "freja.nnr", GOOD)
    _engine(monkeypatch, _FakeEngine(variant="dev"))
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert nr_engine.usable() is True
    assert [m.kind for m in nr_models.available()] == ["nnr"]


def test_an_engine_whose_version_fails_is_not_usable(monkeypatch):
    class _Broken(_FakeEngine):
        def version(self):
            raise EngineError("could not read engine version (code -4)")
    _engine(monkeypatch, _Broken())
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert nr_engine.usable() is False


def test_denoise_never_opens_a_model_on_an_unusable_engine(shipped, monkeypatch):
    """A model picked earlier (a saved recipe, a panel built before the engine
    changed) still reports "not installed" rather than the engine's refusal."""
    _nnr(shipped / "freja.nnr", GOOD)
    engine = _engine(monkeypatch, _FakeEngine())
    [m] = nr_models.available()
    engine.variant = "release"
    monkeypatch.delattr(sys, "frozen", raising=False)
    with pytest.raises(FileNotFoundError, match="^Nocturne NR v23.0 is not installed$"):
        nr_models.denoise(_img(), 0.75, m)
    assert engine.opened == []


@pytest.fixture
def broken_engine(tmp_path, monkeypatch):
    """The engine file is there but will not load — on Windows, what a missing
    VC++ runtime looks like. Goes through the real load(), not a fake."""
    d = tmp_path / "engine"
    d.mkdir()
    (d / nr_engine._library_name()).write_bytes(b"not a library")
    monkeypatch.setattr(nr_engine, "ENGINE_DIR", str(d))
    monkeypatch.setattr(nr_engine, "_cached", nr_engine._UNSET)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    yield
    monkeypatch.setattr(nr_engine, "_cached", nr_engine._UNSET)


def test_a_present_engine_that_will_not_load_says_so(shipped, broken_engine):
    """Not "not installed": the model is right there, and that sentence would
    send the user to reinstall a model rather than to the real cause."""
    from nocturne.recipe import _nr_plan
    from nocturne.steps.noise_sharpen import NoiseSharpenStep
    _nnr(shipped / "freja.nnr", GOOD)
    reason = nr_engine.load_error()
    assert reason
    want = f"Nocturne NR could not start: {reason}"
    assert nr_models.unavailable("v23.0") == want
    assert _nr_plan("Noise Reduction", "nr:v23.0").reason == want
    with pytest.raises(FileNotFoundError) as exc:
        NoiseSharpenStep().apply(_img(), _option("nr:v23.0"))
    assert str(exc.value) == want


def test_a_broken_engine_without_its_model_is_still_not_installed(shipped, broken_engine):
    """The engine's failure is not this model's story when the model is not here."""
    assert nr_engine.load_error()
    assert nr_models.unavailable("v23.0") == nr_models.not_installed("v23.0")


def test_an_absent_engine_has_no_load_error(shipped, tmp_path, monkeypatch):
    _nnr(shipped / "freja.nnr", GOOD)
    monkeypatch.setattr(nr_engine, "ENGINE_DIR", str(tmp_path / "absent"))
    monkeypatch.setattr(nr_engine, "_cached", nr_engine._UNSET)
    assert nr_engine.load_error() == ""
    assert nr_models.unavailable("v23.0") == nr_models.not_installed("v23.0")
    monkeypatch.setattr(nr_engine, "_cached", nr_engine._UNSET)
