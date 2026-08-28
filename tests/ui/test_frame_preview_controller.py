import pytest

pytest.importorskip("PySide6")
import numpy as np  # noqa: E402
from PySide6.QtCore import QThreadPool  # noqa: E402

from nocturne.ui.frame_preview import FramePreview  # noqa: E402
from nocturne.ui.frame_preview_controller import (  # noqa: E402
    PREVIEW_CACHE_LIMIT, FramePreviewController,
)


def _ctl(qtbot, paths):
    preview = FramePreview()
    qtbot.addWidget(preview)
    ctl = FramePreviewController(
        preview, QThreadPool.globalInstance(),
        lambda row: paths[row] if 0 <= row < len(paths) else None)
    ctl.loader = lambda p: np.zeros((8, 8, 3), np.float32)
    return ctl


def test_a_late_load_for_a_row_you_left_does_not_replace_the_one_you_are_on(qtbot):
    """Full-res subs take real time to decode. Click a slow frame, then click
    another, and the first one's result arrives last — without the guard it wins
    and you are looking at a frame you did not select. Neither dialog covered
    this; both share the guard, so test it once here.
    """
    ctl = _ctl(qtbot, ["/slow.fit", "/fast.fit"])
    shown = []
    ctl.preview.show_image = lambda img: shown.append(img)

    ctl.wanted = "/fast.fit"                                  # user moved on
    ctl._on_loaded(("/slow.fit", np.zeros((8, 8, 3), np.float32)))
    assert shown == [], "a result for a row the user has left must not be shown"

    ctl._on_loaded(("/fast.fit", np.zeros((8, 8, 3), np.float32)))
    assert len(shown) == 1, "the row the user is actually on must still show"


def test_a_failure_for_a_row_you_left_is_not_reported_either(qtbot):
    """Same guard, the other branch: an unreadable frame you have already
    clicked away from must not replace a good preview with an error."""
    ctl = _ctl(qtbot, ["/bad.fit", "/good.fit"])
    messages = []
    ctl.preview.show_message = lambda text: messages.append(text)

    ctl.wanted = "/good.fit"
    ctl._on_error("/bad.fit", OSError("unreadable"))
    assert messages == [], "a stale failure must not overwrite the current preview"

    ctl._on_error("/good.fit", OSError("unreadable"))
    assert len(messages) == 1, "a failure on the current row must be reported"


def test_the_cache_is_capped_and_evicts_least_recently_used(qtbot):
    """Full-res QImages are ~24 MB each, so the cap is what keeps a long grading
    session from growing without bound."""
    paths = [f"/f{i}.fit" for i in range(PREVIEW_CACHE_LIMIT + 2)]
    ctl = _ctl(qtbot, paths)
    for p in paths[:PREVIEW_CACHE_LIMIT]:
        ctl.wanted = p
        ctl._on_loaded((p, np.zeros((8, 8, 3), np.float32)))
    assert len(ctl.cache) == PREVIEW_CACHE_LIMIT

    ctl.show_row(0)                       # touch the oldest, making it newest
    ctl.wanted = paths[PREVIEW_CACHE_LIMIT]
    ctl._on_loaded((paths[PREVIEW_CACHE_LIMIT], np.zeros((8, 8, 3), np.float32)))
    assert paths[0] in ctl.cache, "the touched entry must survive — LRU, not FIFO"
    assert paths[1] not in ctl.cache, "the genuinely least-recent one goes"
