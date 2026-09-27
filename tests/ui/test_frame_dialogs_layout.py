"""Layout A holds at the sizes that matter, in both dialogs, under the real
stylesheet (spec 2026-09-27 §2.4.7, §7): the preview is wider than the list,
the divider is easy to hit, no explanation is cut, and the options fold.

Offscreen fonts differ from cocoa, so these assert RELATIONS (preview wider
than list, nothing clipped), never pixel values.
"""
from datetime import datetime, timedelta, timezone

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from nocturne.settings import Settings
from nocturne.stacking.grade import FrameStats
from nocturne.ui.frame_browser import COL_VERDICT
from nocturne.ui.haoiii_dialog import HaOIIIDialog
from nocturne.ui.option_band import WrappedNote
from nocturne.ui.stack_dialog import StackDialog
from nocturne.ui.theme import build_stylesheet

SIZES = [(1280, 800), (1920, 1080)]
T0 = datetime(2026, 9, 21, 20, 0, tzinfo=timezone.utc)


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
    d = cls(Settings())
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


def test_stack_fits_the_1280x800_laptop_with_the_help_on(qtbot):
    """The floor this app targets: 800 px of screen, 740 of it usable
    (_available_height's own margin). With the explanations on, the band is
    taller than the old form; _fit_to_content must still land the dialog on
    the screen — by folding the explanations, as it did before layout A —
    with the preview at its minimum or better, and without folding the
    options when folding the explanations was enough."""
    settings = Settings()
    settings.help_expanded = True
    d = StackDialog(settings)
    qtbot.addWidget(d)
    d._available_height = lambda: 740
    d.resize(1280, 700)
    d.show()
    qtbot.waitExposed(d)
    d._on_graded(_session())
    assert d.height() <= 740, f"{d.height()} px on a 740 px screen"
    assert d.preview.height() >= 220
    assert not d.options_band.is_folded(), (
        "folded the options although folding the explanations was enough")
    assert settings.help_expanded is True, "the screen must not rewrite the preference"


def _minimum_with_the_help_folded(qtbot, graded=False) -> int:
    """What the dialog needs with the explanations folded and the options
    open — measured, not hard-coded: it is 643 px offscreen and 688 under
    cocoa (766 graded), so any fixed screen height tests one font only."""
    settings = Settings()
    settings.help_expanded = False
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
    settings = Settings()
    settings.help_expanded = True
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
    assert settings.help_expanded is True


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
    """Asking for the explanations on a short screen gets them — and the
    options the screen folded come back with them — and nothing folds them
    away again behind the user's back."""
    room = _minimum_with_the_help_folded(qtbot) - 1
    d, settings = _short_stack(qtbot, room)
    assert d.options_band.is_folded() and d._band_forced_folded
    d._toggle_hints()                      # the screen had them folded: show
    d._toggle_hints()
    assert not d.options_band.is_folded(), "the screen's fold outlived the click"
    qtbot.wait(50)
    assert d.mosaic_hint.isVisible(), "folded away again behind the user's back"
    assert not d.options_band.is_folded(), "re-folded behind the user's back"
    assert settings.frame_options_folded is False


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
    assert not d._band_forced_folded


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
    d = cls(Settings())
    qtbot.addWidget(d)
    if cls is StackDialog:
        d._available_height = lambda: 4000
    d.show()
    qtbot.waitExposed(d)
    d._on_graded(_session())
    qtbot.waitUntil(lambda: _verdict_on_screen(d), timeout=2000)
    lst, pv = d.browser.splitter.sizes()
    assert pv > lst


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
    d = HaOIIIDialog(Settings())
    qtbot.addWidget(d)
    d.show()
    qtbot.waitExposed(d)
    d._on_graded(_session())
    qtbot.wait(50)
    assert not d.options_band.is_folded()
    assert d.minimumSizeHint().height() <= 740
    assert d.height() <= 740, f"opens {d.height()} px tall"
