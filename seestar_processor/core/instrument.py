from dataclasses import dataclass


@dataclass(frozen=True)
class Instrument:
    name: str
    width: int
    height: int
    pixel_size_um: float
    focal_length_mm: float
    bayer_pattern: str

    @property
    def pixel_scale_arcsec(self) -> float:
        return 206.265 * self.pixel_size_um / self.focal_length_mm


SEESTAR_S30_PRO = Instrument(
    name="ZWO Seestar S30 Pro",
    width=3840,
    height=2160,
    pixel_size_um=2.9,
    focal_length_mm=150.0,
    bayer_pattern="RGGB",
)
