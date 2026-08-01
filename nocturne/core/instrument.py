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
)


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
    scale = SEESTAR_S30_PRO.pixel_scale_arcsec
    if scale > 0 and height_px > 0:
        return scale * height_px / 3600.0, "profile"
    return None, "none"
