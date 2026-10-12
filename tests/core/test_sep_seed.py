"""sep's star detection must give the same stars every call (2026-10-12)."""
import os
import threading

import numpy as np
import pytest

import nocturne  # noqa: F401  (installs the Windows wrapper)


def _crowded_field(seed=3):
    rng = np.random.default_rng(seed)
    img = rng.normal(100.0, 5.0, (400, 400))
    yy, xx = np.mgrid[:400, :400]
    for cy, cx in rng.uniform(10, 390, (300, 2)):            # many close pairs: deblending works hard
        for dy, dx in ((0, 0), (2.5, 1.5)):
            img += 400 * np.exp(-((yy - cy - dy) ** 2 + (xx - cx - dx) ** 2) / 4.0)
    return np.ascontiguousarray(img, dtype=np.float32)


def _stars(img):
    import sep
    bkg = sep.Background(img)
    sub = img - bkg.back()
    obj = sep.extract(sub, 3.0, err=bkg.globalrms)
    # Exact, not rounded: on Windows the unseeded deblender kept the count and
    # moved positions and fluxes in the last bits (7 of 7 repeat calls).
    order = np.lexsort((obj["y"], obj["x"]))
    return len(obj), np.concatenate([obj["x"][order], obj["y"][order], obj["flux"][order]])


def test_the_same_frame_gives_the_same_stars_on_one_thread():
    img = _crowded_field()
    first = _stars(img)
    for _ in range(6):
        n, xs = _stars(img)
        assert n == first[0]
        assert np.array_equal(xs, first[1])


def test_the_same_frame_gives_the_same_stars_on_another_thread():
    img = _crowded_field()
    here = _stars(img)
    _stars(_crowded_field(seed=9))                            # use up some random draws first
    out = {}
    t = threading.Thread(target=lambda: out.setdefault("r", _stars(img)))
    t.start(); t.join()
    assert out["r"][0] == here[0] and np.array_equal(out["r"][1], here[1])


@pytest.mark.skipif(os.name != "nt", reason="the wrapper exists only on Windows")
def test_the_wrapper_is_installed_on_windows():
    import sep
    assert hasattr(sep.extract, "__wrapped__")


@pytest.mark.skipif(os.name == "nt", reason="elsewhere sep is left alone")
def test_sep_is_untouched_off_windows():
    import sep
    assert not hasattr(sep.extract, "__wrapped__")
