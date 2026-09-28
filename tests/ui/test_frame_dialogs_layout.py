"""Layout A holds at the sizes that matter, in both dialogs, under the real
stylesheet (spec 2026-09-27 §2.4.7, §7): the preview is wider than the list,
the divider is easy to hit, no explanation is cut, and the options fold.

Offscreen fonts differ from cocoa, so these assert RELATIONS (preview wider
than list, nothing clipped), never pixel values.
"""
from datetime import datetime, timedelta, timezone

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QFormLayout, QProxyStyle, QStyle, QStyleFactory

from nocturne.settings import Settings
from nocturne.stacking.grade import FrameStats
from nocturne.ui.frame_browser import COL_VERDICT
from nocturne.ui.haoiii_dialog import HaOIIIDialog
from nocturne.ui.option_band import WrappedNote
from nocturne.ui.stack_dialog import StackDialog
from nocturne.ui.theme import build_stylesheet

SIZES = [(1280, 800), (1920, 1080)]
T0 = datetime(2026, 9, 21, 20, 0, tzinfo=timezone.utc)


def _chart_within_dialog(dialog, chart) -> bool:
    """The chart's own rect, mapped into the dialog, lies inside the dialog
    and inside its immediate parent.

    Final review, T7: `chart.height() == CHART_HEIGHT` is true whatever the
    layout does — `QualityChart.setFixedHeight(CHART_HEIGHT)` guarantees the
    WIDGET's own height, so a squeezed layout that pushes the chart past its
    parent's edge (clipped, not shortened) still passed. This checks the
    thing that can actually go wrong: the chart's geometry sitting fully
    inside both its parent and the dialog.
    """
    parent_rect = chart.parentWidget().rect()
    if chart.geometry().bottom() > parent_rect.bottom():
        return False
    top_left = chart.mapTo(dialog, chart.rect().topLeft())
    bottom_right = chart.mapTo(dialog, chart.rect().bottomRight())
    return dialog.rect().contains(top_left) and dialog.rect().contains(bottom_right)


@pytest.fixture(autouse=True)
def styled():
    app = QApplication.instance()
    before = app.styleSheet()
    app.setStyleSheet(build_stylesheet())
    yield
    app.setStyleSheet(before)


def _session(n=254):
    """A night shaped like his Sh2-108 folder: most frames fine, a run of
    soft ones and a run of trailed ones, so the Verdict column carries its
    LONGEST real strings — the case that could push the list wide."""
    stats = []
    for i in range(n):
        fwhm = 3.1 if i < 20 else 2.5 + 0.01 * (i % 7)
        elong = 1.45 if 100 <= i < 130 else 1.10 + 0.005 * (i % 5)
        s = FrameStats(f"/x/Light_SH2-108_10.0s_LP_{i:04d}.fit", 1200 - i % 50,
                       fwhm, 0.02, 0.5, True, elongation=elong, exposure=10.0,
                       target="SH2-108")
        s.captured = T0 + timedelta(seconds=11 * i)
        stats.append(s)
    return stats


def _open(qtbot, cls, size):
    d = cls(Settings(frame_options_folded=False))
    qtbot.addWidget(d)
    if cls is StackDialog:
        d._available_height = lambda: 4000
    d.resize(*size)
    d.show()
    qtbot.waitExposed(d)
    d._on_graded(_session())
    qtbot.wait(20)
    return d


@pytest.mark.parametrize("cls", [StackDialog, HaOIIIDialog])
@pytest.mark.parametrize("size", SIZES)
def test_the_preview_is_wider_than_the_list(qtbot, cls, size):
    d = _open(qtbot, cls, size)
    lst, pv = d.browser.splitter.sizes()
    assert pv > lst, f"{cls.__name__} at {size}: list {lst} px, preview {pv} px"
    assert any("Stars trailed" in d.browser.cell_text(r, COL_VERDICT)
               for r in range(len(d.browser.frames()))), "fixture lost its long verdicts"


@pytest.mark.parametrize("cls", [StackDialog, HaOIIIDialog])
def test_the_divider_is_easy_to_hit_in_the_dialog(qtbot, cls):
    d = _open(qtbot, cls, (1280, 800))
    assert d.browser.splitter.handle(1).width() >= 10


