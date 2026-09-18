"""StarNet2 as a free star/starless split.

Design: docs/superpowers/specs/2026-09-18-starnet2-integration.md. Measured on a
real NGC 7635 master 2026-09-18 — the free fallback leaves 40.3% of star flux
where StarNet2 leaves 20.9%, and the 1:1 crops are not close.
"""
import numpy as np
import pytest

from nocturne.core.image import AstroImage
from nocturne.settings import Settings
from nocturne.steps.factory import _splitter
from nocturne.tools.starnet import StarNet


def _img(h=16, w=16):
    a = np.full((h, w, 3), 0.2, np.float32)
    a[8, 8] = 0.9
    return AstroImage(a, is_linear=False, metadata={"OBJECT": "M 42"})


def test_it_asks_for_both_outputs_and_the_star_layer_is_unscreened(tmp_path):
    """`--unscreen` is the whole reason this is a drop-in: it writes the star
    layer in the SCREEN-compatible form every caller in this app recombines
    with. RCAstro.remove_stars documents the same contract, down to the flag
    name — the plain (subtractive) star layer recombines wrong, dimming and
    puffing stars even at zero reduction."""
    seen = {}
    import tifffile

    def fake_runner(args, **kw):
        seen["args"] = args
        out = args[args.index("--output") + 1]
        stars = args[args.index("--unscreen") + 1]
        src = tifffile.imread(args[args.index("--input") + 1])
        tifffile.imwrite(out, src)
        tifffile.imwrite(stars, np.zeros_like(src))

    StarNet("/fake/starnet2").remove_stars(_img(), runner=fake_runner)
    assert "--unscreen" in seen["args"], "without this the star layer recombines wrong"
    assert "--output" in seen["args"] and "--input" in seen["args"]
    assert seen["args"][0] == "/fake/starnet2"


def test_it_carries_metadata_and_linearity_through(tmp_path):
    """The tool changes pixels, not headers. Its output files have no metadata
    at all, so without this the target name and everything else is lost."""
    import tifffile

    def fake_runner(args, **kw):
        src = tifffile.imread(args[args.index("--input") + 1])
        tifffile.imwrite(args[args.index("--output") + 1], src)
        tifffile.imwrite(args[args.index("--unscreen") + 1], np.zeros_like(src))

    src = _img()
    starless, stars = StarNet("/fake").remove_stars(src, runner=fake_runner)
    assert starless.metadata == {"OBJECT": "M 42"} and stars.metadata == {"OBJECT": "M 42"}
    assert starless.is_linear is src.is_linear


def test_a_run_that_writes_nothing_is_an_error_not_an_empty_image(tmp_path):
    """The usual failure is a copied executable without its weights package
    beside it. That must say so, not hand back a blank frame that looks like a
    star-free image."""
    with pytest.raises(RuntimeError, match="weights"):
        StarNet("/fake").remove_stars(_img(), runner=lambda args, **kw: None)


def test_it_leaves_nothing_behind(tmp_path, monkeypatch):
    """Temp files go in a temp directory that is removed — never beside the
    user's own files."""
    import tempfile, tifffile, os
    made = []
    real_mkdtemp = tempfile.mkdtemp
    monkeypatch.setattr(tempfile, "mkdtemp", lambda **kw: made.append(real_mkdtemp(**kw)) or made[-1])

    def fake_runner(args, **kw):
        src = tifffile.imread(args[args.index("--input") + 1])
        tifffile.imwrite(args[args.index("--output") + 1], src)
        tifffile.imwrite(args[args.index("--unscreen") + 1], np.zeros_like(src))

    StarNet("/fake").remove_stars(_img(), runner=fake_runner)
    assert made and not os.path.exists(made[0]), "the temp directory survived"


def test_rc_astro_still_wins_when_both_are_installed(tmp_path):
    """The user paid for StarXTerminator and it is still the best. StarNet2 is
    the answer for everyone else, not a replacement for it."""
    from nocturne.tools.rcastro import RCAstro
    rc = tmp_path / "rc-astro"; rc.write_text("#!/bin/sh\n"); rc.chmod(0o755)
    sn = tmp_path / "starnet2"; sn.write_text("#!/bin/sh\n"); sn.chmod(0o755)
    both = Settings(rcastro_path=str(rc), starnet_path=str(sn))
    assert isinstance(_splitter(both), RCAstro)
    assert isinstance(_splitter(Settings(starnet_path=str(sn))), StarNet)
    assert _splitter(Settings()) is None, "nothing installed falls back to core/starless"
