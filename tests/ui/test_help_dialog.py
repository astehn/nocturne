import pytest

pytest.importorskip("PySide6")
from nocturne.ui.help_dialog import HelpDialog  # noqa: E402
from nocturne.ui import help_content as hc  # noqa: E402


def test_help_dialog_lists_sections_and_topics(qtbot):
    dlg = HelpDialog()
    qtbot.addWidget(dlg)
    labels = [dlg.nav.item(i).text() for i in range(dlg.nav.count())]
    assert any("Concepts" in x for x in labels)
    assert any("Stretch" in x for x in labels)


def test_show_topic_renders_body(qtbot):
    dlg = HelpDialog()
    qtbot.addWidget(dlg)
    dlg.show_topic("background")
    assert hc.TOPICS["background"].title in dlg.viewer.toPlainText()


def test_show_unknown_topic_does_not_raise(qtbot):
    dlg = HelpDialog()
    qtbot.addWidget(dlg)
    dlg.show_topic("nope")
