"""User presets: a named look saved from one picture, applied to another.

A preset is a folder holding `preset.json` and `preview.jpg`. The folder is
named by a uuid, never by the preset's name, so any name a person types is
safe on every filesystem and a rename touches one field.

It reuses the recipe step format (`recipe.py`, scope "preset") rather than
inventing a second one, so a step means the same thing in both. Unlike
`load_recipe` it does NOT refuse a file from another app version: during beta
that would wipe a user's library on every update. A step that no longer makes
sense is reported per step by `preset_plan` instead.
"""
from __future__ import annotations

import contextlib
import json
import logging
import os
import shutil
import time
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import NamedTuple

from . import __version__
from .core.export import decimate_for_preview, jpeg_bytes
from .recipe import (Recipe, deserialize_option, preflight, recipe_from_entries,
                     step_display_name, uncaptured_step_names)

FORMAT = 1
PREVIEW_EDGE = 600            # spec: "e.g. 600 px long edge"
MANIFEST, PREVIEW = "preset.json", "preview.jpg"
SORT_KEYS = ("created", "last_used", "name", "target")
DATA_TYPES = ("broadband", "dualband", "unknown")    # core.filter_type.detect_data_type
MAX_NAME = 80

# Into the `nocturne` tree, which core.applog sends to the log file: a packaged
# app has no console, and a skipped preset should leave a trace somewhere.
_log = logging.getLogger("nocturne.user_presets")

# Each picture's own geometry. The format forbids it, so a file that holds one
# (hand-edited, or a bug) has it dropped rather than run.
_GEOMETRY_STAGES = frozenset({"crop", "rotate", "flip_h", "flip_v"})

_DUALBAND_NOTE = "Made on dual-band (LP filter) data — this picture is not dual-band"
STRETCHED_NOTE = ("Made on an already-stretched picture, so it can only be used on "
                  "pictures that open already stretched.")
# A preset's stages that need stretched data: the stepper's post-stretch steps
# plus the finishing steps that live on Enhancements.
_FINISHING_STAGES = frozenset({"enhance", "starless_levels", "star_spikes"})
_BROADBAND_NOTE = "Made on broadband data"


class PresetError(ValueError):
    """A preset that cannot be loaded, saved or renamed; the message says why."""


@dataclass(frozen=True)
class Preset:
    id: str
    name: str
    steps: tuple                     # recipe step dicts {"stage", "option"}
    target: str = ""
    data_type: str = "unknown"       # detect_data_type(): dualband | broadband | unknown
    created: str = ""                # ISO 8601 UTC, to the second
    last_used: str = ""              # "" = never used
    app: str = ""                    # Nocturne version that saved it
    left_out: tuple = ()             # names Save as preset reported as not captured
    folder: str = ""                 # where it lives; not written to the manifest

    @property
    def step_count(self) -> int:
        # Derived, never stored, so it cannot drift from the steps.
        return len(self.steps)

    @property
    def preview_path(self) -> str:
        return os.path.join(self.folder, PREVIEW)

    @property
    def has_preview(self) -> bool:
        try:
            return os.path.getsize(self.preview_path) > 0
        except OSError:
            return False

    def step_names(self) -> list[str]:
        return [step_display_name(s.get("stage"), s.get("option")) for s in self.steps]


class PresetPlan(NamedTuple):
    plan: list                       # [(stage_id, native_option)] for run_auto_plan
    left_out: list                   # [(display name, reason)]: retired or cannot run here
    substitutes: list                # [(display name, engine, why)]


def presets_dir(settings_path: str) -> str:
    return os.path.join(os.path.dirname(settings_path), "presets")


def steps_for_preset(entries) -> tuple[list[dict], list[str]]:
    return (recipe_from_entries(entries, scope="preset").steps,
            uncaptured_step_names(entries, scope="preset"))


def preview_jpeg(img, *, linked: bool = True) -> bytes:
    """The project thumbnail's pixels at a larger edge (WYSIWYG). Untagged
    8-bit JPEG, read as sRGB, as the project thumbnail is."""
    return jpeg_bytes(decimate_for_preview(img, PREVIEW_EDGE), PREVIEW_EDGE,
                      linked=linked, quality=85)


def _now_iso(now: float | None) -> str:
    t = time.time() if now is None else now
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_json_atomic(path: str, data: dict) -> None:
    # Not mkstemp: that makes the file owner-only (0600). Opening with 0o666
    # lets the process umask give it a plain file's mode without reading the
    # umask, which can only be done by changing it.
    tmp = os.path.join(os.path.dirname(path), f".tmp-{uuid.uuid4().hex}.json")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.remove(tmp)
        raise


