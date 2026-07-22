from __future__ import annotations

import os

import numpy as np

from ..core.image import AstroImage
from .step import Step


class Project:
    def __init__(self, base: AstroImage, cache_dir: str) -> None:
        os.makedirs(cache_dir, exist_ok=True)
        self._dir = cache_dir
        self._paths: list[str] = []
        self._records: list[tuple[str, str]] = []
        self._meta: list[dict] = []
        self._linear: list[bool] = []
        self._position = 0
        self._save(0, base)

    def _path(self, index: int) -> str:
        return os.path.join(self._dir, f"state_{index}.npy")

    def _save(self, index: int, img: AstroImage) -> None:
        path = self._path(index)
        np.save(path, img.data)
        if index < len(self._paths):
            self._paths[index] = path
            self._meta[index] = dict(img.metadata)
            self._linear[index] = img.is_linear
        else:
            self._paths.append(path)
            self._meta.append(dict(img.metadata))
            self._linear.append(img.is_linear)

    def _load(self, index: int) -> AstroImage:
        data = np.load(self._paths[index])
        return AstroImage(data, self._linear[index], dict(self._meta[index]))

    def current(self) -> AstroImage:
        return self._load(self._position)

    def set_current_metadata(self, key: str, value) -> None:
        """Persist a metadata key onto the current cached state (survives reload,
        since current() rebuilds AstroImage.metadata from self._meta[index])."""
        self._meta[self._position][key] = value

    def state_at(self, index: int) -> AstroImage:
        """Non-destructive read of the cached state at `index` (no truncation)."""
        return self._load(index)

    def run_step(self, step: Step, option: str) -> AstroImage:
        # Truncate any forward (redo) history.
        del self._paths[self._position + 1:]
        del self._records[self._position:]
        del self._meta[self._position + 1:]
        del self._linear[self._position + 1:]
        result = step.apply(self.current(), option)
        index = self._position + 1
        self._save(index, result)
        self._records.append((step.name, option))
        self._position = index
        return result

    def can_undo(self) -> bool:
        return self._position > 0

    def can_redo(self) -> bool:
        return self._position < len(self._paths) - 1

    def undo(self) -> None:
        if self.can_undo():
            self._position -= 1

    def redo(self) -> None:
        if self.can_redo():
            self._position += 1

    def before_after(self) -> tuple[AstroImage, AstroImage]:
        prev = max(0, self._position - 1)
        return self._load(prev), self._load(self._position)

    def jump_back(self, index: int) -> None:
        if not 0 <= index <= self._position:
            raise IndexError(index)
        self._position = index
        del self._paths[index + 1:]
        del self._records[index:]
        del self._meta[index + 1:]
        del self._linear[index + 1:]

    def entries(self) -> list[tuple[str, str]]:
        return list(self._records[: self._position])
