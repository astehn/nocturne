"""H.264 MP4 writer for the Share video, via PyAV (libx264 ships in the wheel).

Writes to `<path>.part` and renames on success, so a cancelled or failed
encode never leaves a truncated file and never clobbers an existing one.
"""
from __future__ import annotations

import os
from typing import Callable, Iterable

import numpy as np

from nocturne.core.tasks import CancelToken


_BT709 = "ITU709"
_TV = "MPEG"


def encode_mp4(frames: Iterable[np.ndarray], path: str, size: tuple[int, int],
               fps: int = 30, *, total: int | None = None,
               token: CancelToken | None = None,
               on_progress: Callable[[int, int], None] | None = None) -> None:
    """Encode RGB uint8 (h, w, 3) frames as H.264 / yuv420p.

    `size` is (width, height). Any exception, `Cancelled` included (it is a
    BaseException, so this catches BaseException), closes the container,
    removes the `.part` file and re-raises.
    """
    import av

    part = path + ".part"
    width, height = size
    container = None
    try:
        container = av.open(part, mode="w", format="mp4",
                            options={"movflags": "+faststart"})
        stream = container.add_stream("libx264", rate=fps)
        stream.width, stream.height = width, height
        stream.pix_fmt = "yuv420p"
        # Convert AND tag BT.709 limited range. swscale's untagged default is
        # BT.601, which players do not assume for HD, so colours would shift.
        cc = stream.codec_context
        cc.colorspace = av.video.reformatter.Colorspace.ITU709
        cc.color_primaries = av.video.reformatter.ColorPrimaries.BT709
        cc.color_trc = av.video.reformatter.ColorTrc.BT709
        cc.color_range = av.video.reformatter.ColorRange.MPEG
        stream.options = {"crf": "18", "preset": "medium"}
        for i, arr in enumerate(frames):
            if token is not None:
                token.check()
            frame = av.VideoFrame.from_ndarray(np.ascontiguousarray(arr),
                                               format="rgb24")
            frame = frame.reformat(format="yuv420p",
                                   dst_colorspace=_BT709, dst_color_range=_TV)
            for packet in stream.encode(frame):
                container.mux(packet)
            if on_progress is not None and total is not None:
                on_progress(i + 1, total)
        for packet in stream.encode():
            container.mux(packet)
        container.close()
        container = None
        os.replace(part, path)
    except BaseException:
        if container is not None:
            try:
                container.close()
            except Exception:                     # noqa: BLE001 - cleanup only
                pass
        try:
            os.remove(part)
        except OSError:
            pass
        raise


def _name(enum, value) -> str:
    try:
        return enum(int(value)).name
    except ValueError:
        return str(value)


def probe(path: str) -> dict:
    """Read an MP4 back: codec, size, pixel format, frame count, duration."""
    import av

    with av.open(path) as c:
        s = c.streams.video[0]
        frames = sum(1 for _ in c.decode(s))
        cc = s.codec_context
        dur = float(c.duration / av.time_base) if c.duration else 0.0
        from av.video import reformatter as r
        return {"colorspace": _name(r.Colorspace, cc.colorspace),
                "primaries": _name(r.ColorPrimaries, cc.color_primaries),
                "trc": _name(r.ColorTrc, cc.color_trc),
                "range": _name(r.ColorRange, cc.color_range),
                "codec": cc.name, "width": cc.width, "height": cc.height,
                "pix_fmt": cc.pix_fmt, "frames": frames, "duration": dur}
