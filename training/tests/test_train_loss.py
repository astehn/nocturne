import pytest

torch = pytest.importorskip("torch")

from train import masked_l1, masked_l2, selected_loss


def _fit(loss_fn, samples, steps=800, lr=0.05):
    """Fit one scalar to many noisy observations under `loss_fn`."""
    p = torch.zeros(1, requires_grad=True)
    opt = torch.optim.Adam([p], lr=lr)
    for _ in range(steps):
        opt.zero_grad()
        loss_fn(p.expand_as(samples), samples).backward()
        opt.step()
    return float(p.detach())


def test_l2_recovers_the_mean_and_l1_recovers_the_median():
    """THE PREMISE OF THE WHOLE SPEC, in one test.

    Noise2Noise works because fitting a noisy target recovers its conditional
    MEAN, and the mean of an unbiased noisy observation is the clean value.
    That holds for L2. L1 recovers the MEDIAN, which for right-skewed shot
    noise sits BELOW the mean -- so training against a noisy target under the
    project's current masked_l1 would pull faint signal systematically down.

    If this test cannot be made to pass, the spec is wrong and the work stops.

    Poisson(2.5): a FAINT pixel, a couple of photons per sub, which is where a
    Seestar frame's sky background actually lives and where the skew is real.
    The plan wrote Poisson(20). It cannot demonstrate anything: Poisson is
    integer-valued and near-symmetric by lambda=20, so its median lands exactly
    on 20 and the measured mean-median gap was -0.0121 -- the WRONG SIGN, and a
    hundredth the size of the 0.2 the assertion demanded. At 2.5 the gap is
    0.50, i.e. L1 settles 20% below the true signal. Same premise, a rate at
    which it is visible.
    """
    torch.manual_seed(0)
    clean = 2.5
    samples = torch.poisson(torch.full((200000,), clean))
    mean, median = float(samples.mean()), float(samples.median())

    # Guard the fixture itself. Without this the two assertions below would
    # both pass on a symmetric distribution, where mean == median and they say
    # nothing at all -- which is exactly how the plan's version read as a proof.
    assert mean - median > 0.2, (
        f"fixture is not right-skewed enough to show the bias: "
        f"mean={mean} median={median}"
    )

    l2_fit = _fit(lambda a, b: ((a - b) ** 2).mean(), samples)
    l1_fit = _fit(lambda a, b: (a - b).abs().mean(), samples)

    assert abs(l2_fit - clean) < 0.05, f"L2 should recover the mean, got {l2_fit}"
    assert abs(l2_fit - mean) < 0.01, (
        f"L2's minimiser IS the sample mean {mean}, got {l2_fit}")
    # 0.05 = Adam's lr. An L1 gradient has near-constant magnitude, so the step
    # never damps and the iterate keeps oscillating one lr either side of the
    # minimiser; it does not converge tighter than this and should not be asked to.
    assert abs(l1_fit - median) < 0.05, (
        f"L1's minimiser IS the sample median {median}, got {l1_fit}")
    assert l1_fit < clean - 0.2, (
        f"L1 should sit below the mean on right-skewed noise, got {l1_fit} "
        f"(if this fails, the skew is too weak to demonstrate the bias)"
    )


def test_masked_l2_ignores_masked_out_pixels():
    """The masked-out half carries a DIFFERENT error from the masked-in half.

    The plan put error 10 everywhere, so the masked mean and the plain mean of
    the whole tensor were both 100.0 and the assertion held whether or not the
    mask was applied at all. Here, dropping the mask reads ~499050 instead.
    """
    pred = torch.zeros(1, 3, 4, 4)
    target = torch.full((1, 3, 4, 4), 999.0)
    target[:, :, :2, :] = 10.0
    mask = torch.zeros(1, 1, 4, 4)
    mask[:, :, :2, :] = 1.0
    assert masked_l2(pred, target, mask).item() == pytest.approx(100.0)


def test_selected_loss_uses_l2_for_n2n_and_l1_for_truth():
    """A mixed batch must not silently get one loss for both kinds.

    The two samples carry DIFFERENT errors on purpose. The plan gave both an
    error of 3.0, so the batch read (l1=3 + l2=9)/2 = 6.0 -- and swapping the
    two branches read (l2=9 + l1=3)/2 = 6.0 as well. A mutation run confirmed
    it: with `torch.where(is_n2n > 0.5, l1, l2)` this test still passed, so the
    one mistake it exists to catch was the one it could not see.
    """
    pred = torch.zeros(2, 3, 4, 4)
    target = torch.stack([torch.full((3, 4, 4), 3.0), torch.full((3, 4, 4), 2.0)])
    mask = torch.ones(2, 1, 4, 4)
    is_n2n = torch.tensor([0.0, 1.0])

    # sample 0 is truth -> L1 -> |3|   = 3.0
    # sample 1 is n2n   -> L2 -> 2**2 = 4.0   -> mean 3.5
    assert selected_loss(pred, target, mask, is_n2n).item() == pytest.approx(3.5)
    # Flip which sample is which and the SAME batch must read 3**2 and |2|.
    assert selected_loss(pred, target, mask, 1.0 - is_n2n).item() == pytest.approx(5.5)


def test_selected_loss_matches_masked_l1_when_nothing_is_n2n():
    """Back-compatibility: an all-truth batch must train exactly as before,
    or run-to-run comparisons against ladder_v1 stop meaning anything."""
    torch.manual_seed(1)
    pred = torch.randn(4, 3, 8, 8)
    target = torch.randn(4, 3, 8, 8)
    mask = torch.ones(4, 1, 8, 8)
    is_n2n = torch.zeros(4)
    assert selected_loss(pred, target, mask, is_n2n).item() == pytest.approx(
        masked_l1(pred, target, mask).item(), rel=1e-5)


def test_selected_loss_respects_the_coverage_mask():
    """`_per_sample` does its own masking, and nothing else here exercises it:
    every other case in this file passes an all-ones mask, where dropping the
    mask is a no-op. Confirmed by mutation -- replacing the masked reduction
    with `err.mean(dim=(1, 2, 3))` passed all four of the other tests.

    Low-coverage pixels are the whole reason the mask exists: at a tile edge the
    'clean' target is really a partial stack, so its error must not enter the
    loss -- under either kind of pair.
    """
    pred = torch.zeros(1, 3, 4, 4)
    target = torch.full((1, 3, 4, 4), 999.0)
    target[:, :, :2, :] = 2.0
    mask = torch.zeros(1, 1, 4, 4)
    mask[:, :, :2, :] = 1.0

    # n2n   -> L2 over the covered half only -> 2**2 = 4.0
    assert selected_loss(pred, target, mask, torch.ones(1)).item() == pytest.approx(4.0)
    # truth -> L1 over the covered half only -> |2|   = 2.0
    assert selected_loss(pred, target, mask, torch.zeros(1)).item() == pytest.approx(2.0)
