from __future__ import annotations

import os

import numpy as np

from ..core.image import AstroImage
from .step import Step


class Project:
    def __init__(self, base: AstroImage, cache_dir: str, *, written: str | None = None) -> None:
        """`written`: an .npy in `cache_dir` already holding `base.data`, moved
        into place instead of saved again. Opening an image writes it off the
        UI thread — the save was 2.1 s of the M 8 drizzle's 3.9 s freeze."""
        os.makedirs(cache_dir, exist_ok=True)
        self._dir = cache_dir
        self._paths: list[str] = []
        self._records: list[tuple[str, str]] = []
        self._meta: list[dict] = []
        self._linear: list[bool] = []
        self._shapes: list[tuple] = []   # kept so a readout never reloads the pixels
        self._writes: list[int] = []     # per state: which write put its pixels there
        self._write_seq = 0
        self._position = 0
        self._save(0, base, written=written)

    def relocate(self, cache_dir: str) -> None:
        """Move every state file into `cache_dir`, keeping its index. A project
        is loaded into a staging folder off the UI thread, because the live
        cache holds the CURRENT picture's states until the swap; this adopts it
        afterwards. One os.replace per file: each file is either here or there."""
        os.makedirs(cache_dir, exist_ok=True)
        for i, src in enumerate(self._paths):
            dest = os.path.join(cache_dir, f"state_{i}.npy")
            if os.path.abspath(src) != os.path.abspath(dest):
                os.replace(src, dest)
            self._paths[i] = dest
        self._dir = cache_dir

    def files_present(self) -> bool:
        return all(os.path.isfile(p) for p in self._paths)

    @property
    def position(self) -> int:
        return self._position

    def _path(self, index: int) -> str:
        return os.path.join(self._dir, f"state_{index}.npy")

    def _save(self, index: int, img: AstroImage, *, written: str | None = None) -> None:
        path = self._path(index)
        if written is None:
            np.save(path, img.data)
        else:
            os.replace(written, path)
        self._write_seq += 1
        if index < len(self._paths):
            self._paths[index] = path
            self._meta[index] = dict(img.metadata)
            self._linear[index] = img.is_linear
            self._shapes[index] = tuple(img.data.shape)
            self._writes[index] = self._write_seq
        else:
            self._paths.append(path)
            self._meta.append(dict(img.metadata))
            self._linear.append(img.is_linear)
            self._shapes.append(tuple(img.data.shape))
            self._writes.append(self._write_seq)

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

    def is_linear_at(self, index: int) -> bool:
        """Without reading the pixels: state_at loads the whole array, a third
        of a second of UI thread on a 33 MP drizzle for one boolean."""
        return self._linear[index]

    def meta_at(self, index: int) -> dict:
        """A copy of state `index`'s metadata, from memory — as is_linear_at.
        The panel and info strip read it on every repaint; through current()
        a Reset of the M 8 drizzle reloaded 400 MB ten times (2026-10-08)."""
        return dict(self._meta[index])

    def shape_at(self, index: int) -> tuple:
        return self._shapes[index]

    def state_token(self, index: int) -> tuple:
        """Which pixels state `index` holds, without reading them: a re-apply
        rewrites the same index, so the index alone cannot tell (a live preview
        keys its result on this). A write count, not the file's mtime, whose
        granularity is the file system's."""
        return (id(self), index, self._writes[index])

    def run_step(self, step: Step, option: str) -> AstroImage:
        # Truncate any forward (redo) history.
        del self._paths[self._position + 1:]
        del self._records[self._position:]
        del self._meta[self._position + 1:]
        del self._linear[self._position + 1:]
        del self._shapes[self._position + 1:]
        del self._writes[self._position + 1:]
        result = step.apply(self.current(), option)
        index = self._position + 1
        self._save(index, result)
        self._records.append((step.name, option))
        self._position = index
        return result

    def record_precomputed(self, name: str, option: str, img: AstroImage) -> None:
        """Append an already-computed image as a new editable history state,
        without re-running the step that produced it (mirrors the tail of
        run_step, minus the step.apply call). Used to fold a pre-run chain
        (e.g. auto_enhance.run_auto_plan's output) into the live project so
        each stage is undoable/editable without re-invoking slow external
        tools."""
        del self._paths[self._position + 1:]
        del self._records[self._position:]
        del self._meta[self._position + 1:]
        del self._linear[self._position + 1:]
        del self._shapes[self._position + 1:]
        del self._writes[self._position + 1:]
        index = self._position + 1
        self._save(index, img)
        self._records.append((name, option))
        self._position = index

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
        del self._shapes[index + 1:]
        del self._writes[index + 1:]

    def entries(self) -> list[tuple[str, str]]:
        return list(self._records[: self._position])