@pytest.mark.parametrize("cls", [StackDialog, HaOIIIDialog])
@pytest.mark.parametrize("size", SIZES)
def test_no_note_is_cut_off_in_either_dialog(qtbot, cls, size):
    d = _open(qtbot, cls, size)

    def clipped():
        return [n.text()[:30] for n in d.findChildren(WrappedNote)
                if n.isVisible() and n.height() < n.heightForWidth(n.width()) - 1]

    qtbot.waitUntil(lambda: not clipped(), timeout=2000)


@pytest.mark.parametrize("cls", [StackDialog, HaOIIIDialog])
def test_folding_gives_the_list_the_height(qtbot, cls):
    d = _open(qtbot, cls, (1280, 800))
    before = d.browser.height()
    d.options_band.set_folded(True)
    qtbot.waitUntil(lambda: d.browser.height() > before + 40, timeout=2000)


def _uniform_session(n=254):
    """The same shape as `_session()` — count, exposure, target, capture
    times — but with NOTHING for judge() to reject: uniform FWHM and
    elongation, no soft or trailed run. Used only to isolate whether a
    layout decision follows from the "Move N frames to rejected/…" row
    specifically, by comparing against a session that never shows it."""
    stats = []
    for i in range(n):
        s = FrameStats(f"/x/Light_SH2-108_10.0s_LP_{i:04d}.fit", 1200 - i % 50,
                       2.5, 0.02, 0.5, True, elongation=1.10, exposure=10.0,
                       target="SH2-108")
        s.captured = T0 + timedelta(seconds=11 * i)
        stats.append(s)
    return stats


def _fit_at_740(qtbot, session):
    settings = Settings(frame_options_folded=False)
    settings.stack_help_expanded = True
    d = StackDialog(settings)
    qtbot.addWidget(d)
    d._available_height = lambda: 740
    d.resize(1280, 700)
    d.show()
    qtbot.waitExposed(d)
    d._on_graded(session)
    qtbot.wait(50)                   # let any late layout pass land
    return d, settings


