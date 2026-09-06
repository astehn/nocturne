"""Window sizing at startup.

Two hardcoded defaults were wrong in a row. 1280 shipped for months and left 16
of 27 toolbar items behind the overflow chevron; 1600 and 1760 came from
measuring the toolbar on the OFFSCREEN platform, which substitutes fonts and
reports 1698 where the real app needs 2340. Andreas found both by opening the
app. The width is asked of the window now, so there is no number left to get
wrong.
"""
import pytest

from nocturne.__main__ import (DEFAULT_HEIGHT, fit_to_screen, preferred_size,
                               window_size)


class _Geom:
    def __init__(self, w, h): self._w, self._h = w, h
    def width(self): return self._w
    def height(self): return self._h


class _Screen:
    def __init__(self, w, h): self._g = _Geom(w, h)
    def availableGeometry(self): return self._g


class _App:
    def __init__(self, screen): self._s = screen
    def primaryScreen(self): return self._s


class _Win:
    """Stands in for MainWindow: only sizeHint().width() is consulted."""
    def __init__(self, hint_w): self._w = hint_w
    def sizeHint(self): return _Geom(self._w, 400)


# --- the --size override -------------------------------------------------

def test_no_flag_means_no_override():
    assert window_size(["nocturne"]) is None


def test_parses_a_size():
    assert window_size(["nocturne", "--size", "1600x1000"]) == (1600, 1000)


def test_case_insensitive():
    assert window_size(["nocturne", "--size", "1600X1000"]) == (1600, 1000)


@pytest.mark.parametrize("bad", ["junk", "1600", "1600x", "x1000", "16 00x1000"])
def test_a_typo_falls_back_rather_than_raising(bad):
    """A bad flag must not stop the app opening."""
    assert window_size(["nocturne", "--size", bad]) is None


def test_flag_with_no_value():
    assert window_size(["nocturne", "--size"]) is None


def test_floor_keeps_the_window_usable():
    assert window_size(["nocturne", "--size", "10x10"]) == (640, 480)


# --- fitting to the screen ------------------------------------------------

def test_a_big_screen_gets_the_asked_for_size():
    assert fit_to_screen((1760, 1040), _App(_Screen(3840, 2160))) == (1760, 1040)


def test_a_small_screen_is_not_overflowed():
    """A 1280x800 Air must get a window that fits its display."""
    assert fit_to_screen((2400, 1200), _App(_Screen(1280, 800))) == (1280, 800)


def test_fitting_only_ever_shrinks():
    assert fit_to_screen((800, 600), _App(_Screen(3840, 2160))) == (800, 600)


def test_no_screen_is_not_a_crash():
    assert fit_to_screen((1760, 1040), _App(None)) == (1760, 1040)


# --- the derived default --------------------------------------------------

def test_the_default_width_comes_from_the_window_not_a_constant():
    """The whole point: a wider layout gets a wider window, with no edit here.

    A hardcoded default cannot do this, which is how 1280 outlived the toolbar
    growing to 27 items.
    """
    app = _App(_Screen(3840, 2160))
    narrow = preferred_size(_Win(1200), app)[0]
    wide = preferred_size(_Win(2340), app)[0]
    assert wide - narrow == 2340 - 1200


def test_the_default_clears_the_layout_it_was_given():
    """It must be at least as wide as the window asked for — a default one point
    short puts the last toolbar item behind the chevron."""
    w, _ = preferred_size(_Win(2340), _App(_Screen(3840, 2160)))
    assert w >= 2340


def test_the_default_is_still_clamped_to_a_small_screen():
    w, h = preferred_size(_Win(2340), _App(_Screen(1280, 800)))
    assert (w, h) == (1280, 800)


def test_height_is_the_declared_default_on_a_roomy_screen():
    assert preferred_size(_Win(2340), _App(_Screen(3840, 2160)))[1] == DEFAULT_HEIGHT
