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


def _scroll(dlg):
    return dlg.viewer.verticalScrollBar().value()


def test_a_glossary_link_opens_the_glossary_at_that_term(qtbot):
    from PySide6.QtCore import QUrl
    from nocturne import glossary as gl
    dlg = HelpDialog()
    qtbot.addWidget(dlg)
    dlg.resize(760, 560)
    dlg.show()
    qtbot.waitExposed(dlg)
    dlg.show_topic("stacking")
    last = gl.sorted_terms()[-1]           # far down the page, so it must scroll
    dlg.viewer.anchorClicked.emit(QUrl(f"help:glossary#{last.anchor}"))
    assert dlg.current_topic() == "glossary"
    assert hc.TOPICS["glossary"].title in dlg.viewer.toPlainText()
    assert _scroll(dlg) > 0, "the link opened the glossary but did not go to the term"


def test_a_see_link_in_the_glossary_opens_that_topic(qtbot):
    from PySide6.QtCore import QUrl
    dlg = HelpDialog()
    qtbot.addWidget(dlg)
    dlg.show_topic("glossary")
    dlg.viewer.anchorClicked.emit(QUrl("help:stacking"))
    assert dlg.current_topic() == "stacking"
    assert _scroll(dlg) == 0


def test_a_letter_link_stays_on_the_glossary(qtbot):
    from PySide6.QtCore import QUrl
    dlg = HelpDialog()
    qtbot.addWidget(dlg)
    dlg.resize(760, 560)
    dlg.show()
    qtbot.waitExposed(dlg)
    dlg.show_topic("glossary")
    dlg.viewer.anchorClicked.emit(QUrl("#letter-s"))
    assert dlg.current_topic() == "glossary"
    assert _scroll(dlg) > 0


def test_an_unknown_help_link_does_nothing(qtbot):
    from PySide6.QtCore import QUrl
    dlg = HelpDialog()
    qtbot.addWidget(dlg)
    dlg.show_topic("levels")
    dlg.viewer.anchorClicked.emit(QUrl("help:nope#x"))
    assert dlg.current_topic() == "levels"
