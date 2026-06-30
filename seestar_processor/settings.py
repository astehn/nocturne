from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass


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


def graxpert_valid(s: Settings) -> bool:
    return bool(s.graxpert_path) and os.path.isfile(s.graxpert_path)
