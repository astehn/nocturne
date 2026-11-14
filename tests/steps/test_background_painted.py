"""Painted Background through the step, recipes, preflight, batch, log and reports."""
import numpy as np
import pytest
from astropy.io import fits

from nocturne.batch import apply_recipe, run_batch
from nocturne.core import provenance, receipt
from nocturne.core.image import AstroImage
from nocturne.recipe import (Recipe, deserialize_option, missing_tools, preflight,
                             serialize_option)
from nocturne.settings import Settings
from nocturne.steps.background import AUTO_MASK_MESSAGE, BackgroundStep, is_painted
from nocturne.steps.factory import make_step
from nocturne.tools.graxpert import GraXpert

AUTO = "Background used Auto-mask — check the result."


def _img(border=False):
    rng = np.random.default_rng(1)
    h, w = 108, 192
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    d = 0.1 + 0.2 * xx / w + rng.normal(0, 0.002, (h, w)).astype(np.float32)
    data = np.repeat(d[..., None], 3, axis=2).astype(np.float32)
    if border:
        data[:, :20] = 0.0
    return AstroImage(data, is_linear=True)


def _opt(strokes=...):
    o = {"method": "painted", "amount": "strong"}
    if strokes is not ...:
        o["strokes"] = strokes
    return o


STROKES = [{"kind": "sky", "radius": 5.04, "points": [[10.04, 20.06], [30.0, 40.0]]},
           {"kind": "nebula", "radius": 8.0, "points": [[90.0, 50.0]]}]


def _no_graxpert_step():
    step = make_step("background", Settings())       # no GraXpert configured
    def boom(*a, **k):
        raise AssertionError("painted route must not run GraXpert")
    step._runner = boom
    return step


def test_painted_option_runs_without_graxpert():
    step = _no_graxpert_step()
    img = _img()
    out = step.apply(img, _opt([]))
    assert step.last_engine == "Nocturne" and step.last_message == ""
    assert out.data.shape == img.data.shape and not np.allclose(out.data, img.data)


def test_recipe_painted_option_without_strokes_says_auto_mask():
    step = _no_graxpert_step()
    step.apply(_img(), _opt())
    assert step.last_message == AUTO == AUTO_MASK_MESSAGE
    # and a later apply with strokes clears it
    step.apply(_img(), _opt([]))
    assert step.last_message == ""


def test_graxpert_options_unchanged_and_off_copies():
    from tests.steps.test_new_steps import _run_background
    for opt in ("light", "strong"):
        _out, args, _i = _run_background(opt)
        assert "-smoothing" in args
    step = BackgroundStep(GraXpert("/fake"))
    img = _img()
    out = step.apply(img, "off")
    assert np.array_equal(out.data, img.data) and out is not img
    assert step.last_engine is None and step.last_message == ""


def test_painted_amount_light_removes_half_of_strong():
    img = _img()
    s = _no_graxpert_step()
    light = s.apply(img, {"method": "painted", "amount": "light", "strokes": []})
    strong = s.apply(img, _opt([]))
    a = float(np.abs(light.data - img.data).mean())
    b = float(np.abs(strong.data - img.data).mean())
    assert 0.4 < a / b < 0.6


def test_removed_view_is_zero_over_black_border():
    """'Show what was removed' is before minus after; a mosaic border must show 0."""
    img = _img(border=True)
    out = _no_graxpert_step().apply(img, _opt([]))
    assert np.array_equal(out.data[:, :20], img.data[:, :20])
    assert np.all((img.data - out.data)[:, :20] == 0.0)


def test_unknown_stroke_kind_names_it():
    bad = _opt([{"kind": "lava", "radius": 3.0, "points": [[1.0, 1.0]]}])
    with pytest.raises(ValueError, match="lava"):
        deserialize_option("background", bad, project=True)
    with pytest.raises(ValueError, match="lava"):
        _no_graxpert_step().apply(_img(), bad)


def test_serialize_project_keeps_strokes_recipe_drops_them():
    opt = _opt(STROKES)
    rounded = _opt([{"kind": "sky", "radius": 5.0, "points": [[10.0, 20.1], [30.0, 40.0]]},
                    {"kind": "nebula", "radius": 8.0, "points": [[90.0, 50.0]]}])
    assert serialize_option("background", opt, project=True) == rounded
    assert "strokes" not in serialize_option("background", opt)
    assert serialize_option("background", _opt([]), project=True)["strokes"] == []
    back = deserialize_option("background", serialize_option("background", opt, project=True),
                              project=True)
    assert back == rounded
    # a recipe-form read never carries strokes, even if a record held them
    assert "strokes" not in deserialize_option("background", rounded)


def test_old_string_options_pass_through():
    for o in ("off", "light", "strong"):
        assert serialize_option("background", o) == o
        assert deserialize_option("background", o) == o
        assert not is_painted(o)


def test_missing_tools_and_preflight_ignore_painted():
    r = Recipe(steps=[{"stage": "background", "option": _opt()}])
    assert missing_tools(r, Settings()) == []
    plan = preflight(r, Settings())[0]
    assert plan.outcome == "run" and plan.engine == "Nocturne"
    # ...while an ordinary GraXpert option still needs it
    g = Recipe(steps=[{"stage": "background", "option": "strong"}])
    assert missing_tools(g, Settings()) == ["GraXpert"]
    assert preflight(g, Settings())[0].outcome == "fail"
    # old "off" records unchanged
    o = Recipe(steps=[{"stage": "background", "option": "off"}])
    assert missing_tools(o, Settings()) == [] and preflight(o, Settings())[0].outcome == "run"


def _fits(path):
    rng = np.random.default_rng(2)
    base = (0.1 + 0.2 * np.linspace(0, 1, 192))[None, :] * np.ones((108, 1))
    d = np.stack([base + rng.normal(0, 0.002, base.shape) for _ in range(3)])
    fits.PrimaryHDU((d * 60000).astype("uint16")).writeto(str(path))


def test_batch_reports_auto_mask_note(tmp_path):
    src = tmp_path / "a.fits"
    _fits(src)
    out = tmp_path / "out"
    out.mkdir()
    recipe = Recipe(steps=[{"stage": "background", "option": _opt()}])
    res = run_batch(recipe, [str(src)], str(out), "TIFF", Settings())
    assert res[0]["ok"] is True, res
    assert "Auto-mask" in res[0]["message"]


def test_log_label_names_painted():
    from nocturne.ui.main_window import MainWindow
    assert MainWindow._step_log_label("background", _opt([]), "Nocturne") == "strong, painted"
    assert MainWindow._step_log_label("background", "strong", "GraXpert") == "strong (GraXpert)"
    assert MainWindow._step_log_label("background", "off", None) == "off"


def test_provenance_and_receipt_name_painted():
    entries = [("Background", _opt(STROKES)), ("Background", "strong")]
    rep = provenance.build_report(entries[:1], {}, app_version="1", date=__import__("datetime").date(2026, 11, 14))
    assert "1. Background — strong, painted" in rep
    assert "- Background: **Nocturne**" in rep
    assert "- sky strokes: 1" in rep and "- nebula strokes: 1" in rep
    old = provenance.build_report(entries[1:], {}, app_version="1",
                                  date=__import__("datetime").date(2026, 11, 14))
    assert "1. Background — strong" in old and "- Background: **GraXpert**" in old
    note = receipt.engine_for("background", Settings(), option=_opt())
    assert note.engine == "Nocturne" and note.reason == "" and not note.unavailable
    # no option -> unchanged answer
    assert receipt.engine_for("background", Settings()).unavailable
