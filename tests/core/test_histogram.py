import numpy as np
from nocturne.core.image import AstroImage
from nocturne.core.histogram import histogram


def test_color_histogram_channels_and_counts():
    h = histogram(AstroImage(np.full((10, 10, 3), 0.5, np.float32)), bins=256)
    assert set(h) == {"r", "g", "b"}
    assert all(len(v) == 256 for v in h.values())
    assert int(h["r"].sum()) == 100


def test_mono_histogram():
    h = histogram(AstroImage(np.zeros((4, 4), np.float32)), bins=64)
    assert set(h) == {"l"} and len(h["l"]) == 64
