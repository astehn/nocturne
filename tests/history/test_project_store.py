from nocturne.history.project_store import _ensure_serialized, is_reproducible


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
