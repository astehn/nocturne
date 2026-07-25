import json
import zipfile

import numpy as np
import pytest

from nocturne.core.image import AstroImage
from nocturne.history.project import Project
from nocturne.history.project_store import (
    FORMAT_VERSION,
    NewerVersionError,
    _ensure_serialized,
    is_reproducible,
    load_project,
    save_project,
)
from nocturne.settings import Settings
from nocturne.steps.factory import make_step


def test_ensure_serialized_passes_through_already_serialized():
    assert _ensure_serialized("stretch", 0.5) == 0.5            # native primitive
    assert _ensure_serialized("levels", [0.06, 1.0, 1.0]) == [0.06, 1.0, 1.0]  # serialized list
    assert _ensure_serialized("saturation", (0.5, 0.2)) == [0.5, 0.2]  # native tuple -> list


def test_ensure_serialized_serializes_native_objects():
    from nocturne.core.color import ColorSettings
    out = _ensure_serialized("color", ColorSettings(method="sky"))
    assert isinstance(out, dict) and out["method"] == "sky"


def test_reproducible_classification():
    assert is_reproducible("stretch", 0.5) is True
    assert is_reproducible("levels", [0.06, 1.0, 1.0]) is True
    assert is_reproducible("crop", {"bounds": [1, 2, 3, 4]}) is False   # lossy serialize -> cache
    assert is_reproducible("background", "strong") is False
    assert is_reproducible("noise_sharpen", {"engine": "rcastro", "level": "strong"}) is False
    assert is_reproducible("color", {"method": "sky"}) is True
    assert is_reproducible("color", {"method": "photometric"}) is False   # Gaia network
    assert is_reproducible("saturation", [0.5, 0.0]) is True
    assert is_reproducible("saturation", [0.5, 0.2]) is False             # nebula -> star split


def test_save_project_writes_bundle(tmp_path):
    base = AstroImage(np.ones((2, 2), np.float32), is_linear=True, metadata={"gain": 10})
    img2 = AstroImage(np.full((2, 2), 2.0, np.float32), is_linear=False)
    img3 = AstroImage(np.full((2, 2), 3.0, np.float32), is_linear=False)
    p = Project(base, str(tmp_path / "cache"))
    p.record_precomputed("Stretch", 0.5, img2)          # reproducible -> no cache file
    p.record_precomputed("Background", "strong", img3)  # not reproducible -> cached

    out_path = tmp_path / "test.nocturne"
    save_project(p, str(out_path), solve_state={"ra": 1.0}, source_label="stack.fit")

    with zipfile.ZipFile(str(out_path)) as zf:
        names = zf.namelist()
        assert "base.npy" in names

        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["format_version"] == FORMAT_VERSION
        assert manifest["position"] == 2
        assert manifest["source_label"] == "stack.fit"
        assert manifest["solve"] == {"ra": 1.0}

        steps = manifest["steps"]
        assert len(steps) == 2

        stretch = steps[0]
        assert stretch["name"] == "Stretch"
        assert stretch["stage"] == "stretch"
        assert stretch["option"] == 0.5
        assert stretch["cached"] is False
        assert stretch["cache"] is None

        background = steps[1]
        assert background["name"] == "Background"
        assert background["stage"] == "background"
        assert background["option"] == "strong"
        assert background["cached"] is True
        assert background["cache"] is not None
        assert background["cache"] in names

        # cached snapshot round-trips through np.load
        with zf.open(background["cache"]) as f:
            import io as _io
            arr = np.load(_io.BytesIO(f.read()))
            assert np.allclose(arr, img3.data)


def _make_project_with_mixed_steps(tmp_path):
    """base -> Stretch (real, reproducible replay via run_step) -> Background
    (cached precomputed step). Base data is non-trivial (not flat/random-free)
    so a real stretch actually transforms it."""
    rng = np.random.default_rng(42)
    base = AstroImage(
        rng.random((6, 6), dtype=np.float32) * 0.5,
        is_linear=True,
        metadata={"gain": 10, "exposure": 30.5},
    )
    p = Project(base, str(tmp_path / "cache"))

    stretch_step = make_step("stretch", Settings())
    p.run_step(stretch_step, 0.5)

    bg_img = AstroImage(
        np.full((6, 6), 0.75, np.float32), is_linear=False, metadata={"note": "bg-removed"}
    )
    p.record_precomputed("Background", "strong", bg_img)
    return p


