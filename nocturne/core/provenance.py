"""Human-readable Markdown provenance report: capture header + the ordered edit
pipeline as a narrative (with headline choices) plus a full-parameter detail
section. Pure — pass `date`/`app_version` in. Reuses recipe serialization so it
never re-parses step options."""
from __future__ import annotations

import datetime
import re

from ..recipe import _NAME_TO_STAGE, serialize_option
from .crop import shape_label
from .fits_io import format_integration, resolve_integration
from .instrument import DEFAULT_INSTRUMENT, identify

# dict-option steps whose headline choice is a single field of the serialized dict
_HEADLINE_FIELD = {
    "Background": "engine",
    "Narrowband": "palette",
    "Crop": "aspect",
    "Trim": "aspect",
}

# Steps whose recorded "aspect" is a stored shape name. The report says the
# word on the button ("Original", "2:3"), never the internal "Picture".
_SHAPE_STEPS = ("Crop", "Trim")

_FAILED = object()   # sentinel: this step's option could not be serialized


def _serialize(name: str, option):
    """Normalize a recorded option to a JSON-friendly value (scalar / dict /
    list), matching how the project store persists it. Native objects
    (CropParams/ColorSettings/…) go through serialize_option."""
    if option is None or isinstance(option, (int, float, str, bool, dict)):
        return option
    if isinstance(option, (list, tuple)):
        return list(option)
    return serialize_option(_NAME_TO_STAGE.get(name, name), option)


def _num(v) -> str:
    """A number as a person reads it: "1.64", not "1.6400000000000001"."""
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return str(round(v, 4))
    return str(v)


# ---- Colour ----------------------------------------------------------------
# The panel's own words (step_panels: "Sky balance" / "Photometric (SPCC)").
_COLOUR_METHOD = {"sky": "Sky balance", "photometric": "Photometric (SPCC)"}
# One wording for the built-in, shared with core.receipt's fallback name.
SKY_BALANCE_ENGINE = "Nocturne (built-in sky balance)"


def _colour_method(ser: dict) -> str:
    m = ser.get("method", "sky")
    return _COLOUR_METHOD.get(m, str(m))


def _colour_headline(ser: dict) -> str:
    method = _colour_method(ser)
    if ser.get("stepped_aside"):
        return f"{method} → stepped aside on dual-band data; sky balance"
    if ser.get("fell_back"):
        return f"{method} → fell back to sky balance"
    return method


def _colour_params(ser: dict) -> list[str]:
    lines = [f"- method: {_colour_method(ser)}"]
    if ser.get("stepped_aside"):
        lines.append("- result: sky balance — photometric calibration is not meaningful "
                     "through a dual-band filter")
    elif ser.get("fell_back"):
        lines.append("- result: sky balance — photometric calibration could not run")
    # Settings with no control on today's panel: named only when they differ
    # from what every Colour step does, so the block is not padded with them.
    if ser.get("neutralize_background") is False:
        lines.append("- background neutralisation: off")
    if ser.get("remove_green"):
        lines.append("- green removed as part of this step: yes")
    return lines


# ---- Noise Reduction -------------------------------------------------------
# The engine ids the option stores, in the names the Engine box shows.
_NR_NAMES = {"rcastro": "NoiseXTerminator", "graxpert": "GraXpert",
             "free": "Nocturne (built-in denoise)"}


def _nr_name(engine) -> str:
    """"NoiseXTerminator" for "rcastro", "Nocturne NR — Odin (v20.0)" for a
    model id. The model's name is looked up now; a removed one reads by id."""
    from . import nr_models
    if isinstance(engine, str) and engine.startswith(nr_models.PREFIX):
        return nr_models.engine_label(engine[len(nr_models.PREFIX):])
    return _NR_NAMES.get(engine, "") if isinstance(engine, str) else ""


def _nr_ran(ser) -> tuple[str, bool]:
    """(engine name, known): the engine that ran when the record says so. A
    model and the built-in are never substituted, so asking for one IS
    running it; a request for NoiseXTerminator or GraXpert falls back when
    that tool is missing, and before 2026-10-16 nothing recorded which ran."""
    from . import nr_models
    if not isinstance(ser, dict):
        return "", False
    if ran := _nr_name(ser.get("ran")):
        return ran, True
    engine = ser.get("engine")
    if engine == "free" or (isinstance(engine, str) and engine.startswith(nr_models.PREFIX)):
        return _nr_name(engine), True
    return _nr_name(engine), False


