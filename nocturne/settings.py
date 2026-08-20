from __future__ import annotations

import json
import os
import shutil
from dataclasses import asdict, dataclass, field


def resolve_settings_path(home: str | None = None) -> str:
    """Path to settings.json under ~/.nocturne, creating the directory. On first
    run, migrate a pre-rename ~/.seestar_processor/settings.json if present so the
    user keeps their configured tool paths."""
    home = home if home is not None else os.path.expanduser("~")
    config_dir = os.path.join(home, ".nocturne")
    os.makedirs(config_dir, exist_ok=True)
    new_settings = os.path.join(config_dir, "settings.json")
    legacy = os.path.join(home, ".seestar_processor", "settings.json")
    if not os.path.exists(new_settings) and os.path.exists(legacy):
        try:
            shutil.copyfile(legacy, new_settings)
        except OSError:
            pass  # best-effort; a failed migration just starts fresh
    return new_settings


# Plate-solve annotation overlay defaults, shared with nocturne.ui.solve_panel
# (which imports these rather than redefining them) so the panel's checkbox
# states and the persisted settings can never drift apart.
DEFAULT_ANNOTATION_LAYERS = {
    "objects": True, "stars": True, "grid": False,
    "compass": True, "scale": True, "by_type": False,
}
DEFAULT_ANNOTATION_DENSITY = "balanced"


@dataclass
class Settings:
    graxpert_path: str = ""
    rcastro_path: str = ""
    base_dir: str = ""
    denoise_engine: str = "rcastro"
    astap_path: str = ""
    help_expanded: bool = True     # detailed step-help section shown by default (novice-first)
    handle: str = ""                # user's @handle, burned onto shared images
    recent_projects: list[str] = field(default_factory=list)  # most-recent-first, capped
    last_project_dir: str = ""      # directory a "new project" file picker should open in
    annotation_layers: dict = field(default_factory=lambda: dict(DEFAULT_ANNOTATION_LAYERS))
    annotation_density: str = DEFAULT_ANNOTATION_DENSITY
    # Share caption styling. Persisted because these are a personal house style,
    # not a per-image decision — re-picking them on every share would be absurd.
    share_caption_size: float = 0.028
    share_caption_colour: str = "#ffffff"
    share_caption_placement: str = "on"
    share_caption_align: str = "left"
    share_band_opacity: float = 0.59


def load_settings(path: str) -> Settings:
    if not os.path.exists(path):
        return Settings()
    with open(path) as f:
        data = json.load(f)
    return Settings(
        graxpert_path=data.get("graxpert_path", ""),
        rcastro_path=data.get("rcastro_path", ""),
        base_dir=data.get("base_dir", ""),
        denoise_engine=data.get("denoise_engine", "rcastro"),
        astap_path=data.get("astap_path", ""),
        help_expanded=data.get("help_expanded", True),
        handle=data.get("handle", ""),
        recent_projects=data.get("recent_projects", []),
        last_project_dir=data.get("last_project_dir", ""),
        annotation_layers=data.get("annotation_layers", dict(DEFAULT_ANNOTATION_LAYERS)),
        annotation_density=data.get("annotation_density", DEFAULT_ANNOTATION_DENSITY),
        share_caption_size=float(data.get("share_caption_size", 0.028)),
        share_caption_colour=data.get("share_caption_colour", "#ffffff"),
        share_caption_placement=data.get("share_caption_placement", "on"),
        share_caption_align=data.get("share_caption_align", "left"),
        share_band_opacity=float(data.get("share_band_opacity", 0.59)),
    )


def save_settings(s: Settings, path: str) -> None:
    with open(path, "w") as f:
        json.dump(asdict(s), f, indent=2)


MAX_RECENT_PROJECTS = 8


def add_recent_project(settings: Settings, path: str) -> None:
    """Record `path` as the most-recently-used project: dedup (moving an existing
    entry to the front rather than duplicating it), prepend, and cap the list at
    MAX_RECENT_PROJECTS. Mutates settings.recent_projects in place."""
    recent = [p for p in settings.recent_projects if p != path]
    recent.insert(0, path)
    settings.recent_projects = recent[:MAX_RECENT_PROJECTS]