def test_stack_fits_the_1280x800_laptop_with_the_help_on(qtbot):
    """The floor this app targets: 800 px of screen, 740 of it usable
    (_available_height's own margin). With the explanations on, the band is
    taller than the old form; _fit_to_content must still land the dialog on
    the screen — by folding the explanations first, as it did before layout A
    — with the preview at its minimum or better.

    Task 6 (spec decision 7) adds a real row here: `_session()`'s soft and
    trailed runs are now unticked frames the "Move N frames to rejected/…"
    button names, which the old form never showed (the buttons existed but
    their counts, and so their visibility, were never wired until Task 6).
    That is 20 px this test's screen genuinely does not have after folding
    the explanations alone (752 against 740, measured 2026-09-27) — so
    folding the option band too, the SAME fallback `_keep_on_screen` already
    had for a taller band, is the correct next step, not a regression. What
    must still hold is the floor itself: on screen, and the preview usable.
    """
    d, settings = _fit_at_740(qtbot, _session())
    assert d.height() <= 740, f"{d.height()} px on a 740 px screen"
    assert d.preview.height() >= 220
    assert d.verdict_strip.move_btn.isVisible(), "fixture lost its rejects"
    assert settings.stack_help_expanded is True, "the screen must not rewrite the preference"

    # Fix round 1, m5 — rewritten in fix round 2 for accuracy. Two things the
    # first version of this comment got wrong:
    #
    # It framed `kept` below as isolating JUST the move-button row. It does
    # not: `_uniform_session()` also has no soft or trailed frames, so the
    # Verdict column and the strip's own detail line are shorter too ("OK"
    # against "Soft stars (FWHM …)" / "Stars trailed (…)"). This is a
    # comparison of "a session with something to report" against "one with
    # nothing to report" — several differences at once, not a controlled
    # isolation of the row alone.
    #
    # It also claimed "732 to 766 px measured... across runs" as this test's
    # own finding. 766 is `_minimum_with_the_help_folded`'s own docstring
    # figure for COCOA (not offscreen), quoted from elsewhere and presented
    # here as if independently reproduced. What IS true, and is why neither
    # `_minimum_with_the_help_folded` nor a same-dialog before/after toggle
    # works as a check here: the latter is thrown off by `_clamp_to_screen`
    # already having shrunk THIS dialog's own list floor once a fallback made
    # it fit — recomputing after toggling folds back only replays that
    # already-baked-in shrink — and the former builds a SEPARATE widget tree,
    # which this codebase's own rule already warns against comparing by pixel
    # count (CLAUDE.md: offscreen fonts differ; assert RELATIONS, never pixel
    # values).
    #
    # The relation that survives both problems is comparative, not absolute:
    # build a SECOND dialog, same settings and room, from a session with
    # nothing to report at all. It must fit without needing either fallback
    # `_keep_on_screen` offers. The first dialog, with something to report,
    # must have needed at least one of them.
    kept, _ = _fit_at_740(qtbot, _uniform_session())
    assert not kept.verdict_strip.move_btn.isVisible(), "fixture rejected a frame"
    assert kept.height() <= 740
    assert not kept.options_band.is_folded() and not kept.verdict_strip.is_compact(), (
        "folded or compacted something although nothing needed the row Task 6 added")
    # The row itself costs real height (spec decision 7 gave it a full
    # button, not a footnote), so fitting the SAME screen alongside it must
    # have cost something the reject-free dialog above never needed to pay.
    assert d.options_band.is_folded() or d.verdict_strip.is_compact(), (
        "fit the taller strip for free — the row Task 6 added should have "
        "forced some fallback, the same way a taller Verdict column already did"
    )

    # Delivery B: the verdict and the chart are both on screen, the verdict
    # whole, and the list the chart took its height from still shows rows.
    assert not d.verdict_strip.isHidden() and not d.verdict_strip.is_compact()
    assert d.browser.chart.isVisible() and _chart_within_dialog(d, d.browser.chart)
    v = d.browser.view
    assert v.viewport().height() >= 3 * v.rowHeight(0), "the list gave up every row"

    def clipped():
        return [n.text()[:30] for n in d.findChildren(WrappedNote)
                if n.isVisible() and n.height() < n.heightForWidth(n.width()) - 1]

    qtbot.waitUntil(lambda: not clipped(), timeout=2000)


def _minimum_with_the_help_folded(qtbot, graded=False) -> int:
    """What the dialog needs with the explanations folded and the options
    open — measured, not hard-coded: it is 643 px offscreen and 688 under
    cocoa (766 graded), so any fixed screen height tests one font only."""
    settings = Settings(frame_options_folded=False)
    settings.stack_help_expanded = False
    d = StackDialog(settings)
    qtbot.addWidget(d)
    d._available_height = lambda: 4000
    d.resize(1280, 700)
    d.show()
    qtbot.waitExposed(d)
    if graded:
        d._on_graded(_session())
    need = d._settled_minimum_height()
    d.close()
    return need


def _short_stack(qtbot, room):
    settings = Settings(frame_options_folded=False)
    settings.stack_help_expanded = True
    d = StackDialog(settings)
    qtbot.addWidget(d)
    d._available_height = lambda: room
    d.resize(1280, 700)
    d.show()
    qtbot.waitExposed(d)
    return d, settings


def test_a_shorter_screen_folds_the_options_too_without_saving_it(qtbot):
    """If collapsing the explanations is not enough, the band folds for this
    window — and, like the help, the saved preference is untouched."""
    room = _minimum_with_the_help_folded(qtbot) - 1
    d, settings = _short_stack(qtbot, room)
    assert d.options_band.is_folded()
    assert d.height() <= room, f"{d.height()} px on a {room} px screen"
    assert settings.frame_options_folded is False, "the screen rewrote the preference"
    assert settings.stack_help_expanded is True


