import numpy as np
import pytest

from nocturne.training.inject import noise_field, target_from_halves


def test_the_signal_cancels_completely():
    """Subtracting two views of the same sky must leave no sky behind. If any
    signal survives, we would be adding a ghost of the picture to itself."""
    scene = np.random.default_rng(0).random((64, 64, 3)).astype(np.float32)
    assert np.allclose(noise_field(scene, scene), 0.0, atol=1e-6)


def test_the_field_has_the_noise_of_an_n_frame_stack():
    """The sqrt(2) is the whole point. var(A-B) = 2*sigma^2/n for two disjoint
    n-frame halves, so dividing by sqrt(2) recovers sigma^2/n — the variance a
    real n-frame stack would have. Without it every manufactured input would be
    41% noisier than it claims to be."""
    rng = np.random.default_rng(1)
    scene = np.full((256, 256, 3), 0.2, np.float32)
    sigma_half = 0.01                      # what one half-stack carries
    a = scene + rng.normal(0, sigma_half, scene.shape).astype(np.float32)
    b = scene + rng.normal(0, sigma_half, scene.shape).astype(np.float32)
    assert np.std(noise_field(a, b)) == pytest.approx(sigma_half, rel=0.03)


def test_the_field_is_independent_of_the_target():
    """cov(A-B, (A+B)/2) = (var A - var B)/2, which is zero for equal halves.
    That is what lets us add the field back to the target without reintroducing
    the target's own noise — if they correlated, we would be amplifying it."""
    rng = np.random.default_rng(2)
    scene = np.full((256, 256, 3), 0.2, np.float32)
    a = scene + rng.normal(0, 0.01, scene.shape).astype(np.float32)
    b = scene + rng.normal(0, 0.01, scene.shape).astype(np.float32)
    d, m = noise_field(a, b), target_from_halves(a, b)
    r = np.corrcoef(d.ravel(), (m - scene).ravel())[0, 1]
    assert abs(r) < 0.05, f"noise field correlates with the target at {r:.3f}"


def test_the_target_is_the_mean_of_both_halves():
    a = np.full((8, 8, 3), 0.4, np.float32)
    b = np.full((8, 8, 3), 0.6, np.float32)
    assert np.allclose(target_from_halves(a, b), 0.5)


def test_mismatched_shapes_are_refused():
    """The check must be OURS. numpy would reject (8, 9, 3) on its own, but it
    would happily BROADCAST (8, 1, 3) into an (8, 8, 3) result — a noise field
    manufactured out of a single column, with nothing to say it went wrong. So
    match the message, not merely the exception type."""
    good = np.zeros((8, 8, 3), np.float32)
    for bad in (np.zeros((8, 9, 3), np.float32), np.zeros((8, 1, 3), np.float32)):
        with pytest.raises(ValueError, match="differ in shape"):
            noise_field(good, bad)
        with pytest.raises(ValueError, match="differ in shape"):
            target_from_halves(good, bad)


def test_the_manufactured_input_lands_on_the_requested_noise_level():
    """The whole point of injection is CHOOSING the noise level, so 'close
    enough' is not close enough — if the request and the result diverge, the
    sigma conditioning is being told a number that is not true of the image."""
    from nocturne.core.denoise_model import estimate_sigma
    from nocturne.training.inject import inject, noise_field, scale_for_sigma

    rng = np.random.default_rng(3)
    scene = np.full((256, 256, 3), 0.2, np.float32)
    # A DEEP master: the halves must be far cleaner than anything we ask for,
    # because that is the real situation -- M is a 300-frame stack and every
    # request manufactures a shallower one. At the plan's original 0.01 per
    # half the target's own floor was 6.8e-3 and two of the three requests
    # below were unreachable by construction.
    sigma_half = 0.0005
    a = scene + rng.normal(0, sigma_half, scene.shape).astype(np.float32)
    b = scene + rng.normal(0, sigma_half, scene.shape).astype(np.float32)
    m, d = target_from_halves(a, b), noise_field(a, b)

    wanted_range = (0.002, 0.006, 0.02)         # the deployment range
    floor = estimate_sigma(m)
    assert floor < min(wanted_range), (
        f"fixture is not clean enough to be asked for {min(wanted_range)}: "
        f"its own floor is {floor:.3e}")

    for wanted in wanted_range:
        k = scale_for_sigma(d, wanted, estimate_sigma, base=m)
        got = estimate_sigma(inject(m, d, k))
        assert got == pytest.approx(wanted, rel=0.06), f"asked {wanted}, got {got}"


def test_a_request_below_the_targets_own_noise_is_refused():
    """You cannot make an image CLEANER by adding noise to it. Silently
    returning k=0 would hand the trainer an example labelled far cleaner than it
    is — the exact mislabelling that broke the conditioning channel before."""
    from nocturne.core.denoise_model import estimate_sigma
    from nocturne.training.inject import noise_field, scale_for_sigma

    rng = np.random.default_rng(4)
    scene = np.full((128, 128, 3), 0.2, np.float32)
    a = scene + rng.normal(0, 0.01, scene.shape).astype(np.float32)
    b = scene + rng.normal(0, 0.01, scene.shape).astype(np.float32)
    m, d = target_from_halves(a, b), noise_field(a, b)
    floor = estimate_sigma(m)
    with pytest.raises(ValueError):
        scale_for_sigma(d, floor * 0.5, estimate_sigma, base=m)


def test_injection_leaves_the_target_untouched():
    """inject() must not modify its input in place — the same target is reused
    for every noise level and every epoch."""
    from nocturne.training.inject import inject

    m = np.full((16, 16, 3), 0.3, np.float32)
    before = m.copy()
    inject(m, np.ones_like(m), 0.5)
    assert np.array_equal(m, before)
