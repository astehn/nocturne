import json
import os
import pytest
import numpy as np
from nocturne.core.image import AstroImage
from nocturne import user_presets as up

SPIKES = {"length": 0.35, "count": 6, "angle": 45.0, "intensity": 0.8,
          "variation": 0.1, "colour": 0.5}
STEPS = [{"stage": "background", "option": "strong"},
         {"stage": "stretch", "option": {"amount": 0.3, "linked": True}},
         {"stage": "levels", "option": "auto"},
         {"stage": "star_spikes", "option": SPIKES},
         {"stage": "enhance", "option": "Vibrance"}]
JPEG = b"\xff\xd8fakejpeg\xff\xd9"


def _lib(tmp_path):
    return up.PresetLibrary(str(tmp_path / "presets"))


def test_round_trip_steps_metadata_and_preview(tmp_path):
    lib = _lib(tmp_path)
    p = lib.save("M 8", STEPS, JPEG, target="M 8", data_type="dualband",
                 left_out=["Mystery"], now=1_760_000_000)
    [q] = lib.list()
    assert (q.name, q.target, q.data_type, list(q.steps), q.left_out) == \
           ("M 8", "M 8", "dualband", STEPS, ("Mystery",))
    assert q.step_count == 5 and q.created == p.created and q.last_used == ""
    from nocturne import __version__
    assert q.app == __version__
    assert open(q.preview_path, "rb").read() == JPEG
    assert os.path.dirname(q.preview_path) == q.folder


def test_steps_for_preset_excludes_geometry_and_names_the_uncapturable():
    entries = [("Crop", None), ("Rotate", ""), ("Stretch", 0.3), ("Trim", {"aspect": "1:1"}),
               ("Star Spikes", ""), ("Vibrance", ""), ("Flip V", "")]
    steps, left = up.steps_for_preset(entries)
    assert [s["stage"] for s in steps] == ["stretch", "enhance"]
    assert left == ["Star Spikes"]


def test_a_killed_save_leaves_the_old_preset_intact(tmp_path, monkeypatch):
    lib = _lib(tmp_path)
    lib.save("M 8", STEPS[:2], JPEG, now=1)
    before = [(p.name, p.steps, open(p.preview_path, "rb").read()) for p in lib.list()]
    real = os.replace
    def die(src, dst, *a, **k):
        if os.path.basename(str(src)).startswith(".part-"):
            raise KeyboardInterrupt("killed")       # mid-save, after files are written
        return real(src, dst, *a, **k)
    monkeypatch.setattr(up.os, "replace", die)
    with pytest.raises(KeyboardInterrupt):
        lib.save("M 8", STEPS, b"new", now=2)
    monkeypatch.setattr(up.os, "replace", real)
    after = [(p.name, p.steps, open(p.preview_path, "rb").read()) for p in lib.list()]
    assert after == before                          # unchanged, not merely "not new"


def test_overwrite_replaces_the_same_name(tmp_path):
    lib = _lib(tmp_path)
    lib.save("M 8", STEPS[:1], JPEG, now=1)
    lib.save("m 8 ", STEPS, JPEG, now=2)
    [p] = lib.list()
    assert p.step_count == 5
    assert len([d for d in os.listdir(lib.root) if not d.startswith(".")]) == 1


def test_duplicate_names_after_an_interrupted_overwrite_show_once(tmp_path):
    lib = _lib(tmp_path)
    old = lib.save("M 8", STEPS[:1], JPEG, now=1)
    new = lib.save("Other", STEPS, JPEG, now=2)
    m = json.load(open(os.path.join(new.folder, up.MANIFEST)))   # hand-make the dup
    m["name"] = "M 8"
    json.dump(m, open(os.path.join(new.folder, up.MANIFEST), "w"))
    names = [p.name for p in lib.list()]
    assert names.count("M 8") == 1 and lib.find("M 8").id == new.id


