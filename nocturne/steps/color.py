from __future__ import annotations

from ..core.color import ColorSettings, apply_color
from ..core.image import AstroImage
from ..history.step import Step


class ColorStep(Step):
    name = "Color"

    def __init__(self, astap=None, gaia_query=None) -> None:
        self._astap = astap            # ASTAP instance or None
        self._gaia_query = gaia_query  # tools.gaia.query_field or None
        self.last_message = ""         # fallback reason surfaced by the UI (empty = ok)

    def options(self) -> list[str]:
        return []

    def default_option(self) -> str:
        return ""

    def apply(self, img: AstroImage, option=None) -> AstroImage:
        settings = option or ColorSettings()
        self.last_message = ""
        if getattr(settings, "method", "sky") == "photometric" and img.is_color:
            result = self._photometric(img)
            if result is not None:
                return apply_color(result, ColorSettings(neutralize_background=False,
                                                         remove_green=settings.remove_green))
            # fall through to sky balance (self.last_message already set)
        return apply_color(img, settings if getattr(settings, "method", "sky") == "sky"
                           else ColorSettings(remove_green=settings.remove_green))

    def _photometric(self, img: AstroImage):
        """Solve -> query Gaia -> gains -> apply. Returns the calibrated image, or
        None (and sets self.last_message) on any failure so apply() falls back."""
        from ..tools.astap import hint_from_metadata
        from ..tools.gaia import GaiaError
        from ..core.spcc import photometric_gains, apply_gains
        if self._astap is None or self._gaia_query is None:
            self.last_message = "ASTAP not set — used sky balance."
            return None
        meta = img.metadata
        h, w = img.data.shape[:2]
        fov = None
        fl, px = meta.get("focal_length"), meta.get("pixel_size")
        if fl and px:
            fov = (206.265 * float(px) / float(fl)) * h / 3600.0
        hint = hint_from_metadata(meta)
        ra_h, dec_d = hint if hint else (None, None)
        try:
            res = self._astap.solve(img, fov_deg=fov, ra_hours=ra_h, dec_deg=dec_d,
                                    header_cards=meta.get("solve_cards"))
        except Exception:
            res = None
        if res is None or not res.solved:
            self.last_message = "Couldn't plate-solve — used sky balance."
            return None
        radius = (fov or 2.0) * 0.75          # generous cone covering the field's half-diagonal
        try:
            gaia = self._gaia_query(res.center_ra_deg, res.center_dec_deg, radius)
        except GaiaError:
            self.last_message = "Couldn't reach Gaia — used sky balance."
            return None
        spcc = photometric_gains(img, res.wcs, gaia)
        if spcc is None:
            self.last_message = "Too few matched stars — used sky balance."
            return None
        return apply_gains(img, spcc.gains)
