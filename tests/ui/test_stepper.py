import pytest

pytest.importorskip("PySide6")
from seestar_processor.ui.pipeline import Stage, path_stages  # noqa: E402
from seestar_processor.ui.stepper import Stepper  # noqa: E402


def test_set_stages_populates_rows(qtbot):
    step = Stepper()
    qtbot.addWidget(step)
    stages = path_stages("in_app")
    step.set_stages(stages)
    assert step.count() == len(stages)


def test_clicking_enabled_stage_emits_index(qtbot):
    step = Stepper()
    qtbot.addWidget(step)
    step.set_stages(path_stages("in_app"))
    received = []
    step.stageSelected.connect(received.append)
    step._on_click(step.item(3))
    assert received == [3]


def test_disabled_stage_does_not_emit(qtbot):
    step = Stepper()
    qtbot.addWidget(step)
    step.set_stages([Stage("a", "A", "import", True), Stage("b", "B", "x", False)])
    received = []
    step.stageSelected.connect(received.append)
    step._on_click(step.item(1))
    assert received == []


def test_mark_done_prefixes_check(qtbot):
    step = Stepper()
    qtbot.addWidget(step)
    step.set_stages(path_stages("in_app"))
    step.mark_done({"crop"})
    crop_row = next(i for i, s in enumerate(path_stages("in_app")) if s.id == "crop")
    assert step.item(crop_row).text().startswith("✓")