def test_list_skips_a_corrupt_preset_and_keeps_the_rest(tmp_path):
    lib = _lib(tmp_path)
    good = lib.save("Good", STEPS, JPEG, now=1)
    bad = lib.save("Bad", STEPS, JPEG, now=2)
    open(os.path.join(bad.folder, up.MANIFEST), "w").write('{"name": "Ba')
    os.makedirs(os.path.join(lib.root, ".part-stale"))
    os.makedirs(os.path.join(lib.root, "empty-folder"))
    assert [p.id for p in lib.list()] == [good.id]


def test_missing_optional_fields_load_with_defaults(tmp_path):
    folder = tmp_path / "presets" / "abc"
    folder.mkdir(parents=True)
    (folder / up.MANIFEST).write_text(json.dumps({"name": "Old", "steps": STEPS[:1]}))
    p = up.load_preset(str(folder))
    assert (p.target, p.data_type, p.last_used, p.app, p.left_out) == ("", "unknown", "", "", ())


@pytest.mark.parametrize("manifest,why", [
    ({"format": 99, "name": "X", "steps": []}, "newer version"),
    ({"steps": []}, "name"),
    ({"name": "X", "steps": "nope"}, "steps"),
    ({"name": "X", "steps": [{"option": 1}]}, "stage"),
])
def test_unusable_presets_are_refused_clearly(tmp_path, manifest, why):
    folder = tmp_path / "p"
    folder.mkdir()
    (folder / up.MANIFEST).write_text(json.dumps(manifest))
    with pytest.raises(up.PresetError, match=why):
        up.load_preset(str(folder))


def test_a_preset_from_another_app_version_still_loads(tmp_path):
    lib = _lib(tmp_path)
    p = lib.save("M 8", STEPS, JPEG)
    m = json.load(open(os.path.join(p.folder, up.MANIFEST)))
    m["app"] = "0.1.0"
    json.dump(m, open(os.path.join(p.folder, up.MANIFEST), "w"))
    assert lib.find("M 8").app == "0.1.0"


def test_a_retired_stage_still_loads_and_is_left_out_by_name(tmp_path):
    from nocturne.settings import Settings
    p = up.Preset(id="x", name="Old", steps=({"stage": "ai_denoise", "option": "x"},
                                              {"stage": "stretch", "option": {"amount": 0.3}}))
    plan = up.preset_plan(p, Settings())
    assert [s for s, _ in plan.plan] == ["stretch"]
    assert plan.left_out[0][0] == "Linear Denoise"


def test_preset_plan_names_a_tool_that_is_not_set_up(tmp_path):
    from nocturne.settings import Settings
    p = up.Preset(id="x", name="M 8", steps=tuple(STEPS))
    plan = up.preset_plan(p, Settings())                 # no GraXpert configured
    assert "background" not in [s for s, _ in plan.plan]
    assert plan.left_out[0][0] == "Background"
    # Preset scope: the preset-only Star Spikes runs; only Background is left out.
    assert [s for s, _ in plan.plan] == ["stretch", "levels", "star_spikes", "enhance"]
    assert len(plan.left_out) == 1


def test_preset_plan_never_runs_geometry_even_if_a_file_holds_it():
    from nocturne.settings import Settings
    p = up.Preset(id="x", name="X", steps=({"stage": "crop", "option": {}},
                                            {"stage": "stretch", "option": {"amount": 0.3}}))
    assert [s for s, _ in up.preset_plan(p, Settings()).plan] == ["stretch"]


def test_rename_and_its_clashes(tmp_path):
    lib = _lib(tmp_path)
    a = lib.save("A", STEPS, JPEG, now=1)
    lib.save("B", STEPS, JPEG, now=2)
    a2 = lib.rename(a, "A prime")
    assert lib.find("A prime").id == a.id and a2.created == a.created
    with pytest.raises(up.PresetError):
        lib.rename(a2, " b ")
    with pytest.raises(up.PresetError):
        lib.rename(a2, "   ")
    lib.rename(a2, "a PRIME")                            # its own name, new case: allowed