def test_the_grade_that_outgrows_the_screen_folds_the_options(qtbot):
    """The laptop case under cocoa: the empty dialog fits with the help
    folded (688 px), the graded one does not (766 — the status line and the
    drizzle advice arrive with the grade). The window must not follow its
    content off the bottom of the screen."""
    empty = _minimum_with_the_help_folded(qtbot)
    graded = _minimum_with_the_help_folded(qtbot, graded=True)
    assert graded > empty + 20, "the fixture no longer grows the dialog"
    room = (empty + graded) // 2
    d, settings = _short_stack(qtbot, room)
    assert not d.options_band.is_folded(), "folded before it had to"
    d._on_graded(_session())
    assert d.options_band.is_folded(), "not fitted as the grade landed"
    qtbot.wait(50)                   # let any late layout pass land
    assert d.options_band.is_folded()
    assert d.height() <= room, f"{d.height()} px on a {room} px screen"
    assert d.preview.height() >= 220
    assert settings.frame_options_folded is False, "the screen rewrote the preference"


def test_later_content_that_outgrows_the_screen_is_refitted(qtbot):
    """Not only the grade: any note that arrives later grows the window
    through its minimum. resizeEvent catches what no caller announces."""
    empty = _minimum_with_the_help_folded(qtbot)
    room = empty + 5
    d, _settings = _short_stack(qtbot, room)
    assert not d.options_band.is_folded()
    d.status.setText("A long status line\nwith a second line\nand a third "
                     "\nand a fourth, taller than the room left")
    qtbot.waitUntil(lambda: d.options_band.is_folded() and d.height() <= room,
                    timeout=2000)


def test_the_users_own_toggle_outranks_the_screen(qtbot):
    """While the screen has the explanations folded the link reads "▸", so
    ONE click means "show" -- and since every explanation lives in the option
    band, the band the screen folded opens with them (Ruling R6): the link
    must never light ▾ and show nothing. The window still stays on the
    screen, and nothing folds them away again behind the user's back."""
    room = _minimum_with_the_help_folded(qtbot) - 1
    d, settings = _short_stack(qtbot, room)
    assert d._hints_forced_closed and d.options_band.is_folded()
    d._toggle_hints()
    assert not d.options_band.is_folded(), "▾ lit on a folded band"
    assert d.mosaic_hint.isVisible(), "the click showed no explanation"
    assert "▾" in d._help_link.text()
    assert settings.stack_help_expanded is True
    qtbot.wait(50)
    assert not d.options_band.is_folded(), "re-folded behind the user's back"
    assert d.mosaic_hint.isVisible(), "folded away again behind the user's back"
    assert d.height() <= room, f"{d.height()} px on a {room} px screen"
    d._toggle_hints()                      # hiding the help leaves the band open
    qtbot.wait(50)
    assert not d.options_band.is_folded()
    assert not d.mosaic_hint.isVisible()


def test_showing_the_help_opens_a_band_the_user_folded(qtbot):
    """The same for a fold the user made: the help is inside the band."""
    settings = Settings(frame_options_folded=False)
    settings.stack_help_expanded = False
    d = StackDialog(settings)
    qtbot.addWidget(d)
    d._available_height = lambda: 4000
    d.resize(1280, 700)
    d.show()
    qtbot.waitExposed(d)
    d.options_band.set_folded(True)        # by hand
    assert settings.frame_options_folded is True
    d._toggle_hints()
    qtbot.wait(20)
    assert not d.options_band.is_folded()
    assert d.mosaic_hint.isVisible()
    assert settings.stack_help_expanded is True
    assert settings.frame_options_folded is False, "saved like the user's own unfold"


def _arrow(d) -> str:
    text = d._help_link.text()
    assert ("▾" in text) != ("▸" in text), text
    return "▾" if "▾" in text else "▸"


def _roomy_stack(qtbot, settings, saves=None):
    d = StackDialog(settings, on_settings_changed=(
        None if saves is None else
        lambda: saves.append((settings.frame_options_folded, settings.stack_help_expanded))))
    qtbot.addWidget(d)
    d._available_height = lambda: 4000
    d.resize(1280, 700)
    d.show()
    qtbot.waitExposed(d)
    return d


