import pytest

pytest.importorskip("PySide6")
from nocturne.ui.readout_pill import ReadoutPill  # noqa: E402


def test_pill_starts_hidden(qtbot):
    pill = ReadoutPill()
    qtbot.addWidget(pill)
    assert pill.isHidden()


def test_show_text_sets_the_text_and_reveals_the_pill(qtbot):
    pill = ReadoutPill()
    qtbot.addWidget(pill)
    pill.show_text("1284, 772 · R 0.82")
    assert pill.text() == "1284, 772 · R 0.82"
    assert not pill.isHidden()


def test_show_text_resizes_to_fit_its_content(qtbot):
    pill = ReadoutPill()
    qtbot.addWidget(pill)
    pill.show_text("x")
    narrow = pill.width()
    pill.show_text("1284, 772 · R 0.82 G 0.79 B 0.74 · L 0.79 · linear")
    assert pill.width() > narrow


def test_pill_carries_the_styling_object_name(qtbot):
    pill = ReadoutPill()
    qtbot.addWidget(pill)
    assert pill.objectName() == "readoutPill"
