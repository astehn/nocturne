import numpy as np


def test_only_one_definition_of_sigma_exists_outside_the_archive():
    """The sigma fed to the model as a conditioning channel must be computed
    identically when training and when running, or the model has been lied to.

    Until 2026-08-31 that was enforced by keeping two verbatim copies and
    asserting they matched. The app must not import training code — but the
    reverse is fine, and training runs with the app importable, so the new
    system imports THIS function instead of copying it. One definition cannot
    drift from itself.

    Deliberately a search, not an equality check: a second copy that happens to
    agree today is the thing that goes stale later."""
    import pathlib
    root = pathlib.Path(__file__).parents[2]
    # only the two trees that could drift: the shipped package and live
    # training. dist/ holds build output (skimage has its own estimate_sigma)
    # and archive/ is the retired system, kept for reference and never run.
    found = sorted(
        str(f.relative_to(root))
        for tree in ("nocturne", "training")
        for f in (root / tree).rglob("*.py") if (root / tree).is_dir()
        if "def estimate_sigma" in f.read_text(errors="ignore"))
    assert found == ["nocturne/core/denoise_model.py"], (
        f"estimate_sigma must have exactly one live definition, found: {found}")


def test_pre_conditioning_model_is_refused_not_silently_used(tmp_path, monkeypatch):
    """The old 3-channel model is the one that visibly broke a 405-frame
    master. denoise() must refuse it with a clear message naming the cause
    and the remedy -- not a raw onnxruntime shape error, and NOT a silent
    3-channel fallback."""
    import subprocess, pathlib
    import pytest

    onnx_path = tmp_path / "old_3ch.onnx"
    build_script = (
        "import torch, torch.nn as nn\n"
        "net = nn.Conv2d(3, 3, 1)\n"
        "torch.nn.init.zeros_(net.weight); torch.nn.init.zeros_(net.bias)\n"
        "dummy = torch.randn(1, 3, 16, 16)\n"
        f"torch.onnx.export(net, dummy, {str(onnx_path)!r}, input_names=['input'],\n"
        "    output_names=['noise'],\n"
        "    dynamic_axes={'input': {0: 'batch', 2: 'h', 3: 'w'}, 'noise': {0: 'batch', 2: 'h', 3: 'w'}},\n"
        "    opset_version=17)\n"
    )
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    venv_train = repo_root / ".venv-train" / "bin" / "python"
    subprocess.run([str(venv_train), "-c", build_script], check=True, cwd=repo_root)
    assert onnx_path.exists()

    import nocturne.core.denoise_model as dm
    monkeypatch.setattr(dm, "model_path", lambda sensor="s30": str(onnx_path))
    monkeypatch.setattr(dm, "available", lambda sensor="s30": True)
    monkeypatch.setattr(dm, "metadata", lambda sensor="s30": {})
    dm._session.cache_clear()

    from nocturne.core.image import AstroImage
    rng = np.random.default_rng(0)
    img = AstroImage((rng.random((32, 32, 3), dtype=np.float32) * 0.5 + 0.2),
                      is_linear=True, metadata={})
    with pytest.raises(RuntimeError, match="3 input channels"):
        dm.denoise(img, strength=0.5, sensor="faketest")
    dm._session.cache_clear()


def test_a_project_naming_the_withdrawn_step_gets_an_explanation(monkeypatch):
    """onnxruntime is not bundled — 64 MB for a step that cannot be reached, and
    excluding it took a cold start from 9.2 s to 1.0 s.

    The one route here is a project saved before v0.18.0, when AI Denoise was in
    the pipeline. Such a user should be told what happened to the step, not
    handed an ImportError for a library they have never heard of.
    """
    import builtins
    import pytest
    from nocturne.core import denoise_model

    real = builtins.__import__

    def no_ort(name, *a, **k):
        if name == "onnxruntime":
            raise ImportError("No module named 'onnxruntime'")
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", no_ort)
    denoise_model._session.cache_clear()
    with pytest.raises(RuntimeError, match="not part of this version"):
        denoise_model._session("/nonexistent/model.onnx")
    msg = str(pytest.raises(RuntimeError,
                            denoise_model._session, "/nonexistent/model.onnx").value)
    assert "v0.18.0" in msg and "onnxruntime" not in msg.lower(), msg
