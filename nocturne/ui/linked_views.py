"""Two ImageViews that zoom and pan together — Upscale Crop's side by side.

Both images have identical dimensions, so following is a plain copy of the
transform and the scroll position; there is no coordinate mapping to get wrong.
"""
from __future__ import annotations


def copy_view(src, dst) -> None:
    dst.setTransform(src.transform())
    dst.horizontalScrollBar().setValue(src.horizontalScrollBar().value())
    dst.verticalScrollBar().setValue(src.verticalScrollBar().value())
    dst._fitted = src._fitted          # a resize must treat both alike
    dst._note_zoom()                   # its zoom pill and readout follow


def link_views(a, b):
    busy = [False]

    def follow(src, dst):
        if busy[0]:
            return
        busy[0] = True
        try:
            copy_view(src, dst)
        finally:
            busy[0] = False

    fa = lambda: follow(a, b)          # noqa: E731
    fb = lambda: follow(b, a)          # noqa: E731
    a.viewChanged.connect(fa)
    b.viewChanged.connect(fb)

    def unlink():
        a.viewChanged.disconnect(fa)
        b.viewChanged.disconnect(fb)
    return unlink
