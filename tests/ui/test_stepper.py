import pytest

pytest.importorskip("PySide6")
from seestar_processor.ui.pipeline import Stage, path_stages  # noqa: E402
from seestar_processor.ui.stepper import Stepper  # noqa: E402


def test_set_stages_populates_rows(qtbot):
    step = Stepper()
    qtbot.addWidget(step)
    stages = path_stages()
    step.set_stages(stages)
    assert step.count() == len(stages)


def test_clicking_enabled_stage_emits_index(qtbot):
    step = Stepper()
    qtbot.addWidget(step)
    step.set_stages(path_stages())
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


def test_step_state_pure():
    from seestar_processor.ui.stepper import step_state
    # locked wins regardless
    assert step_state(2, 2, {2}, enabled=False) == "locked"
    # current wins over done
    assert step_state(1, 1, {1}, enabled=True) == "current"
    assert step_state(0, 3, {0, 1}, enabled=True) == "done"
    assert step_state(4, 3, {0, 1}, enabled=True) == "upcoming"


def test_mark_done_sets_done_state(qtbot):
    step = Stepper()
    qtbot.addWidget(step)
    step.set_stages(path_stages())
    step.set_current(0)                     # "load" is current
    step.mark_done({"crop"})
    crop_row = next(i for i, s in enumerate(path_stages()) if s.id == "crop")
    assert step.state_at(crop_row) == "done"


def test_current_state(qtbot):
    step = Stepper()
    qtbot.addWidget(step)
    step.set_stages(path_stages())
    step.set_current(2)
    assert step.state_at(2) == "current"
