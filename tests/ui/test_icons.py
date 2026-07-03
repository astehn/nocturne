import xml.etree.ElementTree as ET

import pytest

pytest.importorskip("PySide6")
from seestar_processor.ui.icons import ICON_NAMES, load_icon, _ICON_DIR  # noqa: E402


def test_all_named_svgs_exist_and_are_valid_xml():
    for name in ICON_NAMES:
        path = _ICON_DIR / f"{name}.svg"
        assert path.exists(), f"missing icon: {name}"
        ET.parse(str(path))  # raises if malformed


def test_load_icon_returns_icon(qtbot):
    icon = load_icon("stack")
    assert not icon.isNull()


def test_load_icon_cached(qtbot):
    assert load_icon("palette") is load_icon("palette")


def test_load_icon_unknown_raises(qtbot):
    with pytest.raises(FileNotFoundError):
        load_icon("does-not-exist")