def _nr_headline(ser: dict) -> str:
    level = str(ser.get("level", "medium"))
    name, known = _nr_ran(ser)
    if not name:
        return level
    return f"{level}, {name}" if known else f"{level}, {name} requested"


def _nr_params(ser: dict) -> list[str]:
    lines = [f"- strength: {ser.get('level', 'medium')}"]
    name, known = _nr_ran(ser)
    asked = _nr_name(ser.get("engine"))
    if known:
        line = f"- engine: {name}"
        if asked and asked != name:
            line += f" ({asked} was chosen and is not what ran)"
        lines.append(line)
    elif name:
        lines.append(f"- engine: not recorded — {name} was requested, and Nocturne "
                     "uses another tool when the requested one is not set up")
    else:
        lines.append("- engine: not recorded")
    return lines


# ---- Crop / Trim -----------------------------------------------------------
def _shape_params(ser: dict) -> list[str]:
    lines = [f"- shape: {ser.get('aspect', '')}"] if ser.get("aspect") else []
    # Only what this entry did. A Crop records rotate 0 and both flips off on
    # every entry (one params object for all geometry); printing them under
    # every Crop read as though the crop had been asked to do them.
    if (rot := ser.get("rotate")) not in (None, 0):
        lines.append(f"- turned: {rot}° clockwise")
    if ser.get("flip_h"):
        lines.append("- flipped: left to right")
    if ser.get("flip_v"):
        lines.append("- flipped: top to bottom")
    return lines


# ---- Stretch / Curves ------------------------------------------------------
def _stretch_params(ser: dict) -> list[str]:
    lines = [f"- amount: {_num(ser.get('amount'))}",
             f"- colour channels: {'linked' if ser.get('linked', True) else 'unlinked'}"]
    if "version" in ser:
        lines.append(f"- stretch version: {ser['version']}")
    return lines


_CURVE_CHANNEL = {"rgb": "RGB", "r": "Red", "g": "Green", "b": "Blue", "s": "Saturation"}


def _curves_params(ser) -> list[str]:
    from .curves import normalize_curves
    lines = []
    for key, pts in normalize_curves(ser).items():
        channel, _, target = key.partition("/")
        label = _CURVE_CHANNEL.get(channel, channel)
        if target and target != "all":
            label += f", {target} only"
        path = " → ".join(f"({_num(float(x))}, {_num(float(y))})" for x, y in pts)
        lines.append(f"- {label} curve: {path}")
    return lines or ["- no curve set"]


# ---- Tools with dialogs ----------------------------------------------------
def _narrowband_params(ser: dict) -> list[str]:
    """The dialog's controls by the labels beside them, in its order, in the
    units its value labels show (narrowband_dialog._update_value_labels).
    Fields with no control (black point, SCNR…) are fixed and not listed."""
    from .narrowband import GOLD_BLUE, PALETTES_USING_BLEND
    gold_blue = ser.get("palette") == GOLD_BLUE
    lines = [f"- palette: {ser.get('palette', '')}"]
    if "oxygen_strength" in ser:
        oxy = float(ser["oxygen_strength"])
        lines.append(f"- oxygen strength: {round(oxy * 100)}%" if gold_blue
                     else f"- oxygen strength: ×{oxy:.2f}")
    elif "oiii_boost" in ser:
        # The control before 2026-09-09; it has no equivalent today.
        lines.append(f"- OIII boost (an earlier control): ×{float(ser['oiii_boost']):.2f}")
    # Greyed in the dialog where they do nothing (narrowband_dialog
    # ._update_palette_controls): not listed as though they had an effect.
    if "blend_amount" in ser and ser.get("palette") in PALETTES_USING_BLEND:
        lines.append(f"- green blend: {float(ser['blend_amount']):.2f}")
    if "protect_background" in ser:
        lines.append(f"- protect background: {round(float(ser['protect_background']) * 100)}%")
    if gold_blue:
        for key, label in (("gold_strength", "gold"), ("blue_strength", "blue")):
            if key in ser:
                lines.append(f"- {label}: {round(float(ser[key]) * 100)}%")
    elif "saturation" in ser:
        lines.append(f"- saturation: {float(ser['saturation']):.2f}")
    if "highlight_reduction" in ser:
        from .narrowband import TAME_SPAN as span
        tame = round((float(ser["highlight_reduction"]) - 1.0) / span * 100)
        lines.append(f"- tame core: {'off' if tame <= 0 else f'{tame}%'}")
    if "brightness" in ser:
        lines.append(f"- brightness: ×{float(ser['brightness']):.2f}")
    if "lightness_preserve" in ser and not gold_blue:
        lines.append(f"- preserve lightness: {_num(bool(ser['lightness_preserve']))}")
    return lines


