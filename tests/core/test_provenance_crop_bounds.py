"""Crop and Trim say WHICH part of the picture they kept, in source pixels.

Before 2026-10-17 a Crop recorded its bounds live and the save dropped them,
and a Trim recorded only its shape, so the report could say "Crop — 4:5" and
never what was cut. The region rides in the saved option beside the keys every
build reads; a crop still restores from its cached pixels, never replayed."""
import datetime
import json
import zipfile

import numpy as np

from nocturne.core.crop import CropParams
from nocturne.core.image import AstroImage
from nocturne.core.provenance import build_report
from nocturne.history.project import Project
from nocturne.history.project_store import load_project, restored_entry, save_project
from nocturne.recipe import deserialize_option, recipe_from_entries, serialize_option
from nocturne.steps.factory import make_step
from nocturne.settings import Settings


def _report(entries):
    return build_report(entries, {}, app_version="x", date=datetime.date(2026, 10, 17))


# top 698, bottom 2985, left 175, right 2005 of a 2180 x 3683 picture
_CROP = CropParams(bounds=(698, 2985, 175, 2005), aspect="4:5", source_size=(2180, 3683))


def test_a_crop_says_the_region_it_kept():
    r = _report([("Crop", _CROP)])
    assert "1. Crop — 4:5, 1830 × 2287 px from 2180 × 3683" in r
    assert "- shape: 4:5" in r
    assert "- kept: 1830 × 2287 px of 2180 × 3683, left 175, top 698" in r


def test_a_trim_says_the_region_it_kept():
    r = _report([("Trim", {"aspect": "Picture", "bounds": [10, 790, 20, 1180],
                           "source_size": [1200, 800]})])
    assert "1. Trim — Original, 1160 × 780 px from 1200 × 800" in r
    assert "- kept: 1160 × 780 px of 1200 × 800, left 20, top 10" in r


def test_bounds_without_a_source_size_still_read():
    r = _report([("Crop", CropParams(bounds=(1, 9, 2, 12), aspect="Free"))])
    assert "1. Crop — Free, 10 × 8 px" in r
    assert "- kept: 10 × 8 px, left 2, top 1" in r


def test_an_older_record_reads_exactly_as_before():
    """Bundles saved before the region was kept: unchanged, line for line."""
    old = _report([("Crop", {"aspect": "2:3", "rotate": 0, "flip_h": False, "flip_v": False}),
                   ("Trim", {"aspect": "16:9"}), ("Crop", "")])
    assert "1. Crop — 2:3\n2. Trim — 16:9\n3. Crop\n" in old
    assert "### 1. Crop\n- shape: 2:3\n\n### 2. Trim\n- shape: 16:9\n" in old
    assert "kept" not in old


def test_a_recipe_still_carries_no_bounds():
    """A recipe replays a shape on another picture: one picture's pixels mean
    nothing there. The recipe's crop option is exactly what it was."""
    assert serialize_option("crop", _CROP) == {"aspect": "4:5", "rotate": 0,
                                               "flip_h": False, "flip_v": False}
    saved = serialize_option("crop", _CROP, project=True)
    steps = recipe_from_entries([("Crop", _CROP), ("Crop", saved)]).steps
    assert [s["option"] for s in steps] == [{"aspect": "4:5", "rotate": 0,
                                             "flip_h": False, "flip_v": False}] * 2
    assert deserialize_option("crop", saved).bounds is None


def test_the_saved_option_keeps_the_keys_every_build_reads():
    saved = serialize_option("crop", _CROP, project=True)
    assert saved == {"aspect": "4:5", "rotate": 0, "flip_h": False, "flip_v": False,
                     "bounds": [698, 2985, 175, 2005], "source_size": [2180, 3683]}
    json.dumps(saved)
    # The geometry heal reads exactly three keys: beside the new ones it still
    # tells a mislabelled rotation from a real Crop.
    def name(opt):
        return restored_entry({"name": "Crop", "stage": "crop", "option": opt,
                               "cached": True})[0]
    free = serialize_option("crop", CropParams(bounds=(0, 4, 0, 4), aspect="Free",
                                               source_size=(8, 8)), project=True)
    assert name(free) == "Crop"
    assert name({**free, "rotate": 90}) == "Rotate"


class _Pre:
    def __init__(self, name, img):
        self.name, self._img = name, img

    def apply(self, base, option):
        return self._img


def test_save_and_reopen_keeps_the_region_and_still_restores_from_pixels(tmp_path):
    base = AstroImage(np.random.default_rng(2).random((40, 60, 3)).astype(np.float32),
                      is_linear=True, metadata={})
    p = Project(base, str(tmp_path / "live"))
    crop = make_step("crop", Settings())
    params = CropParams(bounds=(2, 38, 3, 50), aspect="Free", source_size=(60, 40))
    p.run_step(_Pre("Crop", crop.apply(p.current(), params)), params)
    trim_opt = {"aspect": "Free", "bounds": [1, 30, 2, 40], "source_size": [47, 36]}
    p.run_step(_Pre("Trim", crop.apply(p.current(), CropParams(bounds=(1, 30, 2, 40)))),
               trim_opt)
    live = _report(p.entries())
    path = str(tmp_path / "c.nocturne")
    save_project(p, path)
    with zipfile.ZipFile(path) as zf:
        steps = json.loads(zf.read("manifest.json"))["steps"]
    assert [s["cached"] for s in steps] == [True, True], "a crop is never replayed"
    assert steps[0]["option"]["bounds"] == [2, 38, 3, 50]
    assert steps[1]["option"] == trim_opt
    lp = load_project(path, str(tmp_path / "re")).project
    assert _report(lp.entries()) == live
    assert "- kept: 47 × 36 px of 60 × 40, left 3, top 2" in live
    for i in range(3):
        np.testing.assert_array_equal(lp.state_at(i).data, p.state_at(i).data)
    # And a second save of the reopened project keeps it too.
    save_project(lp, str(tmp_path / "d.nocturne"))
    again = load_project(str(tmp_path / "d.nocturne"), str(tmp_path / "re2")).project
    assert _report(again.entries()) == live


def test_an_auto_enhance_crop_keeps_its_region_too():
    from nocturne.core.auto_enhance import run_auto_plan
    data = np.zeros((40, 60, 3), np.float32)
    data[5:35, 8:52] = np.random.default_rng(1).random((30, 44, 3)) * 0.3 + 0.1
    run = run_auto_plan(AstroImage(data, is_linear=True, metadata={}),
                        [("crop", CropParams())], Settings())
    (name, option, img), = run.results
    t, b, l, r = option["bounds"]
    assert option["source_size"] == [60, 40]
    assert img.data.shape[:2] == (b - t, r - l)
