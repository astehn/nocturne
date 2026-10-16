"""Noise Reduction records the engine that RAN beside the one chosen
(2026-10-16). The option's "engine" is a preference — an "rcastro" request runs
GraXpert on a machine without RC-Astro — and the provenance report printed it as
though it had run."""
import numpy as np

from nocturne.core.image import AstroImage
from nocturne.recipe import recipe_from_entries
from nocturne.steps.noise_sharpen import NoiseSharpenStep, parse_noise_option, strip_ran


class _Tool:
    def denoise(self, img, *a, **k):
        return img


def _img():
    return AstroImage(np.random.default_rng(1).random((16, 16, 3)).astype(np.float32),
                      is_linear=False)


def _ran(step, option):
    step.apply(_img(), option)
    return step.recorded_option(option)


def test_the_engine_that_ran_is_recorded_not_the_one_asked_for():
    asked = {"engine": "rcastro", "level": "strong"}
    # RC-Astro absent, GraXpert present: GraXpert runs.
    rec = _ran(NoiseSharpenStep(None, _Tool()), asked)
    assert rec == {"engine": "rcastro", "level": "strong", "ran": "graxpert"}
    assert asked == {"engine": "rcastro", "level": "strong"}       # not mutated
    assert _ran(NoiseSharpenStep(_Tool(), _Tool()), asked)["ran"] == "rcastro"
    assert _ran(NoiseSharpenStep(None, None), asked)["ran"] == "free"
    assert _ran(NoiseSharpenStep(_Tool(), _Tool()),
                {"engine": "free", "level": "light"})["ran"] == "free"


def test_the_record_still_reads_as_the_same_choice():
    """Every reader that predates the key reads engine and level only."""
    rec = _ran(NoiseSharpenStep(None, _Tool()), {"engine": "rcastro", "level": "light"})
    assert parse_noise_option(rec) == ("rcastro", "light")
    assert strip_ran(rec) == {"engine": "rcastro", "level": "light"}


def test_a_legacy_bare_level_is_recorded_as_it_was():
    assert _ran(NoiseSharpenStep(_Tool(), None), "medium") == "medium"


def test_a_recipe_carries_the_choice_not_what_ran_on_one_picture():
    rec = {"engine": "rcastro", "level": "strong", "ran": "graxpert"}
    steps = recipe_from_entries([("Noise Reduction", rec)]).steps
    assert steps == [{"stage": "noise_sharpen",
                      "option": {"engine": "rcastro", "level": "strong"}}]