# Colour Balance's three sliders run Cyan—Red, Magenta—Green, Yellow—Blue from
# −100 to +100 (color_balance_dialog._AXES); the option stores them / 100.
_CB_AXES = ("red", "green", "blue")


def _colour_balance_params(ser: dict) -> list[str]:
    from .color_balance import TONES
    lines = []
    for tone in TONES:
        v = ser.get(tone) or (0, 0, 0)
        if not any(float(x) for x in v):
            continue
        moved = ", ".join(f"{axis} {round(float(x) * 100):+d}".replace("-", "−")
                          for axis, x in zip(_CB_AXES, v) if round(float(x) * 100))
        lines.append(f"- {tone}: {moved}")
    if not lines:
        lines.append("- no tonal range moved")
    lines.append(f"- preserve luminosity: {_num(bool(ser.get('preserve_lum', True)))}")
    lines.append(f"- strength: {round(float(ser.get('strength', 1.0)) * 100)}%")
    lo, hi = float(ser.get("lo", 0.0)), float(ser.get("hi", 1.0))
    if (lo, hi) != (0.0, 1.0):
        lines.append(f"- limited to the brightness range {lo:.2f}–{hi:.2f}, "
                     f"feather {float(ser.get('feather', 0.08)):.2f}")
    if ser.get("invert"):
        lines.append("- range inverted: yes (everything outside it was adjusted)")
    return lines


def _spikes_params(ser: dict) -> list[str]:
    """In the dialog's order and units (star_spikes_dialog._on_change)."""
    out = []
    if "length" in ser:
        out.append(f"- length: {float(ser['length']):.2f}")
    if "intensity" in ser:
        out.append(f"- intensity: {round(float(ser['intensity']) * 100)}%")
    if "count" in ser:
        out.append(f"- number of stars: {int(ser['count'])}")
    if "angle" in ser:
        out.append(f"- rotation: {float(ser['angle']):g}°")
    if "variation" in ser:
        out.append(f"- variation: {round(float(ser['variation']) * 100)}%")
    if "colour" in ser:
        out.append(f"- star colour: ×{float(ser['colour']):.2f}")
    return out


_DICT_PARAMS = {
    "Color": _colour_params,
    "Noise Reduction": _nr_params,
    # Retired 2026-10-05; an old project holds it with NR's option shape.
    "Linear Denoise": _nr_params,
    "AI Denoise": _nr_params,
    "Crop": _shape_params,
    "Trim": _shape_params,
    "Stretch": _stretch_params,
    "Curves": _curves_params,
    "Narrowband": _narrowband_params,
    "Colour Balance": _colour_balance_params,
    "Star Spikes": _spikes_params,
}