def load_preset(folder: str) -> Preset:
    """Lenient on missing optional fields, strict on what it cannot honour."""
    path = os.path.join(folder, MANIFEST)
    try:
        with open(path, encoding="utf-8") as f:
            m = json.load(f)
    except (OSError, ValueError) as exc:
        raise PresetError(f"cannot read {MANIFEST}: {exc}") from exc
    if not isinstance(m, dict):
        raise PresetError(f"{MANIFEST} is not an object")
    fmt = m.get("format", 1)
    if not isinstance(fmt, int) or fmt > FORMAT:
        raise PresetError("saved by a newer version of Nocturne")
    name = m.get("name")
    if name is not None and not isinstance(name, str):
        raise PresetError("name is not text")
    if not name or not name.strip():
        raise PresetError("the preset has no name")
    steps = m.get("steps")
    if not isinstance(steps, list):
        raise PresetError("the preset's steps are not a list")
    for s in steps:
        if not isinstance(s, dict) or not isinstance(s.get("stage"), str):
            raise PresetError("a step has no stage")
    text = {}
    for key, default in (("target", ""), ("data_type", "unknown"), ("created", ""),
                         ("last_used", ""), ("app", "")):
        value = m.get(key)
        if value is None:
            value = default
        if not isinstance(value, str):
            raise PresetError(f"{key} is not text")
        text[key] = value
    left_out = m.get("left_out")
    if left_out is None:
        left_out = []
    if not isinstance(left_out, list) or not all(isinstance(x, str) for x in left_out):
        raise PresetError("left_out is not a list of names")
    return Preset(id=os.path.basename(os.path.normpath(folder)), name=name,
                  steps=tuple(steps), left_out=tuple(left_out), folder=folder, **text)


def _clean_name(name) -> str:
    name = name.strip() if isinstance(name, str) else ""
    if not name:
        raise PresetError("a preset needs a name")
    if len(name) > MAX_NAME:
        raise PresetError(f"a preset name is at most {MAX_NAME} characters")
    return name


def same_name(a: str, b: str) -> bool:
    return a.strip().casefold() == b.strip().casefold()


def _parse_iso(s: str) -> datetime | None:
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def saved_label(p: Preset, now: float | None = None) -> str:
    """ "M 8 · saved 13 Oct" — the date formatted as welcome.when_text does."""
    who = p.target or p.name
    saved = _parse_iso(p.created)
    if saved is None:
        return who
    today = date.fromtimestamp(time.time() if now is None else now)
    d = saved.astimezone().date()
    short = f"{d.day} {d.strftime('%b')}"
    return f"{who} · saved {short if d.year == today.year else f'{short} {d.year}'}"


def sort_presets(presets, key: str) -> list[Preset]:
    by_created = sorted(presets, key=lambda p: p.created, reverse=True)
    if key == "last_used":
        # Stable sort over newest-created first: used ones by recency, then never-used.
        used = sorted((p for p in by_created if p.last_used),
                      key=lambda p: p.last_used, reverse=True)
        return used + [p for p in by_created if not p.last_used]
    if key == "name":
        return sorted(presets, key=lambda p: p.name.casefold())
    if key == "target":
        return sorted(presets, key=lambda p: (not p.target, p.target.casefold(),
                                              p.name.casefold()))
    return by_created


def filter_presets(presets, text: str = "", data_type: str | None = None) -> list[Preset]:
    needle = text.strip().casefold()
    out = []
    for p in presets:
        if needle and needle not in p.name.casefold() and needle not in p.target.casefold():
            continue
        if data_type and "unknown" not in (p.data_type, data_type) and p.data_type != data_type:
            continue
        out.append(p)
    return out


def starts_after_stretch(p: Preset) -> bool:
    """Saved from a picture that opened already stretched (a finished TIFF, an
    Upscale): steps that need stretched data, and no Stretch of its own."""
    from .ui.pipeline import POST_STRETCH_IDS
    stages = {s.get("stage") for s in p.steps} - _GEOMETRY_STAGES
    return "stretch" not in stages and bool(stages & (POST_STRETCH_IDS | _FINISHING_STAGES))


def can_apply(p: Preset, picture_type: str, base_linear: bool = False) -> tuple[bool, str]:
    """One rule for the browser's greying and Apply's backstop. `base_linear`
    is the picture the preset would run on: the CROPPED base, since Apply
    discards everything after the leading geometry first."""
    # The same rule as Gold and blue: unknown is not dual-band.
    if p.data_type == "dualband" and picture_type != "dualband":
        return False, _DUALBAND_NOTE
    if base_linear and starts_after_stretch(p):
        return False, STRETCHED_NOTE
    if p.data_type == "broadband" and picture_type == "dualband":
        return True, _BROADBAND_NOTE
    return True, ""


