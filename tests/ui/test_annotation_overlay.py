import pytest
pytest.importorskip("PySide6")
import numpy as np
from nocturne.core.catalog import CatalogObject
from nocturne.ui.annotation_overlay import build_annotation_group


def test_group_has_a_label_per_object(qtbot):
    objs = [CatalogObject("NGC 7000", "North America", 314.0, 44.0, 120.0, 960, 540),
            CatalogObject("NGC 6997", "", 314.5, 44.5, 8.0, 1200, 400)]
    g = build_annotation_group(objs, north_angle=270.0, scale_len_px=300,
                               scale_label="30′", shape=(1080, 1920), theme="dark")
    # every object contributes at least one child (its label); plus compass + scale
    assert len(g.childItems()) >= len(objs) + 2