def _headline(name: str, ser) -> str:
    if ser is _FAILED or ser is None:
        return ""
    if isinstance(ser, bool):
        return str(ser)
    if isinstance(ser, (int, float, str)):
        return f"{ser}"
    if isinstance(ser, dict):
        if name == "Levels":
            return _levels_headline(ser)
        if name == "Stretch" and "amount" in ser:
            # The linkage changes what a stretch does to colour: the headline
            # says it, as the log line does ("0.12 unlinked").
            linked = "linked" if ser.get("linked", True) else "unlinked"
            return f"{ser['amount']} {linked}"
        if name == "Color":
            return _colour_headline(ser)
        if name == "Colour Balance":
            # Not a single field: which of the three tonal ranges were moved.
            from .color_balance import describe
            return describe(ser)
        if name in ("Noise Reduction", "Linear Denoise", "AI Denoise"):
            return _nr_headline(ser)
        field = _HEADLINE_FIELD.get(name)
        if field and ser.get(field) not in (None, ""):
            return f"{ser[field]}"
    return ""   # lists / unmapped dicts -> name only


# What the numbers in a POSITIONAL option mean. Without this the report prints
# "- values: 0.1, 0.9" and the reader has to guess; for Starless Levels those
# two numbers are the entire content of the tool. Names only — the order is the
# option's own, so a wrong name here is a wrong report, and each is pinned by a
# test against the code that produces the tuple.
# The names are the ones the PANEL puts beside each slider (step_panels.py:606,
# 612, 618, 710, 715), so the report and the control the user moved agree.
_POSITIONAL_FIELDS = {
    "Levels": ("black point", "midtones", "white point"),
    "Saturation": ("saturation", "nebula boost"),
    "Starless Levels": ("black point", "white point"),
    # step_panels' Colour Tint sliders: "Green ←→ Magenta", "Cool ←→ Warm".
    "Colour Tint": ("green ←→ magenta", "cool ←→ warm"),
}


def _levels_auto_words(version: int) -> str:
    from .inspect import CRUSHED_LIMIT
    if version >= 2:
        return (f"auto, stopped where needed so no colour is crushed past the "
                f"{CRUSHED_LIMIT * 100:g}% clipping warning")
    return "auto"


def _levels_headline(ser: dict) -> str:
    from .levels import describe_offsets, parse_levels_option
    p = parse_levels_option(ser)
    parts = ["auto (stops at the clipping limit)" if p.auto and p.version >= 2
             else "auto" if p.auto else ""]
    parts.append(describe_offsets(p.offsets))
    return ", ".join(x for x in parts if x)


def _levels_params(ser: dict) -> list[str]:
    """The dict option in the panel's words: what each slider was set to, and
    the colours moved (only when one was)."""
    from .levels import describe_offsets, parse_levels_option
    p = parse_levels_option(ser)
    if p.auto:
        lines = [f"- black point: {_levels_auto_words(p.version)}",
                 "- midtones: 1.000", "- white point: 1.000"]
    else:
        # Three decimals, the offsets' precision: Auto's continuous black
        # printed seventeen digits.
        lines = [f"- black point: {p.black:.3f}", f"- midtones: {p.gamma:.3f}",
                 f"- white point: {p.white:.3f}"]
    if colours := describe_offsets(p.offsets):
        lines.append(f"- one colour's black point: {colours}")
    return lines


def _plain_key(k) -> str:
    return str(k).replace("_", " ")


def _render_params(ser, name: str = "") -> list[str]:
    if isinstance(ser, dict) and name == "Levels":
        return _levels_params(ser)
    if isinstance(ser, dict) and name in _DICT_PARAMS:
        return _DICT_PARAMS[name](ser)
    if isinstance(ser, list) and name == "Curves":
        return _curves_params(ser)      # a bare list is the pre-matrix RGB curve
    if isinstance(ser, dict):
        # A step with no renderer yet: readable keys and values rather than
        # Python, so a new tool degrades to plain words (the every-step test
        # in tests/core/test_provenance_coverage.py names it either way).
        return [f"- {_plain_key(k)}: "
                + (", ".join(_num(x) for x in v) if isinstance(v, (list, tuple)) else _num(v))
                for k, v in ser.items()]
    if isinstance(ser, list):
        fields = _POSITIONAL_FIELDS.get(name)
        # Only when the count matches: a tool that gains a fourth number must
        # fall back to the unlabelled form rather than silently mislabel three
        # of them and drop the new one.
        if fields and len(fields) == len(ser):
            return [f"- {f}: {_num(v)}" for f, v in zip(fields, ser)]
        return [f"- values: {', '.join(_num(v) for v in ser)}"]
    return []