def start_dir(base_dir: str) -> str:
    """The directory a file picker should open in: the configured base folder if
    it is a real existing directory, else '' (the OS default)."""
    base_dir = (base_dir or "").strip()
    return base_dir if base_dir and os.path.isdir(base_dir) else ""


def resolve_binary(path: str) -> str:
    """Resolve a macOS `.app` bundle to the executable inside it so it can be
    exec'd (picking the bundle directly causes errno 13). Other paths pass through."""
    if path.endswith(".app") and os.path.isdir(path):
        macos = os.path.join(path, "Contents", "MacOS")
        name = os.path.splitext(os.path.basename(path))[0]
        candidate = os.path.join(macos, name)
        if os.path.isfile(candidate):
            return candidate
        if os.path.isdir(macos):  # fall back to the first executable inside
            for entry in sorted(os.listdir(macos)):
                full = os.path.join(macos, entry)
                if os.path.isfile(full) and os.access(full, os.X_OK):
                    return full
    return path


# Where each tool's own installer puts it on macOS. Auto-detection exists
# because the first user feedback this project ever received (2026-08-20) was
# that configuring these three is messy — and it was: the Browse buttons in
# Settings had been dead since 2026-08-15 (b4314fa), leaving a hand-typed
# absolute path as the only route. All three of Andreas' tools sit at these
# exact paths, so in the common case there is nothing to configure at all.
#
# A .app is listed as the BUNDLE, not the executable inside it. resolve_binary
# has always accepted a bundle, which is precisely the affordance nobody could
# reach, and it keeps this list readable.
TOOL_CANDIDATES: dict[str, list[str]] = {
    "graxpert_path": ["/Applications/GraXpert.app",
                      "~/Applications/GraXpert.app"],
    "rcastro_path": ["/Applications/RC-Astro/CLI/rc-astro",
                     "~/Applications/RC-Astro/CLI/rc-astro"],
    "astap_path": ["/Applications/ASTAP.app",
                   "~/Applications/ASTAP.app",
                   "/opt/homebrew/bin/astap"],
}


def detect_tool_paths(s: Settings, candidates: dict | None = None,
                      replace_invalid: bool = False) -> dict[str, str]:
    """Installed tools whose setting is currently EMPTY, as {field: path}.

    `replace_invalid` is for the Settings dialog's explicit rescan, and widens
    that to paths which no longer resolve to a real executable. Startup must not
    use it — but without it a fumbled path is sticky forever, because the empty
    check means nothing would ever correct it. A rescan fixes what is BROKEN and
    still never touches a working custom path.

    Never returns a field the user has already set. Someone whose tool lives
    somewhere unusual has already paid the cost of finding it, and quietly
    replacing their path with a default would be worse than not detecting at
    all — so the empty check is the whole safety model, and the test for it
    asserts the configured value is unchanged rather than merely not-default.
    """
    found: dict[str, str] = {}
    for field_name, paths in (candidates or TOOL_CANDIDATES).items():
        current = getattr(s, field_name, "")
        if current and not (replace_invalid
                            and not os.path.isfile(resolve_binary(current))):
            continue                      # configured and working; leave it alone
        for raw in paths:
            path = os.path.expanduser(raw)
            if os.path.isfile(resolve_binary(path)):
                found[field_name] = path
                break
    return found


def autoconfigure_tools(path: str, candidates: dict | None = None) -> list[str]:
    """Fill in any unconfigured tool found at its default location; save if so.

    Returns the field names filled, so a caller can report them. Runs at
    startup: doing it there rather than in load_settings keeps load_settings
    pure, and keeps the test suite from picking up whatever happens to be
    installed on the machine running it.
    """
    s = load_settings(path)
    found = detect_tool_paths(s, candidates)
    if not found:
        return []
    for field_name, value in found.items():
        setattr(s, field_name, value)
    save_settings(s, path)
    return sorted(found)


def graxpert_valid(s: Settings) -> bool:
    return bool(s.graxpert_path) and os.path.isfile(resolve_binary(s.graxpert_path))


def rcastro_valid(s: Settings) -> bool:
    return bool(s.rcastro_path) and os.path.isfile(resolve_binary(s.rcastro_path))


def astap_valid(s: Settings) -> bool:
    return bool(s.astap_path) and os.path.isfile(resolve_binary(s.astap_path))
