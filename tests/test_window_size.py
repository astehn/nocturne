from nocturne.__main__ import window_size, DEFAULT_WINDOW

def test_default_when_absent():
    assert window_size(["nocturne"]) == DEFAULT_WINDOW

def test_parses_a_size():
    assert window_size(["nocturne", "--size", "1600x1000"]) == (1600, 1000)

def test_case_insensitive():
    assert window_size(["nocturne", "--size", "1600X1000"]) == (1600, 1000)

def test_bad_value_falls_back_rather_than_raising():
    # A typo must not stop the app opening.
    for bad in ("junk", "1600", "1600x", "x1000", "16 00x1000"):
        assert window_size(["nocturne", "--size", bad]) == DEFAULT_WINDOW

def test_flag_with_no_value():
    assert window_size(["nocturne", "--size"]) == DEFAULT_WINDOW

def test_floor_keeps_the_window_usable():
    assert window_size(["nocturne", "--size", "10x10"]) == (640, 480)


class _Screen:
    def __init__(self, w, h): self._w, self._h = w, h
    def availableGeometry(self):
        class G:
            def __init__(s, w, h): s._w, s._h = w, h
            def width(s): return s._w
            def height(s): return s._h
        return G(self._w, self._h)


class _App:
    def __init__(self, screen): self._s = screen
    def primaryScreen(self): return self._s


def test_default_clears_the_toolbar():
    """The main toolbar wants 1698 points. A default below that hides most of
    the tools behind an overflow chevron, which is what 1280 did."""
    from nocturne.__main__ import DEFAULT_WINDOW
    assert DEFAULT_WINDOW[0] >= 1698


def test_a_big_screen_gets_the_preferred_size():
    from nocturne.__main__ import fit_to_screen
    assert fit_to_screen((1760, 1040), _App(_Screen(3840, 2160))) == (1760, 1040)


def test_a_small_screen_is_not_overflowed():
    """A 1280x800 Air must get a window that fits its display."""
    from nocturne.__main__ import fit_to_screen
    assert fit_to_screen((1760, 1040), _App(_Screen(1280, 800))) == (1280, 800)


def test_fitting_only_ever_shrinks():
    from nocturne.__main__ import fit_to_screen
    assert fit_to_screen((800, 600), _App(_Screen(3840, 2160))) == (800, 600)


def test_no_screen_is_not_a_crash():
    from nocturne.__main__ import fit_to_screen
    assert fit_to_screen((1760, 1040), _App(None)) == (1760, 1040)
