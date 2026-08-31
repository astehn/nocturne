import numpy as np
from noise import estimate_sigma


def test_recovers_a_known_sigma():
    rng = np.random.default_rng(0)
    for true_sigma in (0.001, 0.01, 0.05):
        img = np.full((256, 256, 3), 0.4, np.float32)
        img += rng.normal(0, true_sigma, img.shape).astype(np.float32)
        got = estimate_sigma(img)
        assert abs(got - true_sigma) / true_sigma < 0.15, (true_sigma, got)


def test_stars_do_not_inflate_it():
    """A robust estimator must ignore bright outliers, or every star field
    reads as noisy and the model is told to remove far too much."""
    rng = np.random.default_rng(1)
    img = np.full((256, 256, 3), 0.4, np.float32)
    img += rng.normal(0, 0.01, img.shape).astype(np.float32)
    clean = estimate_sigma(img)
    for _ in range(200):                      # scatter bright stars
        y, x = rng.integers(4, 252, 2)
        img[y-2:y+3, x-2:x+3] += 0.5
    assert abs(estimate_sigma(img) - clean) / clean < 0.10
