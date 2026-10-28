import numpy as np
import pytest

from nocturne.core import nr_engine


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.setattr(nr_engine, "_cached", nr_engine._UNSET)
    yield
    monkeypatch.setattr(nr_engine, "_cached", nr_engine._UNSET)


def test_missing_engine_dir_is_none(tmp_path, monkeypatch):
    monkeypatch.setattr(nr_engine, "ENGINE_DIR", str(tmp_path / "absent"))
    assert nr_engine.load() is None


def test_engine_load_failure_means_no_nr(tmp_path, monkeypatch):
    (tmp_path / nr_engine._library_name()).write_bytes(b"not a library")
    monkeypatch.setattr(nr_engine, "ENGINE_DIR", str(tmp_path))
    assert nr_engine.load() is None
    # cached: a second call does not retry
    (tmp_path / nr_engine._library_name()).unlink()
    assert nr_engine.load() is None


class _FakeLib:
    def __init__(self):
        self.calls = 0

    def nr_run(self, h, i, o):
        self.calls += 1
        return 0


def _model():
    lib = _FakeLib()
    return nr_engine.EngineModel(lib, 7), lib


@pytest.mark.parametrize("shape", [(3, 256, 256), (1, 3, 128, 128), (1, 1, 256, 256)])
def test_run_rejects_wrong_shape(shape):
    m, lib = _model()
    with pytest.raises(nr_engine.EngineError):
        m.run(np.zeros(shape, np.float32))
    assert lib.calls == 0


def test_run_rejects_wrong_dtype():
    m, lib = _model()
    with pytest.raises(nr_engine.EngineError):
        m.run(np.zeros((1, 3, 256, 256), np.float64))
    assert lib.calls == 0


def test_run_returns_new_array_and_reports_code():
    m, lib = _model()
    t = np.zeros((1, 3, 256, 256), np.float32)
    out = m.run(t)
    assert out.shape == t.shape and out is not t and lib.calls == 1
    lib.nr_run = lambda h, i, o: -3
    with pytest.raises(nr_engine.EngineError):
        m.run(t)
