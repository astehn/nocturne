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
