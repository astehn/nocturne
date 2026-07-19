import numpy as np
import pytest
from astropy.io import fits
from nocturne.core.fits_io import load_fits


def _write(path, arr):
    fits.PrimaryHDU(arr).writeto(path, overwrite=True)


def test_loads_planar_color_as_hwc(tmp_path):
    arr = np.random.randint(0, 4096, size=(3, 16, 16)).astype(np.uint16)
    p = tmp_path / "color.fits"
    _write(str(p), arr)
    img = load_fits(str(p))
    assert img.is_color is True
    assert img.data.shape == (16, 16, 3)
    assert img.data.max() <= 1.0
    assert img.is_linear is True


def test_debayers_mono_to_color(tmp_path):
    arr = np.random.randint(0, 4096, size=(16, 16)).astype(np.uint16)
    p = tmp_path / "mono.fits"
    _write(str(p), arr)
    img = load_fits(str(p))
    assert img.is_color is True
    assert img.data.shape == (16, 16, 3)
    assert img.data.dtype == np.float32
    assert img.data.max() <= 1.0 and img.data.min() >= 0.0
    assert img.is_linear is True


def test_all_zero_image_does_not_divide_by_zero(tmp_path):
    arr = np.zeros((16, 16), dtype=np.uint16)
    p = tmp_path / "zero.fits"
    _write(str(p), arr)
    img = load_fits(str(p))
    assert np.all(np.isfinite(img.data))
    assert img.data.max() == 0.0


def test_metadata_parsed_from_header(tmp_path):
    from nocturne.core.fits_io import import_summary
    arr = np.random.randint(0, 4096, size=(3, 16, 16)).astype(np.uint16)
    hdu = fits.PrimaryHDU(arr)
    hdu.header["EXPTIME"] = 30.0
    hdu.header["OBJECT"] = "M31"
    hdu.header["STACKCNT"] = 120
    p = tmp_path / "m.fits"
    hdu.writeto(str(p), overwrite=True)
    img = load_fits(str(p))
    assert img.metadata["exposure"] == 30.0
    assert img.metadata["target"] == "M31"
    assert img.metadata["frames"] == 120
    assert img.metadata["width"] == 16 and img.metadata["height"] == 16
    summary = import_summary(img.metadata)
    assert "M31" in summary and "30" in summary


def test_unsupported_3d_shape_raises(tmp_path):
    arr = np.zeros((5, 16, 16), dtype=np.uint16)
    p = tmp_path / "bad.fits"
    _write(str(p), arr)
    with pytest.raises(ValueError):
        load_fits(str(p))


def test_format_integration():
    from nocturne.core.fits_io import format_integration
    assert format_integration(2900) == "48m 20s"
    assert format_integration(8100) == "2h 15m"
    assert format_integration(20) == "20s"


def test_parse_metadata_temp_and_date(tmp_path):
    from astropy.io import fits
    import numpy as np
    arr = np.random.randint(0, 4096, size=(3, 8, 8)).astype(np.uint16)
    hdu = fits.PrimaryHDU(arr)
    hdu.header["CCD-TEMP"] = 26.0
    hdu.header["DATE-OBS"] = "2026-06-18T21:34:00"
    p = tmp_path / "t.fits"
    hdu.writeto(str(p), overwrite=True)
    img = load_fits(str(p))
    assert img.metadata["temp"] == 26.0
    assert str(img.metadata["date"]).startswith("2026-06-18")


def test_import_summary_full_and_sparse():
    from nocturne.core.fits_io import import_summary
    full = import_summary({"exposure": 20, "frames": 145, "target": "IC 5070",
                           "width": 2160, "height": 3840})
    for token in ("IC 5070", "48m 20s", "145 × 20s", "2160 × 3840",
                  "Sony IMX585", "3.7″"):
        assert token in full, token
    sparse = import_summary({"width": 10, "height": 10})
    assert "Sony IMX585" in sparse and "10 × 10" in sparse
    assert "Total integration" not in sparse


def test_resolve_integration_nocturne_master():
    from nocturne.core.fits_io import resolve_integration
    r = resolve_integration({"exposure": 1620.0, "frames": 81})  # EXPTIME=total
    assert round(r.total_s) == 1620 and round(r.per_sub_s) == 20 and r.frames == 81


def test_resolve_integration_native_livetime():
    from nocturne.core.fits_io import resolve_integration
    r = resolve_integration({"livetime": 3220.0, "exposure": 20.0, "frames": 161})
    assert round(r.total_s) == 3220 and round(r.per_sub_s) == 20


def test_resolve_integration_legacy_persub():
    from nocturne.core.fits_io import resolve_integration
    r = resolve_integration({"exposure": 20.0, "frames": 145})  # EXPTIME=per-sub
    assert round(r.total_s) == 2900 and round(r.per_sub_s) == 20


def test_resolve_integration_exposure_only_and_none():
    from nocturne.core.fits_io import resolve_integration
    r = resolve_integration({"exposure": 30.0})
    assert r.total_s is None and round(r.per_sub_s) == 30
    assert resolve_integration({"width": 10}) is None


def test_import_summary_nocturne_master_integration():
    from nocturne.core.fits_io import import_summary
    s = import_summary({"exposure": 1620.0, "frames": 81, "width": 1792, "height": 3656})
    assert "27m 00s" in s and "81 × 20s" in s
    assert "184h" not in s and "81 × 1620s" not in s  # the old bug is gone


def test_import_summary_camera_from_header():
    from nocturne.core.fits_io import import_summary
    s = import_summary({"focal_length": 160.0, "pixel_size": 2.9,
                        "width": 100, "height": 100})
    assert "160 mm" in s and "3.7″" in s


def test_import_summary_target_from_filename():
    from nocturne.core.fits_io import import_summary
    s = import_summary({"width": 10, "height": 10},
                       filename="NGC7000_182x20s_61min.fits")
    assert "NGC7000" in s


def test_import_summary_empty_stack_fallback():
    from nocturne.core.fits_io import import_summary
    s = import_summary({})
    assert "Your stack" in s and "Couldn't read" in s
    assert "Total integration" not in s
