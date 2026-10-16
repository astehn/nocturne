"""Upscale Crop's "Open as copy" and Combine open a NEW project with no steps;
the report said "No processing steps applied" about an enlarged or assembled
picture (audit 2026-10-16). It now says what the image's metadata recorded —
and only that."""
import datetime

import numpy as np

from nocturne.core.image import AstroImage
from nocturne.core.provenance import COMBINED_SOURCE_LABEL, build_report
from nocturne.core.upscale import LanczosEngine, UpscaleLayers, finish_upscale

D = datetime.date(2026, 10, 16)


def _upscaled(crop=(10, 30, 20, 60)):
    layer = AstroImage(np.zeros((8, 8, 3), np.float32), is_linear=False)
    layers = UpscaleLayers(starless_up=layer, stars_up=layer,
                           source_meta={"target": "M 8", "source_label": "M8_drizzle.fit"},
                           crop=crop, scale=2, engine_prov=LanczosEngine().provenance())
    return finish_upscale(layers, 0.35).metadata


def test_an_upscaled_copy_says_what_it_was_made_from():
    r = build_report([], _upscaled(), app_version="x", date=D)
    assert "No processing steps applied" not in r
    assert "_No steps applied since it was made._" in r
    made = r.split("## Made from")[1].split("## Processing steps")[0]
    assert "Upscale Crop from M8\\_drizzle.fit" in made
    assert "not part of this project" in made      # its earlier history is not claimed
    for line in ("- Upscale: 2× (Lanczos)", "- Region of the source: 40 × 20 px, left 20, top 10",
                 "- Star tightening: 0.35", "- Detail: enlarged only, no synthesized detail"):
        assert line in made, line


def test_the_whole_picture_upscaled_says_so():
    assert "- Region of the source: the whole picture" in build_report(
        [], _upscaled(crop=None), app_version="x", date=D)


def test_steps_after_the_copy_are_listed_under_its_origin():
    r = build_report([("Levels", [0.02, 1.0, 1.0])], _upscaled(), app_version="x", date=D)
    assert "## Made from" in r and "1. Levels" in r


def test_a_combine_opened_before_it_recorded_its_inputs_says_only_that():
    r = build_report([], {}, app_version="x", date=D, source_label=COMBINED_SOURCE_LABEL)
    assert "No processing steps applied" not in r
    assert "were not recorded" in r
    assert "- Ha master" not in r


def test_an_ordinary_picture_with_no_steps_is_unchanged():
    r = build_report([], {}, app_version="x", date=D, source_label="M8.fit")
    assert "_No processing steps applied._" in r and "## Made from" not in r


def test_the_combine_label_is_the_one_main_window_opens_with():
    """The legacy line keys on the label, so the two must be one constant."""
    from pathlib import Path
    src = (Path(__file__).parents[2] / "nocturne" / "ui" / "main_window.py").read_text(
        encoding="utf-8")
    assert "self._open_in_background(img, COMBINED_SOURCE_LABEL," in src
