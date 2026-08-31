import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_output_depends_on_the_sigma_it_is_told():
    """The whole point. Same pixels, different stated noise level, different
    correction -- otherwise conditioning is decoration."""
    import torch
    from model import DenoiseUNet
    net = DenoiseUNet(); net.eval()
    for p in net.out.parameters():          # undo zero-init so it does something
        torch.nn.init.normal_(p, 0, 0.01)
    x = torch.rand(1, 3, 64, 64) * 0.4 + 0.3
    with torch.no_grad():
        low = net.denoise(x, sigma=0.001, strength=1.0)
        high = net.denoise(x, sigma=0.05, strength=1.0)
    assert (low - high).abs().max() > 1e-4


def test_still_an_exact_identity_at_init():
    import torch
    from model import DenoiseUNet
    net = DenoiseUNet(); net.eval()
    x = torch.rand(1, 3, 64, 64)
    with torch.no_grad():
        assert torch.equal(net.denoise(x, sigma=0.01, strength=1.0), x)