def test_opened_folded_with_the_help_on_the_link_says_nothing_is_shown(qtbot):
    """Final review I1: the band folded and help on read "▾" over no
    explanation at all, and the first click saved help OFF and changed
    nothing on screen. The arrow says what is visible; "▸" means show."""
    settings = Settings()
    settings.frame_options_folded = True
    settings.stack_help_expanded = True
    saves = []
    d = _roomy_stack(qtbot, settings, saves)
    assert d.options_band.is_folded()
    assert _arrow(d) == "▸", "▾ over a folded band that shows nothing"
    d._toggle_hints()
    qtbot.wait(20)
    assert not d.options_band.is_folded(), "the click did not open the band"
    assert d.mosaic_hint.isVisible(), "the click showed no explanation"
    assert _arrow(d) == "▾"
    assert settings.stack_help_expanded is True, "the click saved help off"
    assert saves == [(False, True)], f"saved {saves}, not once with both"


def test_folding_the_band_with_the_help_on_turns_the_arrow(qtbot):
    """Folding by hand hides every explanation with the band; the link
    follows, and "Change…" brings both back with ▾."""
    settings = Settings(frame_options_folded=False)
    settings.stack_help_expanded = True
    d = _roomy_stack(qtbot, settings)
    assert _arrow(d) == "▾" and d.mosaic_hint.isVisible()
    d.options_band.fold_btn.click()
    qtbot.wait(20)
    assert _arrow(d) == "▸", "▾ kept over a folded band"
    assert settings.stack_help_expanded is True, "folding must not rewrite the help preference"
    d.options_band.change_btn.click()
    qtbot.wait(20)
    assert _arrow(d) == "▾" and d.mosaic_hint.isVisible()
    d.options_band.fold_btn.click()
    d._toggle_hints()                      # ▸ on the folded band: show
    qtbot.wait(20)
    assert not d.options_band.is_folded() and _arrow(d) == "▾"
    assert settings.stack_help_expanded is True


def test_the_screens_fold_turns_the_arrow_too(qtbot):
    """The screen's fold is signal-blocked, so the link is told directly."""
    room = _minimum_with_the_help_folded(qtbot) - 1
    d, settings = _short_stack(qtbot, room)
    assert d.options_band.is_folded()
    assert _arrow(d) == "▸"
    assert settings.stack_help_expanded is True


def test_the_users_change_outranks_the_screens_fold(qtbot):
    """"Change…" on a band the screen folded opens it, and it stays open:
    the screen does not fold it straight back."""
    room = _minimum_with_the_help_folded(qtbot) - 1
    d, settings = _short_stack(qtbot, room)
    assert d.options_band.is_folded()
    d.options_band.change_btn.click()
    qtbot.wait(50)
    assert not d.options_band.is_folded(), "re-folded behind the user's back"
    assert settings.frame_options_folded is False
    assert d.height() <= room, f"{d.height()} px on a {room} px screen"


def test_the_users_help_click_never_runs_off_the_screen(qtbot):
    """Options opened by hand AND the explanations asked for: more than the
    screen holds (842 px on 642 measured offscreen). The click outranks the
    screen's folds, never its edge -- the frame list gives up the height."""
    room = _minimum_with_the_help_folded(qtbot) - 1
    d, settings = _short_stack(qtbot, room)
    d.options_band.change_btn.click()
    d._toggle_hints()
    qtbot.wait(50)
    assert not d.options_band.is_folded() and d.mosaic_hint.isVisible()
    assert d.height() <= room, f"{d.height()} px on a {room} px screen"
    squeezed = d.browser.minimumHeight()
    assert 0 < squeezed < d.browser.minimumSizeHint().height()
    d._toggle_hints()                      # hide them again: the list gets height back
    qtbot.wait(50)
    assert d.height() <= room
    assert d.browser.minimumHeight() > squeezed + 50


def test_the_list_gets_its_own_floor_back_when_there_is_room(qtbot):
    """The clamp lowers the frame list's floor only while the screen is short
    of it; once the content fits again the list's own minimum returns."""
    room = _minimum_with_the_help_folded(qtbot) + 5
    d, _settings = _short_stack(qtbot, room)
    d.options_band.set_folded(True)
    d.options_band.set_folded(False)       # by hand
    d._toggle_hints()                      # help on: more than the room
    qtbot.wait(50)
    assert 0 < d.browser.minimumHeight()
    d._toggle_hints()                      # help off: fits again
    qtbot.wait(50)
    assert d.browser.minimumHeight() == 0
    assert d.height() <= room


