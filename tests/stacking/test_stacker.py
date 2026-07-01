import os
import numpy as np
import pytest
from skimage.transform import SimilarityTransform, warp
from seestar_processor.stacking.stacker import StackOptions, run_stack
from tests.stacking.synthetic import make_star_field, write_color_fits


def _make_subs(tmp_path, n=4, seed=2):
    base = make_star_field(n_stars=40, seed=seed)
    paths = []
    for i in range(n):
        t = SimilarityTransform(translation=(i * 0.5, -i * 0.5))
        f = warp(base, t.inverse, order=1, preserve_range=True).astype(np.float32)
        p = tmp_path / f"s{i}.fit"
        write_color_fits(p, f, exptime=10.0)
        paths.append(str(p))
    return paths


def test_run_stack_produces_master(tmp_path):
    paths = _make_subs(tmp_path)
    out = tmp_path / "master.fits"
    opts = StackOptions("average", 2.5, paths, str(out))
    result = run_stack(opts)
    assert result.image.is_linear and result.image.data.ndim == 3
    assert result.frame_count == 4
    assert result.integration_seconds == 40.0
    assert os.path.exists(result.output_path)


def test_run_stack_reports_unreadable(tmp_path):
    paths = _make_subs(tmp_path)
    bad = tmp_path / "bad.fit"
    bad.write_text("not a fits file")
    opts = StackOptions("average", 2.5, paths + [str(bad)], str(tmp_path / "m.fits"))
    result = run_stack(opts)
    assert any(str(bad) == p for p, _ in result.rejected)
    assert result.frame_count == 4


def test_run_stack_too_few_frames(tmp_path):
    paths = _make_subs(tmp_path, n=2)
    with pytest.raises(ValueError):
        run_stack(StackOptions("average", 2.5, paths, str(tmp_path / "m.fits")))


def test_run_stack_starless_reference_raises(tmp_path):
    # A starless reference (include[0]) can't align anything -> everything drops.
    starless = tmp_path / "flat.fit"
    write_color_fits(starless, make_star_field(n_stars=0))
    subs = _make_subs(tmp_path, n=3)
    opts = StackOptions("average", 2.5, [str(starless)] + subs, str(tmp_path / "m.fits"))
    with pytest.raises(ValueError):
        run_stack(opts)