def _human_date(date: datetime.date) -> str:
    return f"{date.day} {date:%B %Y}"


_MD_SPECIAL = re.compile(r"([\\`*_\[\]<>])")


def _md_escape(s) -> str:
    """Escape Markdown/inline specials in free-text metadata (e.g. a FITS OBJECT
    name typed by the user) so it can't corrupt the report's structure."""
    return _MD_SPECIAL.sub(r"\\\1", str(s).replace("\n", " ").replace("\r", " "))


def _capture_lines(metadata: dict) -> list[str]:
    out: list[str] = []
    target = metadata.get("target") or metadata.get("target_solved")
    if target:
        out.append(f"- Target: {_md_escape(target)}")
    integ = resolve_integration(metadata)
    if integ is not None and integ.total_s is not None:
        s = format_integration(integ.total_s)
        if integ.frames is not None and integ.per_sub_s is not None:
            s += f" ({integ.frames} × {integ.per_sub_s:g}s)"
        out.append(f"- Total integration: {s}")
    # This used to print the S30 Pro's sensor unconditionally, which made the
    # report state a falsehood on anyone else's data — in the one document
    # meant to be an authoritative record of how the image was made. Say what
    # the file says, and mark it when we are only assuming.
    if (cam := identify(metadata)) is not None:
        out.append(f"- Camera: {cam.sensor} ({cam.name})")
    else:
        out.append(f"- Camera: {DEFAULT_INSTRUMENT.sensor} (assumed — no camera in the file)")
    if metadata.get("date"):
        out.append(f"- Captured: {_md_escape(str(metadata['date']).split('T')[0])}")
    if metadata.get("target_solved"):
        out.append(f"- Plate solve: {_md_escape(metadata['target_solved'])} (solved)")
    return out


# ---- Where the picture came from -------------------------------------------
# Upscale Crop's "Open as copy" and Combine each open a NEW project: the steps
# list starts empty, and the report said "No processing steps applied" about a
# picture that had been enlarged, or assembled from two masters. What each
# recorded in the image's metadata is said instead — and nothing more.
COMBINED_SOURCE_LABEL = "combined narrowband"   # MainWindow._open_combined's label


def _origin_lines(metadata: dict, source_label: str | None) -> list[str]:
    up = metadata.get("upscale")
    if isinstance(up, dict):
        scale = up.get("scale", "?")
        engine = up.get("engine") or "an unrecorded engine"
        src = metadata.get("source_label")
        out = [f"An enlarged copy made with Upscale Crop"
               + (f" from {_md_escape(src)}" if src else "")
               + ". The processing that produced the picture it was made from is "
               "not part of this project and is not listed here.", ""]
        out.append(f"- Upscale: {scale}× ({_md_escape(engine)})")
        if (crop := up.get("crop")) and len(crop) == 4:
            t, b, l, r = (int(v) for v in crop)
            out.append(f"- Region of the source: {r - l} × {b - t} px, "
                       f"left {l}, top {t}")
        else:
            out.append("- Region of the source: the whole picture")
        if up.get("tighten") is not None:
            out.append(f"- Star tightening: {_num(float(up['tighten']))}")
        if "fabricates" in up:
            out.append("- Detail: contains synthesized detail — not for measurement"
                       if up["fabricates"] else
                       "- Detail: enlarged only, no synthesized detail")
        return out
    comb = metadata.get("combine")
    if isinstance(comb, dict):
        out = ["Combined from separate Ha and OIII masters with Combine: Ha in red, "
               "OIII in green and blue.", ""]
        if comb.get("ha"):
            out.append(f"- Ha master: {_md_escape(comb['ha'])}")
        if comb.get("oiii"):
            out.append(f"- OIII master: {_md_escape(comb['oiii'])}")
        if comb.get("balance") is not None:
            out.append(f"- OIII balance: {round(float(comb['balance']) * 100)}% "
                       "(0% as measured, 100% matched to Ha)")
        if "aligned" in comb:
            shift = comb.get("shift")
            if comb["aligned"] and shift and len(shift) == 2:
                dy, dx = float(shift[0]), float(shift[1])
                out.append(f"- OIII aligned to Ha: moved {_num(abs(dx))} px "
                           f"{'right' if dx >= 0 else 'left'} and {_num(abs(dy))} px "
                           f"{'down' if dy >= 0 else 'up'}")
            else:
                # Either declined, or never offered (the pair was already
                # within tolerance); the record does not say which.
                out.append("- OIII moved to align with Ha: no")
        return out
    if source_label == COMBINED_SOURCE_LABEL:
        # Opened before Combine recorded its inputs (2026-10-16).
        return ["Combined from separate Ha and OIII masters with Combine. Which files, "
                "and the settings used, were not recorded.", ""]
    return []


