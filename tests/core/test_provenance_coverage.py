"""Every step a commit can record reads in words in the provenance report.

The step list is DERIVED from the code — the pipeline's name tables, the
recipe map, and every literal name `main_window` hands `_PrecomputedStep` — so
a new tool cannot join the history without this test asking how the report
should print it. The audit (2026-10-16) found raw dicts ("neutralize_background:
True"), internal ids ("rcastro", "nr:v20.0"), list reprs and Python booleans
in reports; every one of those is what this rejects.
"""
import datetime
import re
from pathlib import Path

import pytest

from nocturne.core.color import ColorSettings
from nocturne.core.crop import CropParams
from nocturne.core.curves import curve_key
from nocturne.core.levels import new_levels_option
from nocturne.core.narrowband import GOLD_BLUE, NarrowbandParams
from nocturne.core.provenance import PRESET, build_report, run_origin
from nocturne.recipe import _NAME_TO_STAGE, PRESET_ONLY_STAGES
from nocturne.steps.stretch_step import new_stretch_option
from nocturne.ui.pipeline import ENHANCE_NAMES, GEOMETRY_NAMES, RETIRED_NAMES, STEP_NAME

_MW = (Path(__file__).parents[2] / "nocturne" / "ui" / "main_window.py").read_text(
    encoding="utf-8")
_CALL = re.compile(r"(?:_PrecomputedStep|record_precomputed)\(\s*([^,()\n]+),")

# The non-literal names main_window records, and the table each one is drawn
# from: STEP_NAME[stage_id] (STEP_NAME), op (an Enhancements tap, ENHANCE_NAMES),
# name (_apply_geometry: GEOMETRY_NAMES; _record_auto_run: STEP_NAME and taps).
_KNOWN_EXPRESSIONS = {"STEP_NAME[stage_id]", "op", "name"}


def _recordable_names() -> set[str]:
    literals, expressions = set(), set()
    for arg in _CALL.findall(_MW):
        arg = arg.strip()
        (literals if arg.startswith('"') else expressions).add(arg.strip('"'))
    assert expressions <= _KNOWN_EXPRESSIONS, (
        f"a new way of naming a history entry: {expressions - _KNOWN_EXPRESSIONS} — "
        "add the table it draws from to this test")
    return (set(STEP_NAME.values()) | set(GEOMETRY_NAMES) | set(ENHANCE_NAMES)
            | set(RETIRED_NAMES) | set(_NAME_TO_STAGE) | set(PRESET_ONLY_STAGES) | literals)


# Recorded with "" because the step has nothing to choose: the name is all.
PARAMETERLESS = set(ENHANCE_NAMES) | {"Rotate", "Flip H", "Flip V"}

# Each option the history can hold for a name — today's shape and the legacy
# shapes old projects carry — as the producers make them.
SAMPLES = {
    "Crop": [CropParams(bounds=(1, 9, 1, 9), aspect="2:3", source_size=(12, 10)),
             CropParams(bounds=(1, 9, 1, 9), aspect="2:3"), CropParams(bounds=(0, 4, 0, 4)),
             {"aspect": "4:5", "rotate": 0, "flip_h": False, "flip_v": False,
              "bounds": [698, 2985, 175, 2005], "source_size": [2180, 3683]},
             {"aspect": "Picture", "rotate": 0, "flip_h": False, "flip_v": False}, ""],
    "Trim": [{"aspect": "16:9", "bounds": [2, 40, 3, 70], "source_size": [80, 50]},
             {"aspect": "16:9"}, {"aspect": "Picture"}, ""],
    "Background": ["strong", "light"],
    "Color": [ColorSettings(method="photometric"), ColorSettings(method="sky"),
              ColorSettings(method="photometric", fell_back=True),
              ColorSettings(method="photometric", stepped_aside=True),
              {"neutralize_background": False, "remove_green": True, "method": "sky"}],
    "Colour Tint": [(0.25, -0.1), [0.0, 0.0], (-1.0, 1.0)],
    "Deconvolution": ["medium"],
    "Stretch": [new_stretch_option(0.27, linked=False), {"amount": 0.12, "linked": True}, 0.4],
    "De-green Sky": [0.8, ""],
    "Remove Green": [0.2],
    "Recover Core": [0.4],
    "Levels": [new_levels_option(auto=True, offsets=(0.0, 0.0, -0.015)),
               new_levels_option(0.071, 1.05, 0.98), "auto", [0.031, 1.0, 1.0]],
    "Curves": [{curve_key("rgb", "all"): [(0, 0), (0.25, 0.3), (1, 1)],
                curve_key("s", "reds"): [(0, 0), (0.5, 0.6), (1, 1)]},
               {curve_key("rgb", "all"): [(0.08, 0), (0.25, 0.2), (0.75, 0.82), (0.95, 1)],
                curve_key("b", "blues"): [(0, 0.02), (0.5, 0.45), (1, 0.97)]},
               [[0.0, 0.0], [0.3, 0.4], [1.0, 1.0]]],
    "Saturation": [(1.3, 0.25), 1.2],
    "De-green Stars": [0.6, 1.0],
    "Remove Green Fringe": [1.0],
    "Noise Reduction": [{"engine": "rcastro", "level": "strong", "ran": "graxpert"},
                        {"engine": "rcastro", "level": "strong"},
                        {"engine": "graxpert", "level": "light"},
                        {"engine": "free", "level": "medium"},
                        {"engine": "nr:v20.0", "level": "strong", "ran": "nr:v20.0"},
                        {"engine": None, "level": "medium", "ran": "rcastro"},
                        "medium"],
    "Local Contrast": [0.35],
    "Star Reduction": [0.4],
    "Narrowband": [NarrowbandParams(palette=GOLD_BLUE), NarrowbandParams(palette="HOO"),
                   NarrowbandParams(palette="Pseudo-SHO", lightness_preserve=True),
                   NarrowbandParams(palette="Pseudo-bicolor", highlight_reduction=3.0),
                   {"palette": "HOO", "blackpoint": 1.0, "oiii_boost": 1.3,
                    "blend_amount": 0.6, "highlight_reduction": 2.0, "brightness": 1.0,
                    "highlight_recover": 1.0, "saturation": 0.85,
                    "lightness_preserve": False, "protect_background": 0.4, "scnr": True}],
    "Colour Balance": [{"shadows": [0, 0, 0], "midtones": [0.02, 0, -0.01],
                        "highlights": [0, 0, 0], "preserve_lum": True, "strength": 1.0,
                        "lo": 0.1, "hi": 0.6, "feather": 0.08, "invert": True},
                       {"shadows": [-0.3, 0.1, 0.25], "midtones": [0, 0, 0],
                        "highlights": [0, -0.07, 0], "preserve_lum": False, "strength": 0.5,
                        "lo": 0.0, "hi": 1.0, "feather": 0.08, "invert": False}],
    "Starless Levels": [(0.04342411776367962, 0.9448416435368755)],
    "Star Spikes": [{"length": 0.35, "count": 4, "angle": 45.0, "intensity": 0.6,
                     "variation": 0.2, "colour": 0.5}, ""],
    "Linear Denoise": ["medium", {"engine": "nr:v7", "level": "strong"}],
    # The two split taps record the splitter (2026-10-17); "" before that.
    "Star Colour": [{"ran": "StarX"}, {"ran": "StarNet2"}, {"ran": "free"}, ""],
    "Sharpen Nebulosity": [{"ran": "free"}, ""],
    "AI Denoise": ["medium", {"engine": "nr:v7", "level": "strong"}],
}

