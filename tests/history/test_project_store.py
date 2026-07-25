import json
import zipfile

import numpy as np

from nocturne.core.image import AstroImage
from nocturne.history.project import Project
from nocturne.history.project_store import (
    FORMAT_VERSION,
    _ensure_serialized,
    is_reproducible,
    save_project,
)


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
