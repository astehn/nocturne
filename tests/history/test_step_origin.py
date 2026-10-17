"""Steps applied by Auto Enhance or a user preset say so in the report
(2026-10-17). The record sits BESIDE each entry's option, never in it: an
option is compared with panels and replayed by recipes and presets, and which
run applied a step is neither."""
import datetime
import json
import zipfile

import numpy as np

from nocturne.core.image import AstroImage
from nocturne.core.provenance import AUTO_ENHANCE, PRESET, build_report, run_origin
from nocturne.history.project import Project
from nocturne.history.project_store import load_project, save_project
from nocturne.recipe import recipe_from_entries
from nocturne.steps.factory import make_step
from nocturne.steps.stretch_step import new_stretch_option
from nocturne.settings import Settings

VIVID = run_origin(AUTO_ENHANCE, "Vivid")
LAGOON = run_origin(PRESET, "Lagoon HOO")


def _img(p, k):
    cur = p.current()
    return AstroImage(np.clip(cur.data * k, 0, 1), is_linear=cur.is_linear,
                      metadata=dict(cur.metadata))


def _project(tmp_path) -> Project:
    base = AstroImage(np.random.default_rng(4).random((20, 30, 3)).astype(np.float32) * 0.3,
                      is_linear=True, metadata={})
    p = Project(base, str(tmp_path / "live"))
    p.record_precomputed("Background", "strong", _img(p, 0.99), origin=VIVID)
    # A replayable step inside the run: on reopen it is RE-RUN, not restored.
    st = new_stretch_option(0.3)
    p.run_step(make_step("stretch", Settings()), st, origin=VIVID)
    p.record_precomputed("Saturation", [1.3, 0.25], _img(p, 0.98), origin=VIVID)
    p.record_precomputed("Local Contrast", 0.2, _img(p, 0.97))           # by hand
    p.record_precomputed("Star Reduction", 0.3, _img(p, 0.96), origin=LAGOON)
    return p


def _report(p):
    return build_report(p.entries(), {}, app_version="x", date=datetime.date(2026, 10, 17),
                        origins=p.origins())


def test_each_run_is_named_once_above_the_steps_it_applied(tmp_path):
    r = _report(_project(tmp_path))
    steps = r.split("## Processing steps\n\n")[1].split("\n\n## ")[0]
    assert steps.splitlines() == [
        "_Steps 1–3 — applied by Auto Enhance (Vivid)_",
        "",
        "1. Background — strong",
        "2. Stretch — 0.3 linked",
        "3. Saturation",
        "4. Local Contrast — 0.2",
        "",
        "_Step 5 — from preset ‘Lagoon HOO’_",
        "",
        "5. Star Reduction — 0.3",
    ]


def test_a_report_without_origins_is_unchanged(tmp_path):
    p = _project(tmp_path)
    plain = build_report(p.entries(), {}, app_version="x", date=datetime.date(2026, 10, 17))
    assert "Auto Enhance" not in plain and "preset" not in plain
    assert plain == build_report(p.entries(), {}, app_version="x",
                                 date=datetime.date(2026, 10, 17), origins=[None] * 5)


def test_the_options_and_recipes_are_untouched(tmp_path):
    p = _project(tmp_path)
    assert [o for _n, o in p.entries()] == ["strong", new_stretch_option(0.3), [1.3, 0.25],
                                            0.2, 0.3]
    steps = recipe_from_entries(p.entries()).steps
    assert all("applied_by" not in json.dumps(s) and "Vivid" not in json.dumps(s)
               for s in steps)


def test_undo_and_a_new_step_drop_the_origin_with_the_entry(tmp_path):
    p = _project(tmp_path)
    p.undo()
    assert p.origins() == [VIVID, VIVID, VIVID, None]
    p.record_precomputed("Star Reduction", 0.3, _img(p, 0.9))          # by hand now
    assert p.origins() == [VIVID, VIVID, VIVID, None, None]
    p.jump_back(1)
    assert p.origins() == [VIVID]


def test_save_and_reopen_keeps_it_cached_and_replayed_alike(tmp_path):
    p = _project(tmp_path)
    live = _report(p)
    path = str(tmp_path / "o.nocturne")
    save_project(p, path)
    with zipfile.ZipFile(path) as zf:
        steps = json.loads(zf.read("manifest.json"))["steps"]
    assert [s.get("applied_by") for s in steps] == [VIVID, VIVID, VIVID, None, LAGOON]
    assert "applied_by" not in steps[3], "a hand step carries no key at all"
    lp = load_project(path, str(tmp_path / "re")).project
    assert lp.origins() == p.origins()
    assert _report(lp) == live


def test_a_bundle_from_before_the_record_opens_with_none(tmp_path):
    p = _project(tmp_path)
    path = str(tmp_path / "old.nocturne")
    save_project(p, path)
    # Rewrite the manifest as an older build wrote it: no applied_by.
    with zipfile.ZipFile(path) as zf:
        members = {n: zf.read(n) for n in zf.namelist()}
    m = json.loads(members["manifest.json"])
    for st in m["steps"]:
        st.pop("applied_by", None)
    members["manifest.json"] = json.dumps(m).encode()
    with zipfile.ZipFile(path, "w") as zf:
        for n, b in members.items():
            zf.writestr(n, b)
    lp = load_project(path, str(tmp_path / "re")).project
    assert lp.origins() == [None] * 5
