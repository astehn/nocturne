"""The option band shared by Stack and Ha/OIII (spec 2026-09-27 §2.1-2.2)."""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QDialog, QTableView, QVBoxLayout

from nocturne.ui.option_band import OptionBand, WrappedNote

LONG = ("Rebuilds the image on a 2× grid instead of enlarging it — finer detail "
        "and more stars from well-dithered subs. Stacking takes about 10× longer, "
        "and every step afterwards works on an image four times the size.")


def _band(qtbot, summary=lambda: "Normal selection · Sigma-clipped"):
    dlg = QDialog()
    qtbot.addWidget(dlg)
    lay = QVBoxLayout(dlg)
    band = OptionBand(summary)
    for title in ("Frames", "Combine", "Result"):
        g = band.add_group(title)
        g.body.addWidget(QCheckBox(f"{title} option"))
        g.body.addWidget(WrappedNote(LONG))
    lay.addWidget(band)
    lay.addWidget(QTableView(), 1)
    return dlg, band


def test_the_groups_sit_side_by_side_in_one_band(qtbot):
    dlg, band = _band(qtbot)
    dlg.resize(1100, 700); dlg.show(); qtbot.waitExposed(dlg)
    tops = {g.mapTo(dlg, g.rect().topLeft()).y() for g in band.groups}
    lefts = [g.mapTo(dlg, g.rect().topLeft()).x() for g in band.groups]
    assert len(tops) == 1, "the groups are not on one line"
    assert lefts == sorted(lefts) and len(set(lefts)) == 3
    assert [g.title.text() for g in band.groups] == ["FRAMES", "COMBINE", "RESULT"]


def test_folding_shows_one_summary_line_and_change_opens_it_again(qtbot):
    dlg, band = _band(qtbot)
    dlg.resize(1100, 700); dlg.show(); qtbot.waitExposed(dlg)
    seen = []
    band.folded_changed.connect(seen.append)
    qtbot.mouseClick(band.fold_btn, Qt.MouseButton.LeftButton)
    assert band.is_folded() and seen == [True]
    assert not any(g.isVisible() for g in band.groups)
    assert band.summary_label.isVisible()
    assert band.summary_label.text() == "Normal selection · Sigma-clipped"
    qtbot.mouseClick(band.change_btn, Qt.MouseButton.LeftButton)
    assert not band.is_folded() and seen == [True, False]
    assert all(g.isVisible() for g in band.groups)


def test_folding_gives_the_height_to_what_is_below(qtbot):
    dlg, band = _band(qtbot)
    dlg.resize(1100, 700); dlg.show(); qtbot.waitExposed(dlg)
    table = dlg.findChild(QTableView)
    open_h = table.height()
    band.set_folded(True)
    qtbot.waitUntil(lambda: table.height() > open_h + 50, timeout=2000)


def test_the_summary_is_read_when_asked_not_frozen(qtbot):
    state = {"text": "one"}
    dlg, band = _band(qtbot, summary=lambda: state["text"])
    band.set_folded(True)
    state["text"] = "two"
    band.refresh_summary()
    assert band.summary_label.text() == "two"


def test_the_folded_note_shows_only_when_there_is_something_to_say(qtbot):
    dlg, band = _band(qtbot)
    dlg.show(); qtbot.waitExposed(dlg)
    band.set_folded(True)
    band.set_folded_note("")
    assert not band.folded_note.isVisible()
    band.set_folded_note("Drizzle runs on every pointing — expect a very long time.")
    assert band.folded_note.isVisible()


@pytest.mark.parametrize("size", [(1400, 900), (1100, 760), (760, 700)])
def test_the_bands_minimum_height_counts_every_line_of_its_notes(qtbot, size):
    """A plain wrapped QLabel reports ONE line as its minimum. In a box layout
    it still paints fully, but the dialog's minimumSizeHint then understates
    what it needs, and that number is what StackDialog._fit_to_content uses to
    decide a screen is too short and fold the explanations. So the band's
    minimum must include the notes' real wrapped height at their real width.
    760 is the size that reaches the guard: there the notes wrap to more lines
    than the one-line minimum plus the controls can hide."""
    dlg, band = _band(qtbot)
    dlg.resize(*size); dlg.show(); qtbot.waitExposed(dlg)

    def clipped():
        return [n for n in dlg.findChildren(WrappedNote)
                if n.isVisible() and n.height() < n.heightForWidth(n.width()) - 1]

    # A width change re-lays the notes on the NEXT layout pass, not this one.
    qtbot.waitUntil(lambda: not clipped(), timeout=2000)
    need = max(sum(n.heightForWidth(n.width()) for n in g.findChildren(WrappedNote))
               for g in band.groups)
    assert band.minimumSizeHint().height() >= need, (
        f"band minimum {band.minimumSizeHint().height()} px, notes need {need} px")
