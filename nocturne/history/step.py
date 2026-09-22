from __future__ import annotations

from abc import ABC, abstractmethod

from ..core.image import AstroImage


class Step(ABC):
    name: str = ""

    # Which engine this step's LAST apply actually used — "StarX", "StarNet2",
    # "BlurX", "NoiseX", "GraXpert" or "free" — or None for a step with no
    # choice to make. Set by the step during apply(), never derived afterwards:
    # settings can change while a step is in flight (a GraXpert denoise takes
    # minutes), so asking rcastro_valid at log time can report a choice that
    # was never made.
    #
    # Added 2026-09-22. Elapsed time was the only signal about which path ran,
    # and Andreas read a fast Deconvolution as proof the star separation had
    # fallen back — the two are unrelated, and nothing in the app said so.
    #
    # WHO READS IT, as of 2026-09-22: MainWindow._log_step, which handles the
    # steps committed through apply_current — Deconvolution and Noise
    # Reduction. The five splitter steps commit through dedicated paths
    # (_apply_saturation, _apply_star_reduction, _apply_green_fringe,
    # _apply_color_balance, _apply_narrowband) that carry their own tag from
    # _split_tagged, so nothing is missing from the log — but their
    # `last_engine` has no reader today.
    #
    # Kept rather than deleted, deliberately and against a review's advice: it
    # is one line per step, it is correct, and it makes the contract the same
    # for every step that chooses. The thing that was wrong was a commit
    # message claiming every step's value reaches the user. See TODO.md for
    # converging the five dedicated paths onto _log_step, which is what would
    # make them readers.
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
