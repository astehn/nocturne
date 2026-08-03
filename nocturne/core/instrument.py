from dataclasses import dataclass


@dataclass(frozen=True)
class Instrument:
    name: str
    sensor: str
    width: int
    height: int
    pixel_size_um: float
    focal_length_mm: float
    aperture_mm: float
    bayer_pattern: str
    # Lowercase substrings that identify this camera in a CREATOR/INSTRUME card.
    # Seestars are inconsistent about which they fill and with what — a single S50
    # sub carries CREATOR='ZWO Seestar S50' and INSTRUME='Seestar S50', while S30
    # Pro subs carry CREATOR='ZWO Seestar S30 Pro' with INSTRUME either 'imx585'
    # or absent entirely. Matching a set of aliases absorbs that.
    aliases: tuple = ()

    @property
    def pixel_scale_arcsec(self) -> float:
        return 206.265 * self.pixel_size_um / self.focal_length_mm

    @property
    def f_ratio(self) -> float:
        return self.focal_length_mm / self.aperture_mm


SEESTAR_S30_PRO = Instrument(
    name="ZWO Seestar S30 Pro",
    sensor="Sony IMX585",
    width=3840,
    height=2160,
    pixel_size_um=2.9,
    focal_length_mm=160.0,
    aperture_mm=32.0,   # 160 / 32 = f/5 (device header: FOCALLEN=160, APERTURE=5.0)
    bayer_pattern="GRBG",  # confirmed from real S30 Pro sub headers (BAYERPAT='GRBG')
    aliases=("seestar s30 pro", "imx585"),
)

# Every field read off real S50 subs (M 42, 2025-12-09), not from spec sheets:
# CREATOR='ZWO Seestar S50', FOCALLEN=250.0, XPIXSZ=2.9, APERTURE=5.0 (an
# f-RATIO, as on the S30 Pro, so 250/5 = 50 mm), BAYERPAT='GRBG'.
SEESTAR_S50 = Instrument(
    name="ZWO Seestar S50",
    sensor="Sony IMX462",
    width=1920,
    height=1080,
    pixel_size_um=2.9,
    focal_length_mm=250.0,
    aperture_mm=50.0,
    bayer_pattern="GRBG",
    aliases=("seestar s50", "imx462"),
)

# Nocturne is built for the S30 Pro, so it stays the assumption when nothing in
# the file says otherwise. Adding a camera is a matter of appending an entry
# here — deliberately, since more Seestars are expected.
INSTRUMENTS = (SEESTAR_S30_PRO, SEESTAR_S50)
DEFAULT_INSTRUMENT = SEESTAR_S30_PRO


def identify(meta: dict) -> "Instrument | None":
    """Which camera took this, from the file's own headers. None when unknown —
    the caller decides whether to assume, and should say that it did.

    Name first: CREATOR was present and exact on every real Seestar file
    inspected, across both models, which no derived quantity can match for
    reliability. Focal length is the fallback because it is what actually
    differs optically (160 mm vs 250 mm) and it survives into a stacked master
    through the solve cards.

    Deliberately NOT by dimensions. Every real metadata-poor master to hand was
    1886x2699, 1340x1708, 2376x2381 — stacked and auto-cropped, matching no
    sensor's native size. Worse, a cropped S30 Pro frame can land on exactly an
    S50's dimensions and would be misidentified with its scale 56% wrong, which
    is a regression for the camera most users actually have.
    """
    name = " ".join(str(meta.get(k, "") or "") for k in ("creator", "instrument")).lower()
    if name.strip():
        # Longest alias first: a future "seestar s30" entry would otherwise
        # substring-match an "ZWO Seestar S30 Pro" creator string.
        for inst, alias in sorted(
            ((i, a) for i in INSTRUMENTS for a in i.aliases),
            key=lambda pair: -len(pair[1]),
        ):
            if alias in name:
                return inst
    focal = meta.get("focal_length")
    try:
        if focal and float(focal) > 0:
            for inst in INSTRUMENTS:
                if abs(float(focal) - inst.focal_length_mm) < 1.0:
                    return inst
    except (TypeError, ValueError):
        pass
    return None


def fov_hint(meta: dict, height_px: int) -> tuple[float | None, str]:
    """A field-of-view hint for the solver, and where it came from.

    ASTAP solves far more reliably given an approximate scale, and blind-solving
    a few-degree field often fails outright. Headers are the best source, but a
    stacked master exported from another tool routinely arrives with none — the
    user's own NGC 7000 master carries seven header cards and no optics at all.
    Nocturne knows what a Seestar is, so fall back to the instrument profile
    rather than solving blind. A crop preserves pixel scale, so the profile
    stays valid for a cropped frame even though its DIMENSIONS change.

    Lives in core, and is the ONE place this is computed, because it previously
    was not. The Plate Solve tool had the profile fallback; the photometric
    colour (SPCC) step carried its own inline copy with only the header branch,
    so on a metadata-poor file SPCC solved blind, failed, and silently degraded
    to sky balance — while the tool solved the identical frame in 4.9 s. Caught
    on a real NGC 281 capture 2026-08-01, where the panel read "scale assumed
    from Seestar profile" and the log read "Couldn't plate-solve — used sky
    balance" for the same image.

    Returns (fov_degrees or None, source) where source is "header", "profile" or
    "none" — callers report which, because a solve that leaned on an assumed
    scale should say so.
    """
    fl, px = meta.get("focal_length"), meta.get("pixel_size")
    try:
        if fl and px and float(fl) > 0 and float(px) > 0:
            return (206.265 * float(px) / float(fl)) * height_px / 3600.0, "header"
    except (TypeError, ValueError):
        pass
    # No optics in the header, so the scale is a guess — but guess with the
    # camera the file names, if it names one. A Seestar S50 assumed to be an
    # S30 Pro is handed 3.74"/px against a real 2.39"/px.
    scale = (identify(meta) or DEFAULT_INSTRUMENT).pixel_scale_arcsec
    if scale > 0 and height_px > 0:
        return scale * height_px / 3600.0, "profile"
    return None, "none"
