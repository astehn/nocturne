from seestar_processor.ui.pipeline import (
    PIPELINE, next_enabled, prev_enabled, STEP_NAME, PROCESSING_ORDER,
)


def _index(stage_id):
    return next(i for i, s in enumerate(PIPELINE) if s.id == stage_id)


def test_pipeline_order_and_enablement():
    ids = [s.id for s in PIPELINE]
    assert ids == [
        "load", "crop", "background", "color", "deconvolution",
        "noise", "stretch", "final_fixes", "export",
    ]
    enabled = {s.id for s in PIPELINE if s.enabled}
    assert enabled == {"load", "crop", "background", "color", "stretch", "export"}


def test_next_enabled_skips_disabled_and_clamps():
    assert next_enabled(_index("load")) == _index("crop")
    assert next_enabled(_index("crop")) == _index("background")
    assert next_enabled(_index("background")) == _index("color")
    assert next_enabled(_index("color")) == _index("stretch")
    assert next_enabled(_index("stretch")) == _index("export")
    last = _index("export")
    assert next_enabled(last) == last  # clamp at end


def test_prev_enabled_skips_disabled_and_clamps():
    assert prev_enabled(_index("stretch")) == _index("color")
    assert prev_enabled(_index("color")) == _index("background")
    assert prev_enabled(_index("background")) == _index("crop")
    assert prev_enabled(_index("crop")) == _index("load")
    assert prev_enabled(_index("load")) == _index("load")  # clamp at start


def test_step_name_and_order():
    assert STEP_NAME == {
        "crop": "Crop", "background": "Background", "color": "Color", "stretch": "Stretch",
    }
    assert PROCESSING_ORDER == ["crop", "background", "color", "stretch"]
