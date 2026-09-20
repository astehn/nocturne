"""A Nocturne NR model can be tried in the app without becoming part of it.

Andreas, 2026-09-18: *"since its not done its not something that should be
pushed in any release, its just for internal testing at this point in time."*

The guarantee is structural rather than a flag: the models live in
~/.nocturne/models, which is outside the repo, outside the PyInstaller spec and
outside the website rsync. A release build has nothing there, so the engine does
not exist in it. These tests pin that, and pin the routing that only matters
while it does exist.
"""
import os

import pytest

from nocturne.core import denoise_model as dm
from nocturne.steps.noise_sharpen import NoiseSharpenStep  # noqa: F401


def test_the_model_folder_is_outside_the_app():
    """If this ever points inside the package, a model becomes shippable — and
    the whole "cannot reach a release" argument quietly stops being true."""
    # The DEFAULT, not the live value: conftest redirects EXTERNAL_DIR so the
    # suite sees a release's empty folder rather than this machine's models.
    here = os.path.dirname(os.path.dirname(os.path.abspath(dm.__file__)))
    assert not dm._DEFAULT_EXTERNAL_DIR.startswith(here), "models must not live in the package"
    assert dm._DEFAULT_EXTERNAL_DIR.startswith(os.path.expanduser("~"))


def test_no_models_means_no_engine(tmp_path, monkeypatch):
    monkeypatch.setattr(dm, "EXTERNAL_DIR", str(tmp_path / "nothing-here"))
    assert dm.external_models() == []
    assert dm.external_path("v6") is None


def test_each_onnx_becomes_one_engine(tmp_path, monkeypatch):
    monkeypatch.setattr(dm, "EXTERNAL_DIR", str(tmp_path))
    (tmp_path / "v6.onnx").write_bytes(b"not a real model")
    (tmp_path / "v7.onnx").write_bytes(b"not a real model")
    (tmp_path / "notes.txt").write_text("ignored")
    assert [label for label, _ in dm.external_models()] == ["v6", "v7"]
    assert dm.external_path("v7") == str(tmp_path / "v7.onnx")


def test_a_missing_model_refuses_instead_of_running_a_different_engine(tmp_path, monkeypatch):
    """THE one that matters. Every other engine here degrades to the next, which
    is right when the user asked for "denoise" and the app picks how. This engine
    is a question about ONE model: silently running GraXpert would answer a
    different question and look like an answer to this one — which is exactly how
    the old 3-channel model kept running after everyone believed it was gone
    (see denoise_model._check_conditioned).
    """
    monkeypatch.setattr(dm, "EXTERNAL_DIR", str(tmp_path))      # empty
    import numpy as np
    from nocturne.core.image import AstroImage
    img = AstroImage(np.zeros((8, 8, 3), np.float32), is_linear=True)
    from nocturne.steps.ai_denoise import AiDenoiseStep
    with pytest.raises(FileNotFoundError):
        AiDenoiseStep().apply(img, {"engine": "nr:v6", "level": "medium"})


def test_the_ordinary_engines_are_untouched(tmp_path, monkeypatch):
    """The prefix must not capture anything that is not ours."""
    from nocturne.steps.noise_sharpen import parse_noise_option
    assert parse_noise_option({"engine": "graxpert", "level": "light"}) == ("graxpert", "light")
    assert parse_noise_option({"engine": "rcastro", "level": "strong"}) == ("rcastro", "strong")
    engine, level = parse_noise_option({"engine": "nr:v6", "level": "medium"})
    assert engine == "nr:v6" and level == "medium"


def test_the_stage_is_pre_stretch_or_the_model_cannot_work(qtbot):
    """Andreas hit this: the engine was first wired to Noise Reduction, which
    sits AFTER Stretch, and every apply refused — *"surely it should work on
    stretched data as well?"*

    It cannot, and the refusal is right. The model is conditioned on ONE
    measured sigma and works in a fixed asinh space over linear 0-1. A stretch
    applies a curve derived from the image's own statistics, so afterwards the
    background noise has been amplified far more than the highlights and no
    single sigma describes the frame any more.
    """
    from nocturne.ui.pipeline import path_stages
    ids = [s.id for s in path_stages(include=frozenset({"ai_denoise"}))]
    assert ids.index("ai_denoise") < ids.index("stretch")
    # And before EVERYTHING that reshapes the image, not just before Stretch.
    # The model is trained on raw stacker output; after Background the sky it
    # sees drops from 0.29 to 0.04 in model space, and after Deconvolution the
    # star profiles are ones it never met. v7 turned a real M 16 grey and ringed
    # its stars in exactly that position (Nocturne NR, 2026-09-19).
    assert ids.index("crop") < ids.index("ai_denoise") < ids.index("background"), \
        "it must see the stack as the stacker left it"


def test_the_stage_is_absent_without_a_model(tmp_path, monkeypatch):
    """Which is every release build — that folder is outside the bundle."""
    from nocturne.ui.pipeline import path_stages
    monkeypatch.setattr(dm, "EXTERNAL_DIR", str(tmp_path))
    assert "ai_denoise" not in [s.id for s in path_stages()]


def test_the_post_stretch_step_does_not_offer_it(qtbot):
    """Noise Reduction must not list a model it can only fail with. It did for
    an hour, and the failure was a red banner rather than a missing option."""
    from nocturne.ui.pipeline import path_stages
    from nocturne.ui.step_panels import build_panel
    stage = next(s for s in path_stages() if s.id == "noise_sharpen")
    panel = build_panel(stage, on_apply=lambda o: None, apply_enabled=True,
                        denoise_engine_choices=["Default", "RC-Astro", "GraXpert"],
                        denoise_default_engine="rcastro")
    qtbot.addWidget(panel)
    labels = [panel.engine_box.itemText(i) for i in range(panel.engine_box.count())]
    assert not any("Nocturne NR" in t for t in labels), labels


def test_the_panel_turns_the_label_back_into_the_engine_id(qtbot):
    """"Nocturne NR (v6)" -> "nr:v6". The label carries the file name so two
    runs sit side by side in the dropdown; the id is what the step routes on."""
    from nocturne.ui.pipeline import path_stages
    from nocturne.ui.step_panels import build_panel
    stage = next(s for s in path_stages(include=frozenset({"ai_denoise"}))
                 if s.id == "ai_denoise")
    got = []
    panel = build_panel(stage, on_apply=got.append, apply_enabled=True,
                        denoise_engine_choices=["Nocturne NR (v6)", "Nocturne NR (v7)"],
                        denoise_default_engine="rcastro")
    qtbot.addWidget(panel)
    panel.engine_box.setCurrentText("Nocturne NR (v6)")
    panel.apply_btn.click()
    assert got and got[-1]["engine"] == "nr:v6"

    panel.engine_box.setCurrentText("Nocturne NR (v7)")
    panel.apply_btn.click()
    assert got[-1]["engine"] == "nr:v7"


# The "no model is committed" guard used to live here, asserting that the
# already-shipping v1 was the only tracked .onnx. v1 was removed from the repo
# on 2026-09-18, so the fact is now simply "none", and it belongs with the
# packaging guards rather than with this engine — see tests/test_no_model_ships.py.
# Two tests owning one fact is how one of them goes stale unnoticed.
