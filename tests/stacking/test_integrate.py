import numpy as np
import pytest
from nocturne.stacking.integrate import average_integrate, sigma_clip_integrate


def test_average_equals_numpy_mean():
    frames = [np.full((2, 2), 0.2, np.float32), np.full((2, 2), 0.4, np.float32)]
    out = average_integrate(frames)
    assert np.allclose(out, 0.3, atol=1e-6)


def test_average_empty_raises():
    with pytest.raises(ValueError):
        average_integrate([])


def test_sigma_clip_rejects_hot_frame():
    values = [0.5] * 9 + [5.0]  # one satellite/hot outlier at every pixel
    frames = [np.full((2, 2), v, np.float32) for v in values]
    out = sigma_clip_integrate(lambda: iter(frames), kappa=2.5)
    assert np.allclose(out, 0.5, atol=1e-6)  # outlier rejected -> mean of the 9
