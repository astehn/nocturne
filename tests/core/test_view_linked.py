"""The linear preview's stretch is a VIEW preference the caller chooses.

Why it exists: Nocturne's import view leaves a uniform red cast on Andreas's
IC 1396A, because red's distribution is 2.67x wider than green's and one shared
curve spreads it furthest in both directions. An unlinked stretch normalises each
channel instead, which is what AstroWizard shows and what he wanted to see. It is
a view — nothing is committed — so the choice is a keyword, defaulting to today's
behaviour so no existing call site changes.
"""
import numpy as np

from nocturne.core.autostretch import autostretch, neutral_stretch, unlinked_stretch
from nocturne.core.export import display_data
from nocturne.core.image import AstroImage


def _linear():
    """Red given the wider spread, as on the real data. Channels that commute
    cannot tell the two stretches apart."""
    rng = np.random.default_rng(1)
    d = np.clip(rng.normal(0.02, 0.005, (64, 48, 3)), 0, 1).astype(np.float32)
    d[..., 0] = np.clip(0.02 + (d[..., 0] - 0.02) * 2.67, 0, 1)
    return AstroImage(d, is_linear=True)


def test_the_view_switch_reaches_the_pixels():
    img = _linear()
    assert np.array_equal(autostretch(img, linked=False), unlinked_stretch(img.data))
    assert np.array_equal(autostretch(img), neutral_stretch(img.data))


def test_the_two_views_actually_differ():
    img = _linear()
    assert not np.allclose(autostretch(img, linked=True),
                           autostretch(img, linked=False))


def test_display_data_carries_it_so_a_linear_export_matches_the_screen():
    """display_data serves BOTH the canvas and an export of still-linear data —
    that is the whole reason it exists (see its docstring). If the keyword
    stopped short of it, the file and the screen would silently disagree, which
    is the exact bug display_data was written to prevent."""
    img = _linear()
    assert np.array_equal(display_data(img, linked=False),
                          autostretch(img, linked=False))
    assert np.array_equal(display_data(img), autostretch(img))


def test_the_preference_is_NOT_global_state():
    """Captured and asserted UNCHANGED, per CLAUDE.md.

    The realistic way a measurement starts moving with a view preference is a
    module-level default: someone stores the choice on the module so callers
    need not thread it, and every metric silently follows the canvas. Rendering
    unlinked must leave the default render bit-identical.
    """
    img = _linear()
    before = np.array(autostretch(img), copy=True)
    autostretch(img, linked=False)
    assert np.array_equal(autostretch(img), before)


def test_a_measurement_does_not_follow_the_canvas():
    """`metrics._display` is the one measurement path that autostretches. It
    must keep the default: a step's reported delta is a fact about the edit, not
    about how the user happens to be looking at it.

    (`core.histogram` needs no such guard — it reads raw data by design and says
    so in its docstring.)

    Asserted as "the metric renders LINKED", not merely "the metric does not
    move": a metric hard-wired to the wrong stretch never moves either, and an
    earlier version of this test passed with exactly that bug in place.
    """
    from nocturne.core.metrics import _display, rms_delta

    img = _linear()
    assert np.array_equal(_display(img), autostretch(img, linked=True))

    a, b = _linear(), _linear()
    b.data[10:20, 10:20] += 0.01
    before = rms_delta(a, b)
    autostretch(a, linked=False)          # flip the view...
    assert rms_delta(a, b) == before      # ...the measurement does not move
