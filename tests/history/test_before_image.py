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
