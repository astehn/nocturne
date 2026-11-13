from __future__ import annotations

import re

from ..core.color import FALLBACK_COLOUR_METHOD, ColorSettings, apply_color
from ..core.image import AstroImage
from ..history.step import Step

# Approved word for word (2026-10-10; "stars" for "sky" 2026-11-13). Through
# two narrow passbands a star's colour no longer tracks its Gaia BP-RP, so
# there is nothing to calibrate to.
DUALBAND_MESSAGE = ("Photometric colour isn't meaningful through a dual-band "
                    "filter; balanced on the stars instead.")


_STAR_WHY = {"too_few_stars": "too few stars to balance on",
             "implausible": "the star colours gave an implausible correction"}


_USED_STAR = re.compile(r"[\s\u2014]*[Uu]sed star balance( instead)?\.?")


class ColorStep(Step):
    name = "Color"

    def __init__(self, astap=None, gaia_query=None) -> None:
        self._astap = astap            # ASTAP instance or None
        self._gaia_query = gaia_query  # tools.gaia.query_field or None
        self.last_message = ""         # fallback reason surfaced by the UI (empty = ok)
        self.fell_back = False         # photometric asked for, sky balance used
        self.stepped_aside = False     # ...deliberately, on dual-band data
        self.ran = ""                  # what ran: photometric / star / sky
        self.star_version = 0          # star balance version used, 0 = none
        self.last_gains = None         # star balance gains, for the log
        self.last_n_stars = 0
        self.star_fallback = ""        # why star balance did not run, if it did not

    def options(self) -> list[str]:
        return []

    def default_option(self) -> str:
        return ""

    def apply(self, img: AstroImage, option=None) -> AstroImage:
        settings = option or ColorSettings()
        self.last_message = ""
        self.ran, self.star_version = "", 0
        self.last_gains, self.last_n_stars = None, 0
        self.star_fallback = ""
        asked = getattr(settings, "method", "sky") == "photometric"
        self.fell_back = asked          # until the calibration actually lands
        self.stepped_aside = steps_aside(img, settings)
        if self.stepped_aside:
            # Steps aside before solving: no ASTAP, no network. The recorded
            # method stays the choice, so a recipe still calibrates broadband.
            self.last_message = DUALBAND_MESSAGE
        elif asked and img.is_color:
            result = self._photometric(img)
            if result is not None:
                self.fell_back = False
                self.ran = "photometric"
                return apply_color(result, ColorSettings(neutralize_background=False,
                                                         remove_green=settings.remove_green))
            # fall through to the fallback balance (self.last_message already set)
        method = getattr(settings, "method", "sky")
        if method == "sky":
            self.ran = "sky"
            return apply_color(img, settings)
        # "star" chosen, or photometric asked and not used.
        if method == "photometric":
            method = FALLBACK_COLOUR_METHOD
        return self._star_or_sky(img, settings, method)

    def _star_or_sky(self, img: AstroImage, settings, method: str) -> AstroImage:
        from ..core.star_balance import (STAR_BALANCE_VERSION, TOO_FEW_STARS,
                                         apply_star_balance)
        green = ColorSettings(neutralize_background=False,
                              remove_green=settings.remove_green)
        if method == "star" and img.is_color:
            version = getattr(settings, "version", 0) or STAR_BALANCE_VERSION
            balanced, res, reason = apply_star_balance(img, version=version)
            if res is not None:
                self.ran, self.star_version = "star", version
                self.last_gains, self.last_n_stars = res.gains, res.n_stars
                return apply_color(balanced, green)
            self.star_fallback = reason
            self.ran = "sky"
            # `balanced` is the border-safe sky neutralisation; apply_color's own
            # would turn an untrimmed master black.
            why = _STAR_WHY.get(reason, _STAR_WHY[TOO_FEW_STARS])
            if self.last_message:
                # The photometric reason ends "— used star balance", which is no
                # longer true: drop that clause rather than contradict it.
                earlier = _USED_STAR.sub("", self.last_message).strip()
                self.last_message = (f"{earlier} \u2014 star balance couldn't run "
                                     f"either ({why}) \u2014 used sky balance.")
            else:
                self.last_message = f"{why[0].upper()}{why[1:]} \u2014 used sky balance."
            return apply_color(balanced, green)
        self.ran = "sky"
        return apply_color(img, ColorSettings(remove_green=settings.remove_green))

    def recorded_option(self, option):
        if isinstance(option, ColorSettings):
            import dataclasses
            return dataclasses.replace(option, fell_back=self.fell_back,
                                       stepped_aside=self.stepped_aside,
                                       ran=self.ran, version=self.star_version,
                                       star_fallback=self.star_fallback)
        return option

    def _photometric(self, img: AstroImage):
        """Solve -> query Gaia -> gains -> apply. Returns the calibrated image, or
        None (and sets self.last_message) on any failure so apply() falls back."""
        from ..tools.gaia import (GaiaBadResponse, GaiaError, GaiaNoStars,
                                  GaiaTlsError, GaiaUnreachable)
        from ..core.spcc import photometric_gains, apply_gains
        if self._astap is None or self._gaia_query is None:
            self.last_message = "ASTAP not set — used star balance."
            return None
        meta = img.metadata
        h, w = img.data.shape[:2]
        # The SAME solve the Plate Solve tool performs, retry and all. This was
        # an inline header-only hint, so a master with no optics left fov as None,
        # ASTAP solved blind and failed, and colour silently degraded to sky
        # balance -- on files the tool itself solves in seconds.
        from ..tools.astap import solve_with_scale_fallback
        try:
            res, _src = solve_with_scale_fallback(self._astap, img, meta, h)
        except Exception:
            res = None
        if res is None or not res.solved:
            self.last_message = "Couldn't plate-solve — used star balance."
            if res is not None and res.message:
                self.last_message += f" (ASTAP: {res.message})"
            return None
        # Cone covering the frame's half-diagonal, capped at 1.2deg: a bigger cone in
        # a dense field just makes the VizieR query slow AND (even nearest-first) reaches
        # past the frame — 1.2deg of nearest stars densely covers the centre, which is
        # all SPCC needs. (gaia sorts nearest-first so the cap keeps these.)
        # From the SOLVE, not the hint: the hint was a guess (and may have been
        # dropped entirely on the blind retry), while res.pixscale_arcsec is
        # measured from the solution itself.
        fov = res.pixscale_arcsec * h / 3600.0 if res.pixscale_arcsec else 2.0
        radius = min(fov * 0.5 * (1.0 + (w / h) ** 2) ** 0.5, 1.2)
        # Three different problems with three different answers. They were all
        # reported as "Couldn't reach Gaia", and the exception was not even bound,
        # so the reason never reached the log — which sent people looking at
        # their network for faults that were not there.
        try:
            gaia = self._gaia_query(res.center_ra_deg, res.center_dec_deg, radius)
        except GaiaTlsError as exc:
            # Before GaiaUnreachable — it is a subclass, and the whole point is
            # to stop this being reported as a network fault. Until v0.21.0 the
            # built app carried no CA certificates, so this failed on every Mac
            # that was not the build machine and said "Couldn't reach Gaia",
            # which sent the problem to the backlog as a slow catalogue and left
            # it there for weeks.
            self.last_message = (
                f"Couldn't verify a secure connection to the star catalogue — "
                f"this is a certificate problem on this computer, not a problem "
                f"with your network or with Gaia. Used star balance. ({exc})")
            return None
        except GaiaUnreachable as exc:
            self.last_message = (f"Couldn't reach Gaia ({exc}) — used star balance.")
            return None
        except GaiaNoStars as exc:
            self.last_message = (f"Gaia has no usable stars for this field "
                                 f"({exc}) — used star balance.")
            return None
        except GaiaBadResponse as exc:
            self.last_message = (f"Gaia answered with something unreadable, most "
                                 f"likely busy — used star balance. {exc}")
            return None
        except GaiaError as exc:
            # Catch-all for the base class and any future subclass. Without it a
            # new failure mode would escape and take the whole step with it,
            # instead of falling back to sky balance like every other one.
            self.last_message = f"Gaia lookup failed ({exc}) — used star balance."
            return None
        try:
            spcc = photometric_gains(img, res.wcs, gaia)
        except Exception:
            self.last_message = "Colour calibration failed — used star balance."
            return None
        if spcc is None:
            self.last_message = ("Couldn't find enough catalogue stars to "
                                 "colour-calibrate — used star balance instead.")
            return None
        gr, gg, gb = spcc.gains
        self.last_message = (f"Photometric colour — {spcc.n_matched} stars matched · "
                             f"gains R {gr:.2f} · G {gg:.2f} · B {gb:.2f}")
        # Two sources now, so say which one answered: otherwise nobody can tell
        # whether our own copy is being used. getattr, because a fake or an
        # older caller may hand back a plain list.
        source = getattr(gaia, "source", None)
        if source:
            self.last_message += f" · from {source}"
            failure = getattr(gaia, "mirror_failure", None)
            if failure:
                from ..tools.gaia import MIRROR_LABEL
                self.last_message += f" ({MIRROR_LABEL} didn't answer: {failure})"
        return apply_gains(img, spcc.gains)


def steps_aside(img: AstroImage, settings) -> bool:
    """Will photometric colour step aside on this image? One answer for the
    step, its busy label and Auto Enhance's report."""
    from ..core.filter_type import detect_data_type
    return (getattr(settings, "method", "sky") == "photometric" and img.is_color
            and detect_data_type(img.metadata or {}) == "dualband")
