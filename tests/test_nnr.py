import json
import os
import struct

from nocturne.core import nnr


def _write(path, header: dict, fmt=1, hlen=None):
    raw = json.dumps(header).encode()
    with open(path, "wb") as f:
        f.write(b"NNR1" + struct.pack("<HHI", fmt, 1, len(raw) if hlen is None else hlen))
        f.write(raw + os.urandom(200))


def test_reads_header_fields(tmp_path):
    p = tmp_path / "m.nnr"
    _write(p, {"id": "abc", "contract": 1})
    h = nnr.read_header(str(p))
    assert h["id"] == "abc" and h["contract"] == 1


def test_not_nnr_is_none(tmp_path):
    p = tmp_path / "m.nnr"
    p.write_bytes(b"\x08\x07onnx" + os.urandom(100))
    assert nnr.read_header(str(p)) is None


def test_truncated_header_is_none(tmp_path):
    p = tmp_path / "m.nnr"
    _write(p, {"id": "abc"})
    p.write_bytes(p.read_bytes()[:20])
    assert nnr.read_header(str(p)) is None


def test_oversized_or_lying_length_is_none(tmp_path):
    p = tmp_path / "m.nnr"
    _write(p, {"id": "abc"}, hlen=10_000_000)
    assert nnr.read_header(str(p)) is None
    _write(p, {"id": "abc"}, hlen=5_000)
    assert nnr.read_header(str(p)) is None


def test_missing_file_and_non_object_json(tmp_path):
    assert nnr.read_header(str(tmp_path / "nope.nnr")) is None
    p = tmp_path / "m.nnr"
    raw = b"[1,2]"
    p.write_bytes(b"NNR1" + struct.pack("<HHI", 1, 1, len(raw)) + raw)
    assert nnr.read_header(str(p)) is None


def test_deeply_nested_header_is_none(tmp_path):
    p = tmp_path / "m.nnr"
    raw = b"[" * 60_000
    p.write_bytes(b"NNR1" + struct.pack("<HHI", 1, 1, len(raw)) + raw + b"\0" * 10)
    assert nnr.read_header(str(p)) is None


def test_bad_utf8_wrong_format_and_empty_are_none(tmp_path):
    p = tmp_path / "m.nnr"
    raw = b"\xff\xfe{"
    p.write_bytes(b"NNR1" + struct.pack("<HHI", 1, 1, len(raw)) + raw)
    assert nnr.read_header(str(p)) is None
    _write(p, {"id": "a"}, fmt=2)
    assert nnr.read_header(str(p)) is None
    p.write_bytes(b"")
    assert nnr.read_header(str(p)) is None