def test_after_the_users_toggle_a_grade_still_stays_on_the_screen(qtbot):
    """Once the user has toggled the band, the screen folds nothing -- but a
    grade's extra lines must not carry the window past the bottom either
    (834 px on a 648 px screen before the clamp)."""
    room = _minimum_with_the_help_folded(qtbot) + 5
    d, _settings = _short_stack(qtbot, room)
    assert not d.options_band.is_folded()
    d.options_band.set_folded(True)
    d.options_band.set_folded(False)       # by hand: the screen is out of it
    d._on_graded(_session())
    qtbot.wait(50)
    assert not d.options_band.is_folded()
    assert d.height() <= room, f"{d.height()} px on a {room} px screen"


# --- the Verdict column (Ruling R4 b) and the scrollbar (R4 c) ---

def _verdict_on_screen(d) -> bool:
    v = d.browser.view
    hdr = v.horizontalHeader()
    left = hdr.sectionViewportPosition(COL_VERDICT)
    width = hdr.sectionSize(COL_VERDICT)
    return (not v.horizontalScrollBar().isVisible()
            and left >= 0 and left + width <= v.viewport().width()
            # its header readable, not squeezed to a sliver
            and width >= hdr.sectionSizeHint(COL_VERDICT))


@pytest.mark.parametrize("cls", [StackDialog, HaOIIIDialog])
@pytest.mark.parametrize("size", SIZES)
def test_every_column_is_on_screen_verdict_included(qtbot, cls, size):
    """The mockup shows every column with the preview taking the rest. At
    1280 the list's cap put Bg and Verdict behind a scrollbar under cocoa,
    because Qt reserved a sort arrow's width in all seven headers."""
    d = _open(qtbot, cls, size)
    qtbot.waitUntil(lambda: _verdict_on_screen(d), timeout=2000)
    lst, pv = d.browser.splitter.sizes()
    assert pv > lst


@pytest.mark.parametrize("cls", [StackDialog, HaOIIIDialog])
def test_every_column_is_on_screen_at_the_width_it_opens(qtbot, cls):
    """What he actually sees on the laptop: the dialog's own opening width,
    not a resize a test chose."""
    d = cls(Settings(frame_options_folded=False))
    qtbot.addWidget(d)
    if cls is StackDialog:
        d._available_height = lambda: 4000
    d.show()
    qtbot.waitExposed(d)
    d._on_graded(_session())
    qtbot.waitUntil(lambda: _verdict_on_screen(d), timeout=2000)
    lst, pv = d.browser.splitter.sizes()
    assert pv > lst


@pytest.mark.parametrize("cls", [StackDialog, HaOIIIDialog])
@pytest.mark.parametrize("size", SIZES)
def test_the_chart_sits_under_the_list_at_every_size(qtbot, cls, size):
    d = _open(qtbot, cls, size)
    b = d.browser
    assert b.chart.isVisible() and _chart_within_dialog(d, b.chart)
    view_bottom = b.view.mapTo(d, b.view.rect().bottomLeft()).y()
    assert b.chart.mapTo(d, b.chart.rect().topLeft()).y() > view_bottom
    lst, pv = b.splitter.sizes()
    assert pv > lst, "the chart widened the list"


def test_the_sorted_column_gets_room_for_its_arrow(qtbot):
    """Only the sorted column reserves the arrow — so sorting by another
    column must hand the room over, or its header would be cut."""
    from nocturne.ui.frame_browser import COL_FWHM
    d = _open(qtbot, StackDialog, (1280, 800))
    hdr = d.browser.view.horizontalHeader()
    fwhm = hdr.sectionSize(COL_FWHM)
    d.browser.view.sortByColumn(COL_FWHM, Qt.SortOrder.AscendingOrder)
    qtbot.waitUntil(lambda: hdr.sectionSize(COL_FWHM) > fwhm + 10
                    and hdr.sectionSize(COL_FWHM) >= hdr.sectionSizeHint(COL_FWHM),
                    timeout=2000)
    qtbot.waitUntil(lambda: _verdict_on_screen(d), timeout=2000)


