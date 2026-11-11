import numpy as np
import pytest

from collections import deque

from nocturne.core.share_video import (
    DEFAULT_WORDMARK,
    TIMELINE,
    WORDMARK_URL,
    Timeline,
    end_card,
    frame_spec,
    render_frames,
    video_size,
)

# A one-second timeline whose last frame shows the end card fully faded in:
# the full 315 frames at 1080x1920 held in a list were ~2 GB per test.
SHORT = Timeline(hook=.1, before=.1, wipe=.1, end=.7)


def _last(frames):
    return deque(frames, maxlen=1)[0]


def test_timeline_totals():
    assert TIMELINE.total == pytest.approx(10.5)
    assert TIMELINE.frame_count == 315


@pytest.mark.parametrize("t,phase", [(0.0, "hook"), (1.19, "hook"), (1.2, "before"),
                                     (2.49, "before"), (2.5, "wipe"), (6.99, "wipe"), (7.0, "end")])
def test_phase_boundaries(t, phase):
    assert frame_spec(t).phase == phase


def test_wipe_is_eased_and_monotonic():
    xs = [frame_spec(2.5 + 4.5 * k / 20).wipe for k in range(21)]
    assert xs[0] == pytest.approx(0.0) and xs[-1] == pytest.approx(1.0, abs=1e-6)
    assert all(b >= a for a, b in zip(xs, xs[1:]))
    assert frame_spec(2.5 + 4.5 * 0.25).wipe == pytest.approx(0.15625)   # smoothstep(0.25)


def test_label_and_end_alphas():
    assert frame_spec(1.2 + 0.15).label_alpha == pytest.approx(0.5)
    assert frame_spec(2.5 + 0.2).label_alpha == pytest.approx(0.5)
    assert frame_spec(3.0).label_alpha == 0.0
    assert frame_spec(7.0 + 0.3).end_alpha == pytest.approx(0.5)
    assert frame_spec(0.5).end_alpha == 0.0


def test_zoom_runs_1_to_1_08():
    assert frame_spec(0.0).zoom == pytest.approx(1.0)
    assert frame_spec(10.5).zoom == pytest.approx(1.08)


@pytest.mark.parametrize("wm,url", [("NOCTURNE", WORDMARK_URL), ("  nocturne ", WORDMARK_URL),
                                    ("@andreas", ""), ("", "")])
def test_end_card_url_only_for_default(wm, url):
    assert end_card("NGC 7000", "54 min", wm).url == url


def test_end_card_fields_stripped():
    c = end_card("  NGC 7000 ", " 54 min  ", " @a ")
    assert (c.title, c.credit, c.wordmark) == ("NGC 7000", "54 min", "@a")
    assert DEFAULT_WORDMARK == "NOCTURNE"


@pytest.mark.parametrize("cw,ch,out", [(1399, 2488, (1080, 1920)), (2488, 1991, (1350, 1080)),
                                       (1000, 1000, (1080, 1080)), (1991, 2488, (1080, 1350))])
def test_video_size_even_short_side_1080(cw, ch, out):
    w, h = video_size(cw, ch)
    assert (w, h) == out and w % 2 == 0 and h % 2 == 0


def _pair(h=64, w=36):
    before = np.zeros((h, w, 3), np.uint8); before[..., 2] = 200       # blue
    after = np.zeros((h, w, 3), np.uint8); after[..., 0] = 200          # red
    return before, after


def test_frames_count_and_shape():
    b, a = _pair()
    frames = list(render_frames(b, a, end_card("", "", ""), (36, 64)))
    assert len(frames) == 315 and frames[0].shape == (64, 36, 3) and frames[0].dtype == np.uint8


def test_mid_wipe_after_left_before_right():
    b, a = _pair()
    frames = list(render_frames(b, a, end_card("", "", ""), (36, 64)))
    f = frames[round((2.5 + 4.5 * 0.5) * 30)]               # wipe 0.5
    assert f[32, 4, 0] > 150 and f[32, 4, 2] < 50            # left: after (red)
    assert f[32, 31, 2] > 150 and f[32, 31, 0] < 50          # right: before (blue)


def test_hook_is_after_and_before_phase_is_before():
    b, a = _pair()
    frames = list(render_frames(b, a, end_card("", "", ""), (36, 64)))
    assert frames[10][40, 18, 0] > 150                      # hook: after
    assert frames[50][40, 18, 2] > 150                      # before phase (label is top 1/8)


def test_shape_mismatch_raises():
    b, a = _pair()
    with pytest.raises(ValueError):
        next(render_frames(b, a[:-1], end_card("", "", ""), (36, 64)))


def test_short_timeline_ends_on_the_full_card():
    assert frame_spec((SHORT.frame_count - 1) / SHORT.fps, SHORT).end_alpha == 1.0


def test_end_card_draws_text_only_when_present():
    b, a = _pair(1920, 1080)
    blank = _last(render_frames(b, a, end_card("", "", ""), (1080, 1920), SHORT))
    text = _last(render_frames(b, a, end_card("NGC 7000", "54 min", "NOCTURNE"),
                               (1080, 1920), SHORT))
    assert not np.array_equal(blank, text)
    # the card lives in the bottom gradient: the top half is untouched
    assert np.array_equal(blank[:960], text[:960])
    # bottom gradient darkens even with no text
    assert blank[1900, 540, 0] < a[1900, 540, 0]


_LONG = "Andreas Stehn Astrophotography"          # 30 characters, 1520 px unfitted


@pytest.mark.parametrize("title,credit,wordmark", [
    ("", "", _LONG),
    ("", "Seestar S30 Pro · 312 × 20 s · 1 h 44 min · Bortle 1 · Starfront Observatories", ""),
    ("NGC 7000 · North America Nebula, Pelican Nebula and the Cygnus Wall in Hα and OIII",
     "", ""),
    ("NGC 7000 · North America Nebula and the Pelican Nebula",
     "Seestar S30 Pro · 312 × 20 s · 1 h 44 min · Bortle 1 · Starfront Observatories", _LONG),
])
def test_long_card_text_stays_inside_the_frame(title, credit, wordmark):
    """Every line is shrunk to fit inside a 40 px margin, so the outermost
    columns of the last frame are exactly the blank card's."""
    b, a = _pair(1920, 1080)
    blank = _last(render_frames(b, a, end_card("", "", ""), (1080, 1920), SHORT))
    text = _last(render_frames(b, a, end_card(title, credit, wordmark), (1080, 1920), SHORT))
    assert not np.array_equal(blank, text)
    assert np.array_equal(blank[:, :6], text[:, :6])
    assert np.array_equal(blank[:, -6:], text[:, -6:])


def test_a_short_wordmark_keeps_its_full_size():
    """Fitting only ever shrinks: NOCTURNE is drawn as tuned in the spike."""
    from nocturne.core.share_video import _fit
    assert _fit("NOCTURNE", 64, 300, 1000, 0.35).size == 64
    assert _fit(_LONG, 64, 300, 1000, 0.35).size < 64
