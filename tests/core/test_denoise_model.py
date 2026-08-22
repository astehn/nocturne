import numpy as np


def test_app_and_training_sigma_are_identical():
    """Not 'close' — IDENTICAL. The conditioning channel is a number the model
    was trained against; two implementations that drift make it meaningless."""
    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).parents[2] / "training"))
    from noise import estimate_sigma as train_sigma
    from nocturne.core.denoise_model import estimate_sigma as app_sigma
    rng = np.random.default_rng(7)
    for _ in range(5):
        img = (rng.random((128, 128, 3), dtype=np.float32) * 0.5 + 0.2)
        assert app_sigma(img) == train_sigma(img)


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
