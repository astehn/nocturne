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
    focal_length_mm=150.0,
    aperture_mm=30.0,   # 150 / 30 = f/5
    bayer_pattern="GRBG",  # confirmed from real S30 Pro sub headers (BAYERPAT='GRBG')
)