# ---- Engines ---------------------------------------------------------------
_DECONV_UNRECORDED = ("not recorded — BlurXTerminator when RC-Astro was set up, "
                      "otherwise Nocturne's built-in sharpen")
_SPLIT_UNRECORDED = ("not recorded — the stars were separated by StarXTerminator, "
                     "StarNet2 or Nocturne's own split, whichever was set up")
# Three star steps do NOT fall back to a split: without a star tool they work on
# the whole image, or inside a star mask (core.receipt._FALLBACKS; the log says
# the same, MainWindow._step_log_label).
_WHOLE_UNRECORDED = ("not recorded — the stars were separated by StarXTerminator or "
                     "StarNet2 if one was set up; otherwise it worked on the whole "
                     "image, with nothing separated")
_MASK_UNRECORDED = ("not recorded — the stars were separated by StarXTerminator or "
                    "StarNet2 if one was set up; otherwise it worked inside a star mask")
# Steps whose engine the history does not record, with what can honestly be
# said instead. The star steps are core.receipt's SPLIT_STAGES plus the two
# Enhancements taps that split (steps/enhance_step._LAYERED).
_UNRECORDED = {"Deconvolution": _DECONV_UNRECORDED,
               "Narrowband": _WHOLE_UNRECORDED, "Colour Balance": _WHOLE_UNRECORDED,
               "De-green Stars": _MASK_UNRECORDED,
               **{n: _SPLIT_UNRECORDED for n in (
                   "Saturation", "Star Reduction", "Starless Levels", "Star Colour",
                   "Sharpen Nebulosity")}}
_STAGE_OF = {"Saturation": "saturation", "Star Reduction": "star_reduction"}


def _engine_text(name: str, ser) -> str | None:
    """What ran for one entry, from its record alone, or None when the step has
    no engine choice (or, for a star step, split nothing)."""
    if name == "Background":
        # One implementation: BackgroundStep has only ever called GraXpert.
        return None if ser == "off" else "**GraXpert**"
    if name == "Color":
        if not isinstance(ser, dict):
            return "not recorded"
        if ser.get("stepped_aside"):
            return (f"**{SKY_BALANCE_ENGINE}** — photometric calibration was chosen and "
                    "stepped aside: it isn't meaningful through a dual-band filter")
        if ser.get("fell_back"):
            return (f"**{SKY_BALANCE_ENGINE}** — photometric calibration was chosen "
                    "but could not run")
        if ser.get("method") == "photometric":
            if "fell_back" in ser:
                return "**ASTAP + Gaia** — photometric calibration (SPCC)"
            # Written explicitly since 2026-10-16; before that a successful
            # run and an unrecorded fallback (pre-0.44) looked the same.
            return ("ASTAP + Gaia was chosen (photometric calibration); whether it ran "
                    "or fell back to sky balance was not recorded for this step")
        return f"**{SKY_BALANCE_ENGINE}**"
    if name == "Noise Reduction":
        ran, known = _nr_ran(ser)
        if known:
            return f"**{ran}**"
        if ran:
            return f"not recorded — {ran} was requested"
        return "not recorded"
    if name in _UNRECORDED:
        from .receipt import splits_stars
        if name in _STAGE_OF and not splits_stars(_STAGE_OF[name], ser):
            return None
        return _UNRECORDED[name]
    return None


