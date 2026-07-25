import datetime

from nocturne.core import provenance
from nocturne.core.crop import CropParams


META = {
    "target": "NGC 7000",
    "livetime": 8100.0, "exposure": 60.0, "frames": 135,
    "date": "2026-07-20T21:03:00",
}
D = datetime.date(2026, 7, 25)


def _entries():
    return [
        ("Crop", CropParams(bounds=(0, 100, 0, 100))),   # native obj -> serialize_option -> dict
        ("Background", "graxpert"),                       # scalar str
        ("Color", {"neutralize_background": True, "remove_green": False, "method": "photometric"}),
        ("Stretch", 0.5),                                 # scalar float
        ("Levels", [0.02, 1.0, 1.0]),                     # list
    ]


def test_capture_header_shows_present_fields():
    r = provenance.build_report(_entries(), META, app_version="0.4.0", date=D)
    assert "# Nocturne processing report" in r
    assert "## Capture" in r
    assert "- Target: NGC 7000" in r
    assert "- Total integration: 2h 15m (135 × 60s)" in r
    assert "- Camera: Sony IMX585" in r
    assert "- Captured: 2026-07-20" in r


def test_narrative_uses_scalar_and_headline_field():
    r = provenance.build_report(_entries(), META, app_version="0.4.0", date=D)
    assert "1. Crop" in r                       # dict w/o headline field -> name only
    assert "2. Background — graxpert" in r       # scalar str
    assert "3. Color — photometric" in r         # dict headline field 'method'
    assert "4. Stretch — 0.5" in r               # scalar float
    assert "5. Levels" in r                      # list -> name only


def test_parameters_skips_scalars_lists_dicts_only_as_configured():
    r = provenance.build_report(_entries(), META, app_version="0.4.0", date=D)
    params = r.split("## Parameters")[1]
    assert "### 1. Crop" in params               # dict option -> block present
    assert "### 3. Color" in params
    assert "- method: photometric" in params
    assert "### 5. Levels" in params             # list option -> block present
    assert "- values: 0.02, 1.0, 1.0" in params
    assert "### 2. Background" not in params      # scalar -> skipped
    assert "### 4. Stretch" not in params         # scalar -> skipped


def test_footer_uses_passed_version_and_date():
    r = provenance.build_report(_entries(), META, app_version="0.4.0", date=D)
    assert "Nocturne 0.4.0 · report generated 25 July 2026" in r


def test_empty_history():
    r = provenance.build_report([], META, app_version="0.4.0", date=D)
    assert "_No processing steps applied._" in r
    assert "## Parameters" not in r


def test_missing_metadata_degrades_without_target_or_integration():
    r = provenance.build_report([("Stretch", 0.5)], {}, app_version="0.4.0", date=D)
    assert "## Capture" in r
    assert "- Camera: Sony IMX585" in r          # camera is always known from the profile
    assert "- Target:" not in r


def test_unserializable_option_is_isolated(monkeypatch):
    def boom(*a, **k):
        raise ValueError("bad option")
    monkeypatch.setattr(provenance, "serialize_option", boom)
    # a native (non-scalar) option now fails to serialize; report must still build
    r = provenance.build_report([("Crop", CropParams(bounds=(0, 1, 0, 1))), ("Stretch", 0.5)],
                                META, app_version="0.4.0", date=D)
    assert "### 1. Crop" in r
    assert "- (parameters unavailable)" in r
    assert "4. Stretch" not in r                  # only 2 steps
    assert "2. Stretch — 0.5" in r


def test_target_with_markdown_is_escaped():
    r = provenance.build_report([], {"target": "M31 *fake* [x]"}, app_version="0.4.0", date=D)
    assert "- Target: M31 \\*fake\\* \\[x\\]" in r
