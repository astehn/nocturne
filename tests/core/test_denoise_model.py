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
