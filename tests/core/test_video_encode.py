import os

import numpy as np
import pytest

from nocturne.core.tasks import CancelToken, Cancelled
from nocturne.core.video_encode import encode_mp4, probe


def _frames(n, w=64, h=96):
    for i in range(n):
        f = np.zeros((h, w, 3), np.uint8)
        f[:, : (i * 4) % w, 1] = 255
        yield f


def test_encodes_h264_yuv420p(tmp_path):
    p = str(tmp_path / "v.mp4")
    encode_mp4(_frames(30), p, (64, 96))
    info = probe(p)
    assert (info["codec"], info["pix_fmt"], info["width"], info["height"]) == (
        "h264", "yuv420p", 64, 96)
    assert info["frames"] == 30 and info["duration"] == pytest.approx(1.0, abs=0.05)
    assert not os.path.exists(p + ".part")


def test_progress_reports_every_frame(tmp_path):
    seen = []
    encode_mp4(_frames(10), str(tmp_path / "v.mp4"), (64, 96), total=10,
               on_progress=lambda d, t: seen.append((d, t)))
    assert seen[0] == (1, 10) and seen[-1] == (10, 10) and len(seen) == 10


def test_cancel_leaves_no_file(tmp_path):
    p = str(tmp_path / "v.mp4")
    tok = CancelToken()

    # x264 buffers ~40 frames before the muxer writes a byte, so cancelling
    # early leaves nothing on disk to clean up and proves nothing. Cancel past
    # that, where a .part file really exists.
    def frames():
        for i, f in enumerate(_frames(90)):
            if i == 70:
                tok.cancel()
            yield f

    with pytest.raises(Cancelled):
        encode_mp4(frames(), p, (64, 96), token=tok)
    assert not os.path.exists(p) and not os.path.exists(p + ".part")


def test_failure_keeps_an_existing_file_untouched(tmp_path):
    p = tmp_path / "v.mp4"
    p.write_bytes(b"old")

    def bad():
        for f in _frames(70):                     # past x264's buffering
            yield f
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        encode_mp4(bad(), str(p), (64, 96))
    assert p.read_bytes() == b"old"
    assert not os.path.exists(str(p) + ".part")


def test_colour_is_bt709_tagged_and_round_trips(tmp_path):
    """Convert and tag must agree, or phones shift the colours."""
    import av

    patch = np.zeros((96, 64, 3), np.uint8)
    patch[:48] = (200, 60, 30)
    patch[48:] = (128, 128, 128)
    p = str(tmp_path / "c.mp4")
    encode_mp4([patch] * 5, p, (64, 96))
    info = probe(p)
    assert (info["colorspace"], info["primaries"], info["trc"], info["range"]) == (
        "ITU709", "BT709", "BT709", "MPEG")
    with av.open(p) as c:
        fr = next(c.decode(video=0))
        rgb = fr.reformat(format="rgb24", src_colorspace="ITU709",
                          src_color_range="MPEG").to_ndarray()
    for y, want in ((24, (200, 60, 30)), (72, (128, 128, 128))):
        got = rgb[y, 32].astype(int)
        assert np.abs(got - np.array(want)).max() <= 4, (got, want)