def test_a_horizontal_scrollbar_is_as_dark_as_the_vertical_one(qtbot):
    """If the list is dragged narrow a horizontal bar appears; unstyled it was
    the platform's light box (lightness 191 cocoa, 255 offscreen, against 65
    for the themed vertical one)."""
    from PySide6.QtGui import QColor
    d = _open(qtbot, StackDialog, (1280, 800))
    d.browser.splitter.setSizes([150, 1100])
    hsb, vsb = d.browser.view.horizontalScrollBar(), d.browser.view.verticalScrollBar()
    qtbot.waitUntil(lambda: hsb.isVisible() and vsb.isVisible(), timeout=2000)

    def brightest(bar):
        img = bar.grab().toImage()
        return max(QColor(img.pixel(x, y)).lightness()
                   for x in range(img.width()) for y in range(img.height()))

    assert brightest(hsb) <= brightest(vsb) + 10
    assert hsb.height() == vsb.width()


def test_haoiii_fits_the_1280x800_laptop_with_the_options_open(qtbot):
    """Ha/OIII has no explanations to fold and no screen fit of its own: it
    relies on needing less than the floor (633 px offscreen, 688 cocoa,
    against 740). If it ever outgrows that, it needs Stack's fit."""
    d = HaOIIIDialog(Settings(frame_options_folded=False))
    qtbot.addWidget(d)
    d.show()
    qtbot.waitExposed(d)
    d._on_graded(_session())
    qtbot.wait(50)
    assert not d.options_band.is_folded()
    assert d.minimumSizeHint().height() <= 740
    assert d.height() <= 740, f"opens {d.height()} px tall"
    assert d.browser.chart.isVisible(), "Ha/OIII lost the shared chart"


# --- the output fields fill their row (Ruling R5) ---

class _FieldsStayAtSizeHint(QProxyStyle):
    """What the macOS style tells a QFormLayout: fields stay at their size
    hint. Offscreen's Fusion lets them grow, so without this the tests below
    would pass against the bug."""

    def styleHint(self, hint, option=None, widget=None, data=None):
        if hint == QStyle.StyleHint.SH_FormLayoutFieldGrowthPolicy:
            return QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint.value
        return super().styleHint(hint, option, widget, data)


def _open_mac_form(qtbot, cls, size):
    d = cls(Settings(frame_options_folded=False))
    qtbot.addWidget(d)
    d._mac_style = _FieldsStayAtSizeHint(QStyleFactory.create("Fusion"))
    d.setStyle(d._mac_style)
    if cls is StackDialog:
        d._available_height = lambda: 4000
    d.resize(*size)
    d.show()
    qtbot.waitExposed(d)
    d._on_graded(_session())
    qtbot.wait(20)
    return d


def _shows_whole(edit) -> bool:
    return edit.fontMetrics().horizontalAdvance(edit.text()) + 16 <= edit.width()


@pytest.mark.parametrize("cls, field", [(StackDialog, "name_edit"),
                                        (HaOIIIDialog, "output_edit")])
def test_the_output_field_fills_its_row(qtbot, cls, field):
    typical = {"name_edit": None,
               "output_edit": "/Users/andreas/Astro/SH2-108/SH2-108_190x10s_32min_HaOIII.fits"}
    widths = {}
    for size in SIZES:
        d = _open_mac_form(qtbot, cls, size)
        edit = getattr(d, field)
        if typical[field]:
            edit.setText(typical[field])
        widths[size[0]] = edit.width()
        if size[0] == 1280:
            assert len(edit.text()) >= len("SH2-108_190x10s_32min.fits"), edit.text()
            assert _shows_whole(edit), (
                f"{field} {edit.width()} px cuts {edit.text()!r} at 1280")
        d.close()
    assert widths[1920] > widths[1280], widths
