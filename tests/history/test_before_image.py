import numpy as np

from nocturne.core.autostretch import linked_stretch
from nocturne.core.crop import CropParams, apply_crop_params
from nocturne.core.image import AstroImage
from nocturne.core.share import to_rgb8
from nocturne.history.before_image import before_image, before_rgb8
from nocturne.history.project import Project
from nocturne.ui.pipeline import GEOMETRY_NAMES

H, W = 40, 30


def _base(linear=False):
    d = (np.arange(H * W * 3).reshape(H, W, 3) / (H * W * 3)).astype(np.float32)
    return AstroImage(d, is_linear=linear)


def _geo(p, name, option, params):
    p.record_precomputed(name, option, apply_crop_params(p.current(), params))


def _stretch(p):
    cur = p.current()
    p.record_precomputed("Stretch", "", AstroImage(cur.data * 0.5 + 0.25))


def test_no_geometry_gives_the_opened_image(tmp_path):
    p = Project(_base(), str(tmp_path))
    _stretch(p)
    assert np.array_equal(before_image(p).data, p.state_at(0).data)


def test_replay_crop_rotate_flip_trim_matches_geometry_without_processing(tmp_path):
    p = Project(_base(), str(tmp_path))
    crop = CropParams(bounds=(2, 38, 3, 27), aspect="4:5", source_size=(W, H))
    _geo(p, "Crop", crop, CropParams(bounds=(2, 38, 3, 27)))
    _stretch(p)
    _geo(p, "Rotate", "", CropParams(rotate=90))
    _geo(p, "Flip H", "", CropParams(flip_h=True))
    trim = {"aspect": "Original", "bounds": [1, 20, 2, 30], "source_size": [36, 24]}
    _geo(p, "Trim", trim, CropParams(bounds=(1, 20, 2, 30)))
    exp = p.state_at(0)
    for prm in (CropParams(bounds=(2, 38, 3, 27)), CropParams(rotate=90),
                CropParams(flip_h=True), CropParams(bounds=(1, 20, 2, 30))):
        exp = apply_crop_params(exp, prm)
    got = before_image(p)
    assert np.array_equal(got.data, exp.data)
    assert got.data.shape == p.shape_at(p.position)


def test_rotate_180_is_not_mistaken_for_identity(tmp_path):
    p = Project(_base(), str(tmp_path))
    _geo(p, "Rotate", "", CropParams(rotate=90))
    _geo(p, "Rotate", "", CropParams(rotate=90))
    assert p.shape_at(p.position)[:2] == (H, W)
    assert np.array_equal(before_image(p).data, np.rot90(p.state_at(0).data, -2))
    assert not np.array_equal(before_image(p).data, p.state_at(0).data)


def test_reloaded_dict_option_replays(tmp_path):
    p = Project(_base(), str(tmp_path))
    opt = {"aspect": "Original", "rotate": 0, "flip_h": False, "flip_v": False,
           "bounds": [2, 38, 3, 27], "source_size": [30, 40]}
    _geo(p, "Crop", opt, CropParams(bounds=(2, 38, 3, 27)))
    _stretch(p)
    exp = p.state_at(0).data[2:38, 3:27]
    assert np.array_equal(before_image(p).data, exp)


def test_crop_without_bounds_falls_back_to_after_last_geometry(tmp_path):
    p = Project(_base(), str(tmp_path))
    _geo(p, "Crop", "", CropParams(bounds=(2, 38, 3, 27)))
    _stretch(p)
    got = before_image(p).data
    assert np.array_equal(got, p.state_at(1).data)
    assert got.shape[:2] == (36, 24)


def test_mono_before_rgb8_is_three_channel(tmp_path):
    base = AstroImage(np.linspace(0, 1, H * W, dtype=np.float32).reshape(H, W), is_linear=True)
    p = Project(base, str(tmp_path))
    out = before_rgb8(p)
    assert out.shape == (H, W, 3) and out.dtype == np.uint8
    assert np.array_equal(out[..., 0], out[..., 1]) and np.array_equal(out[..., 1], out[..., 2])


def test_linear_before_is_stretched_like_the_spike(tmp_path):
    base = _base(linear=True)
    p = Project(base, str(tmp_path))
    _geo(p, "Flip V", "", CropParams(flip_v=True))
    exp = apply_crop_params(p.state_at(0), CropParams(flip_v=True)).data
    assert np.array_equal(before_rgb8(p), to_rgb8(linked_stretch(exp, 0.205)))


def test_geometry_names_come_from_pipeline():
    assert GEOMETRY_NAMES == ("Crop", "Rotate", "Flip H", "Flip V", "Trim")