def test_save_load_round_trip_is_pixel_identical(tmp_path):
    proj = _make_project_with_mixed_steps(tmp_path)
    before = [proj.state_at(i).data.copy() for i in range(proj.position + 1)]

    save_project(proj, str(tmp_path / "p.nocturne"), source_label="ngc.fits")
    loaded = load_project(str(tmp_path / "p.nocturne"), str(tmp_path / "reopen"))

    assert loaded.source_label == "ngc.fits"
    assert loaded.project.position == proj.position
    for i in range(proj.position + 1):
        assert np.array_equal(loaded.project.state_at(i).data, before[i])


def test_save_load_round_trip_preserves_solve_state(tmp_path):
    proj = _make_project_with_mixed_steps(tmp_path)
    save_project(proj, str(tmp_path / "p.nocturne"), solve_state={"ra": 10.5, "dec": -5.2})
    loaded = load_project(str(tmp_path / "p.nocturne"), str(tmp_path / "reopen"))
    assert loaded.solve_state == {"ra": 10.5, "dec": -5.2}


def test_self_contained_after_source_deleted(tmp_path):
    # The bundle embeds the base image, so it must load even when no source
    # file exists anywhere near it (no reference back to an original .fits).
    src = tmp_path / "source.fits"
    src.write_bytes(b"not a real fits file, just proving deletion doesn't matter")

    proj = _make_project_with_mixed_steps(tmp_path)
    before = [proj.state_at(i).data.copy() for i in range(proj.position + 1)]
    save_project(proj, str(tmp_path / "p.nocturne"), source_label=str(src))

    src.unlink()  # source gone; bundle must be fully self-contained
    assert not src.exists()

    loaded = load_project(str(tmp_path / "p.nocturne"), str(tmp_path / "reopen2"))
    assert loaded.project.position == proj.position
    for i in range(proj.position + 1):
        assert np.array_equal(loaded.project.state_at(i).data, before[i])


def test_newer_format_version_raises(tmp_path):
    base = AstroImage(np.ones((2, 2), np.float32), is_linear=True, metadata={})
    manifest = {
        "format_version": FORMAT_VERSION + 1,
        "app_version": None,
        "position": 0,
        "source_label": "",
        "solve": None,
        "base": {"is_linear": base.is_linear, "metadata": base.metadata},
        "steps": [],
    }
    bundle = tmp_path / "future.nocturne"
    with zipfile.ZipFile(str(bundle), "w") as zf:
        import io as _io
        buf = _io.BytesIO()
        np.save(buf, base.data)
        zf.writestr("base.npy", buf.getvalue())
        zf.writestr("manifest.json", json.dumps(manifest))

    with pytest.raises(NewerVersionError):
        load_project(str(bundle), str(tmp_path / "x"))


def test_base_and_cached_step_metadata_round_trips(tmp_path):
    proj = _make_project_with_mixed_steps(tmp_path)
    save_project(proj, str(tmp_path / "p.nocturne"))
    loaded = load_project(str(tmp_path / "p.nocturne"), str(tmp_path / "reopen"))

    base_meta = loaded.project.state_at(0).metadata
    assert base_meta["gain"] == 10
    assert base_meta["exposure"] == 30.5

    cached_meta = loaded.project.state_at(2).metadata
    assert cached_meta["note"] == "bg-removed"


def test_numpy_scalar_metadata_survives_round_trip_with_native_type(tmp_path):
    # A processing step might stuff a computed numpy scalar into metadata
    # (e.g. a numpy.float32/int64 stat). json.dumps(default=str) would silently
    # turn that into a string on the way out; the normalizer must keep it numeric.
    base = AstroImage(
        np.ones((2, 2), np.float32),
        is_linear=True,
        metadata={"gain": np.float32(10.5), "frames": np.int64(3), "nested": {"x": np.float64(1.5)}},
    )
    p = Project(base, str(tmp_path / "cache"))
    save_project(p, str(tmp_path / "p.nocturne"))
    loaded = load_project(str(tmp_path / "p.nocturne"), str(tmp_path / "reopen"))

    meta = loaded.project.state_at(0).metadata
    assert meta["gain"] == pytest.approx(10.5)
    assert isinstance(meta["gain"], float)
    assert meta["frames"] == 3
    assert isinstance(meta["frames"], int)
    assert meta["nested"]["x"] == pytest.approx(1.5)
