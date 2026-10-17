"""A saved project's report says what the live session's did (audit
2026-10-16: a reopened project renamed Rotate and both flips "Crop"). A real
save and a real load, then the report rendered from each."""
import datetime

import numpy as np

from nocturne.core.color import ColorSettings
from nocturne.core.crop import CropParams
from nocturne.core.image import AstroImage
from nocturne.core.levels import new_levels_option
from nocturne.core.curves import curve_key
from nocturne.core.narrowband import GOLD_BLUE, NarrowbandParams
from nocturne.core.provenance import AUTO_ENHANCE, build_report, run_origin
from nocturne.recipe import serialize_option
from nocturne.history.project import Project
from nocturne.history.project_store import load_project, save_project
from nocturne.settings import Settings
from nocturne.steps.factory import make_step
from nocturne.steps.stretch_step import new_stretch_option


class _Precomputed:
    def __init__(self, name, img):
        self.name, self._img = name, img

    def apply(self, base, option):
        return self._img


def _live(tmp_path) -> Project:
    rng = np.random.default_rng(11)
    base = AstroImage(rng.random((24, 36, 3)).astype(np.float32) * 0.2, is_linear=True,
                      metadata={"target": "IC 1805", "exposure": 10.0, "frames": 120,
                                "creator": "ZWO Seestar S30 Pro"})
    p = Project(base, str(tmp_path / "live"))
    s = Settings()

    def commit(name, stage, option, recorded=None, origin=None):
        """As MainWindow does: the real step's pixels, the recorded option."""
        out = make_step(stage, s).apply(p.current(), option)
        p.run_step(_Precomputed(name, out), option if recorded is None else recorded,
                   origin=origin)

    commit("Rotate", "crop", CropParams(rotate=90), "")
    commit("Flip H", "crop", CropParams(flip_h=True), "")
    commit("Flip V", "crop", CropParams(flip_v=True), "")
    # Rotated, so the picture the box is drawn on is 24 wide and 36 tall.
    commit("Crop", "crop", CropParams(bounds=(2, 30, 1, 20)),
           CropParams(bounds=(2, 30, 1, 20), aspect="2:3", source_size=(24, 36)))
    commit("Color", "color", ColorSettings(method="sky"))
    commit("Colour Tint", "tint", (0.25, -0.1))
    # An Auto Enhance run: a replayed Stretch and Levels and a cached Curves,
    # each carrying the run beside its option.
    vivid = run_origin(AUTO_ENHANCE, "Vivid")
    commit("Stretch", "stretch", new_stretch_option(0.3, linked=False), origin=vivid)
    commit("Levels", "levels", new_levels_option(auto=True, offsets=(0.0, 0.0, -0.01)),
           origin=vivid)
    commit("Curves", "curves", {curve_key("rgb", "all"): [(0, 0), (0.25, 0.3), (1, 1)],
                                curve_key("s", "reds"): [(0, 0), (0.5, 0.6), (1, 1)]},
           origin=vivid)
    # Cached steps: an external engine (NR), dialog tools, a split tap, a Trim.
    def cached(name, option, k, origin=None):
        cur = p.current()
        p.record_precomputed(name, option, AstroImage(cur.data * k, is_linear=False,
                                                      metadata=cur.metadata), origin=origin)
    cached("Noise Reduction", {"engine": "rcastro", "level": "strong", "ran": "graxpert"},
           0.99, vivid)
    cached("Narrowband", serialize_option("narrowband", NarrowbandParams(palette=GOLD_BLUE)),
           0.99)
    cached("Colour Balance", {"shadows": [0, 0, 0], "midtones": [0.02, 0, -0.01],
                              "highlights": [0, 0, 0], "preserve_lum": True, "strength": 1.0,
                              "lo": 0.1, "hi": 0.6, "feather": 0.08, "invert": False}, 0.99)
    cached("Star Spikes", {"length": 0.35, "count": 4, "angle": 45.0,
                           "intensity": 0.6, "variation": 0.2, "colour": 0.5}, 0.98)
    cached("Star Colour", {"ran": "StarNet2"}, 0.98)
    h, w = p.current().data.shape[:2]
    trim = CropParams(bounds=(1, h - 1, 2, w - 2))
    p.run_step(_Precomputed("Trim", make_step("crop", s).apply(p.current(), trim)),
               {"aspect": "Free", "bounds": [1, h - 1, 2, w - 2], "source_size": [w, h]})
    return p


def _report(project) -> str:
    return build_report(project.entries(), project.meta_at(project.position),
                        app_version="0.54.0", date=datetime.date(2026, 10, 16),
                        origins=project.origins())


def test_the_report_after_save_and_reopen_is_the_live_report(tmp_path):
    p = _live(tmp_path)
    live = _report(p)
    save_project(p, str(tmp_path / "r.nocturne"), source_label="ic1805.fit")
    lp = load_project(str(tmp_path / "r.nocturne"), str(tmp_path / "reopen")).project
    assert _report(lp) == live
    # And it is the report it should be, not merely the same one twice.
    for line in ("1. Rotate", "2. Flip H", "3. Flip V",
                 "4. Crop — 2:3, 19 × 28 px from 24 × 36",
                 "- kept: 19 × 28 px of 24 × 36, left 1, top 2",
                 "5. Color — Sky balance",
                 "6. Colour Tint — tint +0.25, temperature −0.10",
                 "_Steps 7–10 — applied by Auto Enhance (Vivid)_",
                 "7. Stretch — 0.3 unlinked",
                 "8. Levels — auto (stops at the clipping limit), blue −0.010",
                 "9. Curves",
                 "- RGB curve: 3 points — brightens the shadows, midtones and highlights "
                 "(in 0.250 → out 0.300)",
                 "- Saturation curve, Reds only: 3 points — raises saturation "
                 "(in 0.500 → out 0.600)",
                 "10. Noise Reduction — strong, GraXpert",
                 "11. Narrowband — SHO-style (gold and blue)", "- gold: 100%",
                 "12. Colour Balance — midtones", "- Midtones: Cyan — Red +2, Yellow — Blue −1",
                 "13. Star Spikes", "- number of stars: 4",
                 "14. Star Colour", "- Star Colour: **StarNet2**",
                 "15. Trim — Free, 15 × 26 px from 19 × 28",
                 "- Noise Reduction: **GraXpert**"):
        assert line in live, line
    assert "Crop — Free" not in live
    for i in range(len(p.entries()) + 1):
        np.testing.assert_array_equal(lp.state_at(i).data, p.state_at(i).data)


def test_a_second_save_and_reopen_changes_nothing(tmp_path):
    """The re-save is where the wrong name used to become permanent."""
    p = _live(tmp_path)
    live = _report(p)
    save_project(p, str(tmp_path / "a.nocturne"))
    once = load_project(str(tmp_path / "a.nocturne"), str(tmp_path / "o1")).project
    save_project(once, str(tmp_path / "b.nocturne"))
    twice = load_project(str(tmp_path / "b.nocturne"), str(tmp_path / "o2")).project
    assert _report(twice) == live