# What a reader must never meet: Python, or the ids the code stores.
_FORBIDDEN = [
    (re.compile(r"[{}\[\]]|'\w+': "), "a dict/list repr"),
    (re.compile(r"\b(True|False|None)\b"), "a Python value"),
    (re.compile(r"\b[a-z]+_[a-z_]+\b"), "a snake_case key"),
    (re.compile(r"\b(rcastro|graxpert|nr:|free)\b"), "an internal engine id"),
    (re.compile(r"\d\.\d{6,}"), "an unrounded float"),
    # 2026-10-17: Curves printed "(0.25, 0.3)" point tuples and its slot keys.
    (re.compile(r"\(\s*-?\d+(\.\d+)?\s*,\s*-?\d"), "a tuple repr"),
    (re.compile(r"\b(rgb|[rgbs])/[a-z]+\b"), "a curve slot key"),
    # A value the panel shows as "−0.10" printed with a hyphen ("-0.1").
    (re.compile(r"(?<![\w.])-\d"), "an ASCII minus"),
]


def _entry_text(report: str, name: str) -> str:
    """The step's own lines: its headline, its Parameters block, its Engines
    line and any note naming the run that applied it."""
    head = [ln for ln in report.splitlines() if re.match(rf"1\. {re.escape(name)}( —|$)", ln)]
    assert head, f"{name} is not listed:\n{report}"
    text = head[0] + "\n"
    for section in ("## Parameters", "## Engines"):
        if section in report:
            text += report.split(section)[1].split("\n## ")[0].split("\n---")[0]
    steps = report.split("## Processing steps")[1].split("\n## ")[0]
    return text + "\n".join(ln for ln in steps.splitlines() if ln.startswith("_"))


def test_every_recordable_name_has_a_sample_or_is_parameterless():
    missing = _recordable_names() - set(SAMPLES) - PARAMETERLESS
    assert not missing, f"new step names with no report sample: {sorted(missing)}"


@pytest.mark.parametrize("name", sorted(set(SAMPLES) | PARAMETERLESS))
def test_each_step_reads_in_words(name):
    options = SAMPLES.get(name, [""])
    for option in options:
        # As a run applied it too: the note above it must read as well.
        r = build_report([(name, option)], {}, app_version="x",
                         date=datetime.date(2026, 10, 16),
                         origins=[run_origin(PRESET, "Lagoon HOO")])
        assert "_Step 1 — from preset ‘Lagoon HOO’_" in r
        text = _entry_text(r, name)
        for pattern, what in _FORBIDDEN:
            found = pattern.search(text)
            assert found is None, f"{name} {option!r} prints {what} ({found.group(0)!r}):\n{text}"
        if name in PARAMETERLESS:
            assert "## Parameters" not in r and f"1. {name}\n" in r + "\n"


@pytest.mark.parametrize("name", ["Color", "Noise Reduction", "Stretch", "Levels", "Curves",
                                  "Narrowband", "Colour Balance", "Star Spikes", "Crop",
                                  "Saturation", "Starless Levels", "Colour Tint"])
def test_a_step_with_settings_shows_them(name):
    """Readable is not the same as present: a renderer that printed nothing
    would pass the test above."""
    r = build_report([(name, SAMPLES[name][0])], {}, app_version="x",
                     date=datetime.date(2026, 10, 16))
    block = r.split("## Parameters")[1]
    assert len([ln for ln in block.splitlines() if ln.startswith("- ")]) >= 1, r