def _engine_lines(ser_entries, saved_version) -> list[str]:
    """One line per step that has an engine choice, from what its record says
    ran. A step applied more than once with different results is named once
    per result, by step number."""
    by_name: dict[str, list[tuple[int, str]]] = {}
    for i, (name, ser) in enumerate(ser_entries, 1):
        if ser is _FAILED:
            continue
        text = _engine_text(name, ser)
        if text is not None:
            by_name.setdefault(name, []).append((i, text))
    lines = []
    for name, found in by_name.items():
        texts = list(dict.fromkeys(t for _i, t in found))
        if texts == [_SPLIT_UNRECORDED]:
            continue        # said once, for all of them, below
        if len(texts) == 1:
            lines.append(f"- {name}: {texts[0]}")
        else:
            for i, t in found:
                lines.append(f"- {name} (step {i}): {t}")
    # Eight star steps with the same unknown would be eight identical lines.
    split = [n for n, found in by_name.items()
             if [t for _i, t in found] and set(t for _i, t in found) == {_SPLIT_UNRECORDED}]
    if split:
        lines.append(f"- {', '.join(split)}: {_SPLIT_UNRECORDED}")
    return lines


def build_report(entries, metadata, *, app_version: str, date: datetime.date,
                 settings=None, saved_version: str | None = None,
                 source_label: str | None = None) -> str:
    """The Engines section comes from the RECORD — what each step stored about
    the engine that ran — never from today's tool setup, which said "ASTAP +
    Gaia" or "sky balance" according to what is installed now and contradicted
    the steps above it (2026-10-16). `settings` is accepted for older callers
    and no longer read."""
    ser_entries = []
    for name, option in entries:
        try:
            ser = _serialize(name, option)
            if name in _SHAPE_STEPS and isinstance(ser, dict) and "aspect" in ser:
                ser = {**ser, "aspect": shape_label(str(ser["aspect"]))}
            ser_entries.append((name, ser))
        except Exception:
            ser_entries.append((name, _FAILED))

    lines = ["# Nocturne processing report", ""]
    lines.append("## Capture")
    lines += _capture_lines(metadata)
    lines.append("")

    origin = _origin_lines(metadata or {}, source_label)
    if origin:
        lines.append("## Made from")
        lines.append("")
        lines += origin
        lines.append("")

    lines.append("## Processing steps")
    lines.append("")
    if not ser_entries:
        lines.append("_No steps applied since it was made._" if origin
                     else "_No processing steps applied._")
    else:
        for i, (name, ser) in enumerate(ser_entries, 1):
            h = _headline(name, ser)
            lines.append(f"{i}. {name}" + (f" — {h}" if h else ""))
    lines.append("")

    blocks = []
    for i, (name, ser) in enumerate(ser_entries, 1):
        if ser is _FAILED:
            blocks.append((i, name, ["- (parameters unavailable)"]))
        elif isinstance(ser, (dict, list)):
            body = _render_params(ser, name)
            if body:
                blocks.append((i, name, body))
    if blocks:
        lines.append("## Parameters")
        lines.append("")
        for i, name, body in blocks:
            lines.append(f"### {i}. {name}")
            lines += body
            lines.append("")

    # Which implementation ran. Several steps have an external tool and a
    # built-in fallback whose results differ materially, and from the outside
    # the two are the same line in a history.
    engine_lines = _engine_lines(ser_entries, saved_version)
    if engine_lines:
        lines.append("## Engines")
        lines.append("")
        lines.append("_Which tool ran each step that has a choice, as the project "
                     "recorded it. Where it was not recorded, the line says so rather "
                     "than guessing from the tools set up today._")
        lines.append("")
        lines += engine_lines
        lines.append("")

    lines.append("---")
    # "Nocturne 0.33.0 · report generated 17 September 2026" READ as "made with
    # 0.33.0", which for a project processed months earlier and opened today is
    # simply false — in the one document whose purpose is to be an authoritative
    # record. The version is now attributed to the REPORT, and the version that
    # last touched the project is named separately when it is known and differs.
    footer = f"Report generated by Nocturne {app_version} on {_human_date(date)}"
    if saved_version and saved_version != app_version:
        footer += f" · project last saved by Nocturne {saved_version}"
    lines.append(footer)
    return "\n".join(lines).rstrip() + "\n"
