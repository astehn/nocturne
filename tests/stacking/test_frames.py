import numpy as np
from seestar_processor.stacking.frames import discover_subs, load_sub, luminance
from tests.stacking.synthetic import make_star_field, write_color_fits


def test_discover_subs_sorted(tmp_path):
    for name in ("b.fit", "a.fit", "c.fits"):
        write_color_fits(tmp_path / name, make_star_field())
    (tmp_path / "notes.txt").write_text("ignore me")
    found = discover_subs(str(tmp_path))
    assert [p.split("/")[-1] for p in found] == ["a.fit", "b.fit", "c.fits"]


def test_load_sub_returns_color_image(tmp_path):
    p = tmp_path / "s.fit"
    write_color_fits(p, make_star_field())
    img = load_sub(str(p))
    assert img.data.ndim == 3 and img.data.shape[2] == 3


def test_luminance_reduces_to_2d():
    lum = luminance(np.zeros((6, 7, 3), np.float32))
    assert lum.shape == (6, 7) and lum.dtype == np.float32
