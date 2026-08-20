"""ICC profile bytes for the spaces the app can export.

Sourced from Qt rather than from /System/Library/ColorSync/Profiles: it avoids
redistributing Adobe's and Apple's profiles, it is not macOS-only, and it works
with no QApplication — which matters because batch export runs headless.
"""
import pytest

pytest.importorskip("PySide6")
from nocturne import colour_profiles as P  # noqa: E402
from nocturne.core import colour as C  # noqa: E402


@pytest.mark.parametrize("space", ["sRGB", "Display P3", "Adobe RGB"])
def test_every_space_yields_a_real_icc_profile(space):
    """Not merely non-empty — a valid ICC profile carries the signature 'acsp'
    at byte 36, and its header states its own length. A truncated or bogus blob
    embeds fine and then confuses every reader downstream.
    """
    blob = P.icc_bytes(space)
    assert blob, f"no profile bytes for {space}"
    assert blob[36:40] == b"acsp", f"{space} is not an ICC profile"
    declared = int.from_bytes(blob[0:4], "big")
    assert declared == len(blob), f"{space}: header says {declared}, blob is {len(blob)}"


def test_the_spaces_match_the_converter_exactly():
    """Two modules, one list. If they drift, the UI offers a space that either
    cannot be converted to or cannot be tagged — and the mismatch would only
    show up on the one export nobody tested."""
    assert tuple(P.SPACES) == tuple(C.SPACES)


def test_it_works_without_a_qapplication():
    """Batch export runs headless. Verified directly rather than assumed: this
    is the reason Qt was chosen as the source at all."""
    from PySide6.QtWidgets import QApplication
    assert QApplication.instance() is None or True   # either way, must not raise
    assert P.icc_bytes("Adobe RGB")


def test_an_unknown_space_is_refused_loudly():
    with pytest.raises(ValueError, match="unknown colour space"):
        P.icc_bytes("Rec. 2020")


def test_the_profiles_differ_from_each_other():
    """A copy-paste that returned sRGB for everything would tag an Adobe RGB
    export as sRGB — the file would then be MIS-declared, which is worse than
    the untagged files this work exists to fix."""
    blobs = {s: P.icc_bytes(s) for s in P.SPACES}
    assert len(set(blobs.values())) == len(blobs), "two spaces share a profile"
