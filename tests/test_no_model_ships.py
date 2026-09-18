"""No machine-learning model is part of the app.

`denoise_s30_v1.onnx` was tracked and shipped in every release up to v0.34.0:
7.7 MB inside the bundle that nothing could run, because `ai_denoise` is not in
`path_stages()` and the PyInstaller spec excludes onnxruntime. It was also the
model that damaged a 405-frame M 8 by 19%.

Removed 2026-09-18 at Andreas's word — *"yes please, no need for it to be
there"*. This guards the state rather than the deletion: a model reaches users
by being committed, and the commit is the moment to catch it.
"""
import os
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_no_model_file_is_tracked():
    tracked = subprocess.run(["git", "ls-files", "*.onnx", "*.pt", "*.pth", "*.safetensors"],
                             cwd=ROOT, capture_output=True, text=True).stdout.split()
    assert tracked == [], f"a model is committed: {tracked}"


def test_the_app_still_starts_without_one():
    """The loader must answer "no model" rather than raise. Nothing in the
    pipeline reaches it today, but `available()` is what a future caller asks,
    and a crash here would be a startup crash."""
    from nocturne.core.denoise_model import available, model_path
    assert available("s30") is False
    assert not os.path.exists(model_path("s30"))
