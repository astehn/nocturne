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
            if res is not None and res.message:
                self.last_message += f" (ASTAP: {res.message})"
            return None
        # Cone covering the frame's half-diagonal, capped at 1.2deg: a bigger cone in
        # a dense field just makes the VizieR query slow AND (even nearest-first) reaches
        # past the frame — 1.2deg of nearest stars densely covers the centre, which is
        # all SPCC needs. (gaia sorts nearest-first so the cap keeps these.)
        radius = min((fov or 2.0) * 0.5 * (1.0 + (w / h) ** 2) ** 0.5, 1.2)
        try:
            gaia = self._gaia_query(res.center_ra_deg, res.center_dec_deg, radius)
        except GaiaError:
            self.last_message = "Couldn't reach Gaia — used sky balance."
            return None
        try:
            spcc = photometric_gains(img, res.wcs, gaia)
        except Exception:
            self.last_message = "Colour calibration failed — used sky balance."
            return None
        if spcc is None:
            self.last_message = ("Couldn't find enough catalogue stars to "
                                 "colour-calibrate — used sky balance instead.")
            return None
        gr, gg, gb = spcc.gains
        self.last_message = (f"Photometric colour — {spcc.n_matched} stars matched · "
                             f"gains R {gr:.2f} · G {gg:.2f} · B {gb:.2f}")
        return apply_gains(img, spcc.gains)
