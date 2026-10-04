"""The Stretch panel SAYS which colour balance Apply will commit.

The linkage is half of what Apply commits, and until 2026-10-04 nothing on the
panel showed it. Import sets a default and Visual stretch can pick the other
one (Option A, 2026-09-14), so a first-time user who went back and forth (the
2026-10-04 app audit) had to reconstruct the state from the log.

The invariant every test below checks: the line names exactly what
commit_option() would commit — never the Import choice when the two differ.
"""
import re

import numpy as np
import pytest

from tests.ui.test_main_window import _make_fits, _window


def _note(win) -> str:
    text = win._panel.linkage_note.text().replace("<br>", "\n")
    return re.sub(r"<[^>]+>", "", text)


def _says(win) -> str:
    """Which linkage the line names: 'Linked' or 'Unlinked'."""
    m = re.search(r"^Colour balance: (Linked|Unlinked),", _note(win), re.M)
    assert m, _note(win)
    return m.group(1)


def _commits(win) -> str:
    return "Linked" if win._panel.commit_option()["linked"] else "Unlinked"


def _at_stretch(qtbot, tmp_path, *, linked=True):
    win = _window(qtbot, tmp_path)
    win.open_fits(_make_fits(tmp_path))
    if not linked:
        win._set_view_linked(False)
    win._go_to_id("stretch")
    return win


def test_a_linked_import_reads_linked(qtbot, tmp_path):
    win = _at_stretch(qtbot, tmp_path)
    assert _says(win) == _commits(win) == "Linked"
    # In the pinned description box, under the step's own sentence.
    assert win._panel.linkage_note is win._panel.desc_box
    assert _note(win).startswith("Brighten the faint detail")


def test_an_unlinked_import_reads_unlinked(qtbot, tmp_path):
    win = _at_stretch(qtbot, tmp_path, linked=False)
    assert _says(win) == _commits(win) == "Unlinked"


def test_an_unlinked_pick_under_a_linked_import_reads_unlinked(qtbot, tmp_path):
    """The case the audit hit in reverse: the line must follow the PICK, which
    is what Apply commits, not the Import choice it overrode."""
    win = _at_stretch(qtbot, tmp_path)
    win._apply_picked_stretch({"amount": 0.24, "linked": False})
    assert win._view_linked is True, "fixture: Import still says Linked"
    assert _says(win) == _commits(win) == "Unlinked"


def test_a_linked_pick_under_an_unlinked_import_reads_linked_on_the_new_panel(qtbot, tmp_path):
    """This pick rebuilds the stages and replaces the panel: the line has to be
    right on the panel the user is now looking at."""
    win = _at_stretch(qtbot, tmp_path, linked=False)
    old = win._panel
    win._apply_picked_stretch({"amount": 0.24, "linked": True})
    assert win._panel is not old, "fixture: the rebuild replaced the panel"
    assert _says(win) == _commits(win) == "Linked"


def test_a_committed_unlinked_stretch_still_reads_unlinked_when_revisited(qtbot, tmp_path):
    win = _at_stretch(qtbot, tmp_path)
    win._apply_picked_stretch({"amount": 0.24, "linked": False})
    win._panel.apply_btn.click(); qtbot.wait(50)
    win._go_to_id("levels"); qtbot.wait(20)
    win._go_to_id("stretch"); qtbot.wait(20)
    assert _says(win) == _commits(win) == "Unlinked"


@pytest.mark.parametrize("linked", [True, False], ids=["linked", "unlinked"])
def test_the_stretch_step_still_fits_at_1280x800(qtbot, tmp_path, linked):
    """The review that caught it (2026-10-04): the first version was a label in
    the card, and Stretch at 1280x800 had 16 px to spare — even one line made
    the step scroll. In the description box it costs the scroll nothing, and
    both wordings must fit the box's two lines under the real stylesheet."""
    from tests.ui.test_stable_frame import _settle, _themed_window
    from PySide6.QtWidgets import QApplication, QLabel
    app = QApplication.instance()
    before = app.styleSheet()
    try:
        win = _themed_window(qtbot, tmp_path, (1280, 800))
        if not linked:
            win._set_view_linked(False)
        win._go_to_id("stretch", user_initiated=False)
        _settle(qtbot)
        assert _says(win) == ("Linked" if linked else "Unlinked"), "fixture"
        assert win._side.scroll.verticalScrollBar().maximum() == 0
        d = win._panel.desc_box
        free = QLabel(d.text()); free.setObjectName("stepDesc"); free.setWordWrap(True)
        free.setParent(d.parentWidget()); free.hide(); free.ensurePolished()
        assert free.heightForWidth(d.width()) <= d.height(), "the box would clip a third line"
    finally:
        app.setStyleSheet(before)


# --- said before the switch, not only after it ---------------------------

def _colour_caveats(win):
    pick = win._stretch_picks()[0]
    assert pick.key == "linked", "fixture: colour is the first question"
    return pick.caveats


def test_under_an_unlinked_import_the_linked_choice_warns_of_the_switch(qtbot, tmp_path):
    win = _at_stretch(qtbot, tmp_path, linked=False)
    caveats = _colour_caveats(win)
    assert "Colour is offered again" in caveats.get(True, "")
    assert False not in caveats, "no SPCC was applied, so no calibration warning"


def test_under_a_linked_import_neither_choice_carries_a_note(qtbot, tmp_path):
    """Linked here switches nothing; a note on it would be noise."""
    win = _at_stretch(qtbot, tmp_path)
    assert _colour_caveats(win) == {}


def test_both_notes_can_stand_together(qtbot, tmp_path):
    from nocturne.core.image import AstroImage
    from nocturne.ui.stretch_picker import colour_pick
    rng = np.random.default_rng(0)
    img = AstroImage(rng.random((64, 64, 3)).astype(np.float32), is_linear=True)
    caveats = colour_pick(img, spcc_applied=True, view_linked=False).caveats
    assert set(caveats) == {True, False}
