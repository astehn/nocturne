from __future__ import annotations

from abc import ABC, abstractmethod

from ..core.image import AstroImage


class Step(ABC):
    name: str = ""

    @abstractmethod
    def options(self) -> list[str]:
        ...

    @abstractmethod
    def default_option(self) -> str:
        ...

    @abstractmethod
    def apply(self, img: AstroImage, option: str) -> AstroImage:
        ...
