from __future__ import annotations

from abc import ABC, abstractmethod

from ..core.image import AstroImage


class Step(ABC):
    name: str = ""

    # Which engine this step's LAST apply actually used — "StarX", "StarNet2"
    # or "free" — or None for a step that has no choice to make. Set by the
    # step during apply(), never derived afterwards: settings can change while
    # a step is in flight (a GraXpert denoise takes minutes), so asking
    # rcastro_valid at log time can report a choice that was never made.
    #
    # Added 2026-09-22. Elapsed time was the only signal about which path ran,
    # and Andreas read a fast Deconvolution as proof the star separation had
    # fallen back — the two are unrelated, and nothing in the app said so.
    last_engine: str | None = None

    @abstractmethod
    def options(self) -> list[str]:
        ...

    @abstractmethod
    def default_option(self) -> str:
        ...

    @abstractmethod
    def apply(self, img: AstroImage, option: str) -> AstroImage:
        ...
