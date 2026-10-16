"""A saved project's report says what the live session's did (audit
2026-10-16: a reopened project renamed Rotate and both flips "Crop"). A real
save and a real load, then the report rendered from each."""
import datetime

import numpy as np

from nocturne.core.color import ColorSettings
from nocturne.core.crop import CropParams
from nocturne.core.image import AstroImage
from nocturne.core.levels import new_levels_option
from nocturne.core.provenance import build_report
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

    def commit(name, stage, option, recorded=None):
        """As MainWindow does: the real step's pixels, the recorded option."""
        out = make_step(stage, s).apply(p.current(), option)
        p.run_step(_Precomputed(name, out), option if recorded is None else recorded)

    commit("Rotate", "crop", CropParams(rotate=90), "")
    commit("Flip H", "crop", CropParams(flip_h=True), "")
    commit("Flip V", "crop", CropParams(flip_v=True), "")
    commit("Crop", "crop", CropParams(bounds=(2, 30, 1, 20)),
           CropParams(bounds=(2, 30, 1, 20), aspect="2:3"))
    commit("Color", "color", ColorSettings(method="sky"))
    commit("Stretch", "stretch", new_stretch_option(0.3, linked=False))
    commit("Levels", "levels", new_levels_option(auto=True, offsets=(0.0, 0.0, -0.01)))
    # Cached steps: an external engine (NR) and a dialog tool (Star Spikes).
    cur = p.current()
    p.record_precomputed("Noise Reduction",
                         {"engine": "rcastro", "level": "strong", "ran": "graxpert"},
                         AstroImage(cur.data * 0.99, is_linear=False, metadata=cur.metadata))
    p.record_precomputed("Star Spikes", {"length": 0.35, "count": 4, "angle": 45.0,
                                         "intensity": 0.6, "variation": 0.2, "colour": 0.5},
                         AstroImage(cur.data * 0.98, is_linear=False, metadata=cur.metadata))
    return p


def _report(project) -> str:
    return build_report(project.entries(), project.meta_at(project.position),
                        app_version="0.54.0", date=datetime.date(2026, 10, 16))


def test_the_report_after_save_and_reopen_is_the_live_report(tmp_path):
    p = _live(tmp_path)
    live = _report(p)
    save_project(p, str(tmp_path / "r.nocturne"), source_label="ic1805.fit")
    lp = load_project(str(tmp_path / "r.nocturne"), str(tmp_path / "reopen")).project
    assert _report(lp) == live
    # And it is the report it should be, not merely the same one twice.
    for line in ("1. Rotate", "2. Flip H", "3. Flip V", "4. Crop — 2:3",
                 "5. Color — Sky balance", "6. Stretch — 0.3 unlinked",
                 "7. Levels — auto (stops at the clipping limit), blue −0.010",
                 "8. Noise Reduction — strong, GraXpert", "9. Star Spikes",
                 "- number of stars: 4", "- Noise Reduction: **GraXpert**"):
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
