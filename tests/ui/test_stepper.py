import pytest

pytest.importorskip("PySide6")
from seestar_processor.ui.pipeline import PIPELINE  # noqa: E402
from seestar_processor.ui.stepper import Stepper  # noqa: E402


def _index(stage_id):
    return next(i for i, s in enumerate(PIPELINE) if s.id == stage_id)


def test_clicking_enabled_stage_emits_index(qtbot):
    step = Stepper()
    qtbot.addWidget(step)
    received = []
    step.stageSelected.connect(received.append)
    step._on_click(step.item(_index("stretch")))
    assert received == [_index("stretch")]


def _patched_pipeline(monkeypatch):
    # Every real stage is enabled now; exercise the disabled-handling code path
    # against a synthetic pipeline that still has a disabled stage.
    from seestar_processor.ui.pipeline import Stage
    custom = [Stage("a", "A", "load", True), Stage("b", "B", "placeholder", False)]
    monkeypatch.setattr("seestar_processor.ui.stepper.PIPELINE", custom)
    return custom


def test_clicking_disabled_stage_emits_nothing(qtbot, monkeypatch):
    _patched_pipeline(monkeypatch)
    step = Stepper()
    qtbot.addWidget(step)
    received = []
    step.stageSelected.connect(received.append)
    step._on_click(step.item(1))  # the disabled stage
    assert received == []


def test_disabled_items_are_not_selectable(qtbot, monkeypatch):
    _patched_pipeline(monkeypatch)
    step = Stepper()
    qtbot.addWidget(step)
    from PySide6.QtCore import Qt
    assert not (step.item(1).flags() & Qt.ItemFlag.ItemIsEnabled)


def test_mark_done_prefixes_check(qtbot):
    step = Stepper()
    qtbot.addWidget(step)
    step.mark_done({"background"})
    assert step.item(_index("background")).text().startswith("✓")