def test_delete_removes_the_folder(tmp_path):
    lib = _lib(tmp_path)
    p = lib.save("A", STEPS, JPEG)
    lib.delete(p)
    assert lib.list() == [] and not os.path.exists(p.folder)


def test_touch_sets_last_used_and_nothing_else(tmp_path):
    lib = _lib(tmp_path)
    p = lib.save("A", STEPS, JPEG, now=1)
    before = json.load(open(os.path.join(p.folder, up.MANIFEST)))
    lib.touch(p, now=1_760_000_000)
    after = json.load(open(os.path.join(p.folder, up.MANIFEST)))
    assert after.pop("last_used") and before.pop("last_used") == ""
    assert after == before


def test_names_compare_casefolded_and_stripped():
    assert up.same_name(" M 8", "m 8 ") and not up.same_name("M 8", "M 81")


def test_awkward_names_round_trip(tmp_path):
    lib = _lib(tmp_path)
    for n in ("a/b:c", "Nébuleuse 🌌", "x" * 200):
        lib.save(n, STEPS, JPEG)
        assert lib.find(n).name == n
    assert all(len(os.path.basename(p.folder)) == 32 for p in lib.list())   # uuid hex, never the name


def _p(name, created, last="", target="", dt="unknown"):
    return up.Preset(id=name, name=name, steps=(), target=target, data_type=dt,
                     created=created, last_used=last)


def test_sorting():
    ps = [_p("b", "2026-10-01T00:00:00Z", "2026-10-12T00:00:00Z", "M 31"),
          _p("A", "2026-10-03T00:00:00Z", "", ""),
          _p("c", "2026-10-02T00:00:00Z", "2026-10-13T00:00:00Z", "M 8")]
    key = lambda k: [p.name for p in up.sort_presets(ps, k)]
    assert key("created") == ["A", "c", "b"]
    assert key("last_used") == ["c", "b", "A"]
    assert key("name") == ["A", "b", "c"]
    assert key("target") == ["b", "c", "A"]
    assert key("bogus") == key("created")


def test_filtering():
    ps = [_p("Heart", "1", target="IC 1805", dt="dualband"), _p("Andromeda", "2", target="M 31",
          dt="broadband"), _p("Old", "3", dt="unknown")]
    assert [p.name for p in up.filter_presets(ps, "m 3")] == ["Andromeda"]
    assert [p.name for p in up.filter_presets(ps, "ic")] == ["Heart"]
    assert [p.name for p in up.filter_presets(ps, data_type="dualband")] == ["Heart", "Old"]


@pytest.mark.parametrize("preset_t,pic_t,ok,note", [
    ("dualband", "broadband", False, "dual-band"), ("dualband", "unknown", False, "dual-band"),
    ("dualband", "dualband", True, ""), ("broadband", "dualband", True, "broadband"),
    ("broadband", "broadband", True, ""), ("unknown", "dualband", True, "")])
def test_can_apply(preset_t, pic_t, ok, note):
    got_ok, got_note = up.can_apply(_p("x", "1", dt=preset_t), pic_t)
    assert got_ok == ok and (note in got_note if note else got_note == "")


def test_saved_label_is_honest_about_where_it_came_from():
    import calendar
    t = calendar.timegm((2026, 10, 13, 12, 0, 0))
    p = up.Preset(id="x", name="My look", steps=(), target="M 8",
                  created="2026-10-13T12:00:00Z")
    assert up.saved_label(p, now=t) == "M 8 · saved 13 Oct"
    assert up.saved_label(p, now=t + 400 * 86400).endswith("13 Oct 2026")


def test_preview_is_600_px_from_the_display_pixels():
    from PIL import Image
    import io
    img = AstroImage(np.random.default_rng(0).random((900, 1600, 3)).astype(np.float32),
                     is_linear=False, metadata={})
    im = Image.open(io.BytesIO(up.preview_jpeg(img)))
    assert im.format == "JPEG" and max(im.size) == 600


def test_presets_dir_is_beside_the_settings_file(tmp_path):
    assert up.presets_dir(str(tmp_path / "settings.json")) == str(tmp_path / "presets")
