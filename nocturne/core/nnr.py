"""Public header of a .nnr model file.

Only the unencrypted header is read here, with no cryptography: the engine
authenticates the whole file when it opens it, so anything this module reports
is for listing and filtering, never for trust.
"""
from __future__ import annotations

import json
import os
import struct

MAGIC = b"NNR1"
SUPPORTED_CONTRACTS = frozenset({1})

# Real headers are a few hundred bytes; the cap keeps a hostile length field
# from making us read a whole file into memory.
_MAX_HEADER = 64 * 1024


def read_header(path: str) -> dict | None:
    """The header dict, or None for anything malformed or not an NNR file."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            fixed = f.read(12)
            if len(fixed) < 12 or fixed[:4] != MAGIC:
                return None
            fmt, _key_id, hlen = struct.unpack("<HHI", fixed[4:12])
            if fmt != 1 or hlen == 0 or hlen > _MAX_HEADER or 12 + hlen > size:
                return None
            raw = f.read(hlen)
        if len(raw) != hlen:
            return None
        header = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError, struct.error):
        return None
    return header if isinstance(header, dict) else None