def test_a_step_recorded_after_the_snapshot_does_not_change_the_before(tmp_path):
    p = Project(_base(), str(tmp_path))
    _geo(p, "Crop", CropParams(bounds=(2, 38, 3, 27)), CropParams(bounds=(2, 38, 3, 27)))
    _stretch(p)
    at = p.position
    pinned = before_image(p, at).data.copy()
    _geo(p, "Rotate", "", CropParams(rotate=90))       # lands after Share opened
    assert np.array_equal(before_image(p, at).data, pinned)
    assert np.array_equal(before_rgb8(p, at), to_rgb8(pinned))
    assert before_image(p).data.shape != pinned.shape  # unpinned does follow it


# --- final-review fixes ------------------------------------------------------

import pytest

from nocturne.history.before_image import has_processing


def _big_base(linear, h=520, w=420):
    """Past autostretch's 200k-sample threshold, so the stretch statistics come
    from a strided sample — the path a real master takes."""
    rng = np.random.default_rng(7)
    d = (rng.random((h, w, 3)) ** 3 * 0.2).astype(np.float32)
    return AstroImage(d, is_linear=linear)


@pytest.mark.parametrize("linear", [True, False])
@pytest.mark.parametrize("make", [_base, _big_base])
def test_a_boxed_before_equals_the_full_before_cropped(tmp_path, linear, make):
    p = Project(make(linear), str(tmp_path))
    h, w = p.shape_at(0)[:2]
    _geo(p, "Flip H", "", CropParams(flip_h=True))
    box = (3, h - 5, 2, w - 7)
    t, b, l, r = box
    full = before_rgb8(p)
    got = before_rgb8(p, box=box)
    assert got.shape == (b - t, r - l, 3)
    assert np.array_equal(got, full[t:b, l:r])


def test_a_boxed_linear_before_is_stretched_from_the_whole_frame(tmp_path):
    """A box over the dark half alone would stretch brighter if its own
    statistics were used: the look must come from the whole frame."""
    d = np.full((H, W, 3), 0.01, np.float32)
    d[:, W // 2:] = 0.3
    p = Project(AstroImage(d, is_linear=True), str(tmp_path))
    box = (0, H, 0, W // 2)
    assert np.array_equal(before_rgb8(p, box=box),
                          to_rgb8(linked_stretch(d, 0.205))[:, :W // 2])


def test_the_replay_honours_the_token(tmp_path):
    from nocturne.core.tasks import CancelToken, Cancelled
    p = Project(_base(linear=True), str(tmp_path))
    tok = CancelToken()
    tok.cancel()
    with pytest.raises(Cancelled):
        before_rgb8(p, box=(0, H, 0, W), token=tok)


def test_has_processing(tmp_path):
    p = Project(_base(), str(tmp_path))
    assert has_processing(p, 0) is False
    _geo(p, "Crop", CropParams(bounds=(2, 38, 3, 27)), CropParams(bounds=(2, 38, 3, 27)))
    _geo(p, "Rotate", "", CropParams(rotate=90))
    assert has_processing(p, p.position) is False
    _stretch(p)
    assert has_processing(p, p.position) is True
    assert has_processing(p, 2) is False          # pinned before the stretch


@pytest.mark.parametrize("bounds", [[1, 2, 3], ["a", "b", "c", "d"], [None, 1, 2, 3], 5])
def test_malformed_bundle_bounds_fall_back(tmp_path, bounds):
    p = Project(_base(), str(tmp_path))
    _geo(p, "Crop", {"bounds": bounds}, CropParams(bounds=(2, 38, 3, 27)))
    _stretch(p)
    assert np.array_equal(before_image(p).data, p.state_at(1).data)


def test_a_replay_that_disagrees_with_the_recorded_shape_falls_back(tmp_path):
    """The recorded bounds say one crop, the stored state is another: the
    replay's shape does not match shape_at(position), so the state after the
    last geometry entry is used instead."""
    p = Project(_base(), str(tmp_path))
    _geo(p, "Crop", {"bounds": [0, 10, 0, 10]}, CropParams(bounds=(2, 38, 3, 27)))
    _stretch(p)
    got = before_image(p).data
    assert got.shape[:2] == (36, 24)
    assert np.array_equal(got, p.state_at(1).data)


@pytest.mark.parametrize("shape", [(H, W, 3), (520, 420, 3), (1001, 903, 3), (1001, 903)])
def test_split_stretch_is_bitwise_linked_stretch(shape):
    """The crop path derives its luminance from the sample, not the whole
    frame; it must still be exactly linked_stretch, below and above the
    200k-sample threshold."""
    from nocturne.core.autostretch import apply_linked_stretch, linked_stretch_params
    d = (np.random.default_rng(3).random(shape) ** 3 * 0.2).astype(np.float32)
    assert np.array_equal(apply_linked_stretch(d, linked_stretch_params(d, 0.205)),
                          linked_stretch(d, 0.205))