def preset_plan(p: Preset, settings) -> PresetPlan:
    steps = [s for s in p.steps if s.get("stage") not in _GEOMETRY_STAGES]
    plan, left_out, substitutes = [], [], []
    for step, sp in zip(steps, preflight(Recipe(list(steps)), settings, scope="preset")):
        if sp.outcome in ("skip", "fail"):
            left_out.append((sp.step, sp.reason))
            continue
        if sp.outcome == "substitute":
            substitutes.append((sp.step, sp.engine, sp.reason))
        stage = step["stage"]
        plan.append((stage, deserialize_option(stage, step.get("option"))))
    return PresetPlan(plan, left_out, substitutes)


class PresetLibrary:
    def __init__(self, root: str) -> None:
        self.root = root

    def _all(self) -> list[Preset]:
        """Every readable preset, duplicates included; never raises."""
        try:
            names = sorted(os.listdir(self.root))
        except OSError:
            return []
        out = []
        for entry in names:
            folder = os.path.join(self.root, entry)
            if entry.startswith(".") or not os.path.isdir(folder):
                continue
            try:
                out.append(load_preset(folder))
            except Exception as exc:    # one bad preset must never take down the list
                _log.warning("preset %s skipped: %s", entry, exc)
        return out

    def list(self) -> list[Preset]:
        # Two folders with one name: an overwrite killed between its rename and
        # the removal. The later one is the one the user saved last.
        # Equal `created` (same second): newer folder mtime, then folder name,
        # so the answer never depends on listing order.
        kept: dict[str, tuple] = {}
        for p in self._all():
            k = p.name.strip().casefold()
            try:
                mtime = os.stat(p.folder).st_mtime
            except OSError:
                mtime = 0.0
            rank = (p.created, mtime, p.id)
            if k not in kept or rank > kept[k][0]:
                kept[k] = (rank, p)
        return [p for _, p in kept.values()]

    def find(self, name: str) -> Preset | None:
        return next((p for p in self.list() if same_name(p.name, name)), None)

    def _sweep(self) -> None:
        """Leftovers of a killed save or delete. Single-instance app, so no
        other writer can own one."""
        with contextlib.suppress(OSError):
            for entry in os.listdir(self.root):
                if entry.startswith((".part-", ".trash-")):
                    shutil.rmtree(os.path.join(self.root, entry), ignore_errors=True)

    def _remove(self, folder: str) -> None:
        root = os.path.realpath(self.root)
        if os.path.dirname(os.path.realpath(folder)) != root:
            raise ValueError(f"not a preset in this library: {folder}")
        trash = os.path.join(self.root, f".trash-{uuid.uuid4().hex}")
        os.replace(folder, trash)            # gone from list() in one step
        shutil.rmtree(trash, ignore_errors=True)

    def save(self, name, steps, preview, *, target="", data_type="unknown",
             left_out=(), now=None) -> Preset:
        name = _clean_name(name)
        if data_type not in DATA_TYPES:
            raise ValueError(f"data_type must be one of {DATA_TYPES}, not {data_type!r}")
        os.makedirs(self.root, exist_ok=True)
        self._sweep()
        pid = uuid.uuid4().hex
        part = os.path.join(self.root, f".part-{pid}")
        os.mkdir(part)
        with open(os.path.join(part, PREVIEW), "wb") as f:
            f.write(preview)
        manifest = {"format": FORMAT, "name": name, "target": target, "data_type": data_type,
                    "created": _now_iso(now), "last_used": "", "app": __version__,
                    "left_out": list(left_out), "steps": list(steps)}
        with open(os.path.join(part, MANIFEST), "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())                     # on disk before it can be found
        final = os.path.join(self.root, pid)
        os.replace(part, final)                      # the one atomic step
        # Only now retire the replaced one. The new preset is already saved, so a
        # failure here is not the save's: list() resolves the duplicate by rank.
        for other in self._all():
            if other.id != pid and same_name(other.name, name):
                try:
                    self._remove(other.folder)
                except OSError as exc:
                    _log.warning("could not retire replaced preset %s: %s", other.id, exc)
        return load_preset(final)

    def rename(self, p: Preset, new_name: str) -> Preset:
        new_name = _clean_name(new_name)
        if any(o.id != p.id and same_name(o.name, new_name) for o in self._all()):
            raise PresetError(f"a preset called “{new_name}” already exists")
        return self._rewrite(p, name=new_name)

    def delete(self, p: Preset) -> None:
        self._remove(p.folder)

    def touch(self, p: Preset, now: float | None = None) -> Preset:
        return self._rewrite(p, last_used=_now_iso(now))

    def _rewrite(self, p: Preset, **fields) -> Preset:
        """Change named fields and keep every other key as found, including
        any a later version of the same format added."""
        load_preset(p.folder)                        # refuse what we cannot honour
        path = os.path.join(p.folder, MANIFEST)
        with open(path, encoding="utf-8") as f:
            m = json.load(f)
        m.update(fields)
        _write_json_atomic(path, m)
        return load_preset(p.folder)
