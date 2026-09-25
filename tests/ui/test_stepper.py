import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QRectF  # noqa: E402
from PySide6.QtGui import QPainter  # noqa: E402
from nocturne.ui.pipeline import Stage, path_stages  # noqa: E402
from nocturne.ui.stepper import STEP_ROW_H, Stepper, step_state  # noqa: E402


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
    from nocturne.ui.stepper import step_state
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


# --- a step you PASSED vs one you have not reached ------------------------
# Andreas, 2026-09-13: "upcoming" was doing two jobs. A step you walked past and
# chose not to apply, and one you have never been to, rendered identically grey.
# At the end of a pass "which steps did I skip?" is a real question, and the
# list is the only thing on screen placed to answer it.
#
# Derivable at a glance ONLY while the walk is linear — grey above the current
# row was passed, grey below is unreached. Jumping back breaks that, and that is
# exactly when you would want to ask. Hence a high-water mark rather than
# comparing against the current index.

def test_a_row_below_the_high_water_mark_is_skipped():
    assert step_state(2, current_index=5, done_indexes=set(), enabled=True,
                      high_water=5) == "skipped"


def test_a_row_above_it_is_still_upcoming():
    assert step_state(7, current_index=5, done_indexes=set(), enabled=True,
                      high_water=5) == "upcoming"


def test_applied_beats_skipped():
    """Green means applied; walking past an applied step does not un-apply it."""
    assert step_state(2, current_index=5, done_indexes={2}, enabled=True,
                      high_water=5) == "done"


def test_the_current_row_is_never_skipped():
    """You are standing on it — it has not been passed yet."""
    assert step_state(5, current_index=5, done_indexes=set(), enabled=True,
                      high_water=5) == "current"


def test_locked_beats_skipped():
    assert step_state(2, current_index=5, done_indexes=set(), enabled=False,
                      high_water=5) == "locked"


def test_without_a_high_water_mark_nothing_is_skipped():
    """The default preserves the old four-state behaviour for any caller that
    has not been taught about it."""
    assert step_state(2, current_index=5, done_indexes=set(), enabled=True) == "upcoming"


def test_jumping_back_does_not_un_skip_what_you_passed():
    """The reason this is a high-water mark and not `index < current_index`.

    Walk to 8, jump back to 3: rows 4-7 were still passed, and comparing against
    the current index would quietly call them unreached again — precisely when
    the question is hardest to answer from memory.
    """
    assert step_state(6, current_index=3, done_indexes=set(), enabled=True,
                      high_water=8) == "skipped"


# --- 32 px rows, no phantom pill, unavailable rows say why -----------------

def _stepper(qtbot, stages):
    s = Stepper()
    qtbot.addWidget(s)
    s.resize(240, 800)
    s.set_stages(stages)
    return s


def test_rows_are_32px(qtbot):
    s = _stepper(qtbot, [Stage("a", "Import", "import"), Stage("b", "Crop", "crop")])
    assert s.sizeHintForRow(0) == STEP_ROW_H == 32


def test_ideal_height_fits_every_row_without_scrolling(qtbot):
    stages = [Stage(str(i), f"Step {i}", "process") for i in range(17)]
    s = _stepper(qtbot, stages)
    assert s.ideal_height() >= 17 * 32
    assert s.ideal_height() <= 17 * 32 + 8


def test_the_label_is_not_cut_short_by_a_pill_that_is_not_drawn(qtbot):
    """'Noise Reductio' (screenshot 17): the label rect always reserved room
    for the 'soon' pill, which only a locked row draws."""
    from nocturne.ui import stepper as mod
    assert mod.label_rect_width(200, locked=False) > mod.label_rect_width(200, locked=True)
    assert mod.label_rect_width(200, locked=False) == 200 - 36 - 8


def test_an_unavailable_row_says_why(qtbot):
    stage = Stage("color", "Color", "auto", enabled=False)
    object.__setattr__(stage, "reason", "Needs a linked stretch.")   # Stage is frozen
    s = _stepper(qtbot, [stage])
    assert s.item(0).toolTip() == "Needs a linked stretch."


def test_paint_actually_uses_label_rect_width(qtbot):
    """The `label_rect_width` unit test above only exercises the helper — it
    would still pass if StepDelegate.paint never called it (wrong `locked=`
    expression, or a hardcoded `r.width() - 80`). This watches the real paint
    path by spying on QPainter.drawText while the widget is actually rendered,
    which is exactly the code path that shipped "Noise Reductio"."""
    from nocturne.ui import stepper as mod

    stages = [Stage("a", "Noise Reduction", "process"),
              Stage("b", "Locked Step", "process", enabled=False)]
    s = _stepper(qtbot, stages)
    s.set_current(0)

    calls = []
    original_draw_text = QPainter.drawText

    def spy(self, *args, **kwargs):
        calls.append(args)
        return original_draw_text(self, *args, **kwargs)

    QPainter.drawText = spy
    try:
        s.grab()   # forces a real, synchronous paint (offscreen-safe)
    finally:
        QPainter.drawText = original_draw_text

    def rect_for(text):
        for args in calls:
            if args and isinstance(args[0], QRectF) and args[-1] == text:
                return args[0]
        return None

    current_rect = rect_for("Noise Reduction")
    locked_rect = rect_for("Locked Step")
    assert current_rect is not None, "label draw for the current row was not observed"
    assert locked_rect is not None, "label draw for the locked row was not observed"

    unlocked_row_width = s.visualItemRect(s.item(0)).width()
    locked_row_width = s.visualItemRect(s.item(1)).width()
    assert current_rect.width() == mod.label_rect_width(unlocked_row_width, locked=False)
    assert locked_rect.width() == mod.label_rect_width(locked_row_width, locked=True)
