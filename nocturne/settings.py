from __future__ import annotations

import json
import os
import shutil
from dataclasses import asdict, dataclass


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


@dataclass
class Settings:
    graxpert_path: str = ""
    rcastro_path: str = ""


def load_settings(path: str) -> Settings:
    if not os.path.exists(path):
        return Settings()
    with open(path) as f:
        data = json.load(f)
    return Settings(
        graxpert_path=data.get("graxpert_path", ""),
        rcastro_path=data.get("rcastro_path", ""),
    )


def save_settings(s: Settings, path: str) -> None:
    with open(path, "w") as f:
        json.dump(asdict(s), f, indent=2)


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


def graxpert_valid(s: Settings) -> bool:
    return bool(s.graxpert_path) and os.path.isfile(resolve_binary(s.graxpert_path))


def rcastro_valid(s: Settings) -> bool:
    return bool(s.rcastro_path) and os.path.isfile(resolve_binary(s.rcastro_path))
