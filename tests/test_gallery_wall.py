"""The wall: the gallery becomes a database-backed, moderated surface.

Spec: docs/superpowers/specs/2026-09-20-gallery-submissions-design.md
Plan: docs/superpowers/plans/2026-09-21-gallery-submissions-a-the-wall.md
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"

pytestmark = pytest.mark.skipif(
    not (SITE / "index.html").exists(),
    reason="site/ is decoupled and gitignored — only validated when present locally",
)

MIGRATION = SITE / "db" / "migrate-2026-09-21-submissions.sql"

# Every column the spec's §4 names. A later task that quietly renames one of
# these breaks gallery.php or the importer, and the symptom is an empty wall
# rather than an error.
SUBMISSION_COLUMNS = (
    "id", "created_at", "handle", "target", "catalogue_id", "integration_s",
    "frames", "sub_s", "captured_on", "instrument", "stored_2000", "stored_900",
    "stored_pending", "orig_filename", "size_bytes", "ip", "status",
    "representative",
)


def test_migration_exists_and_creates_the_table():
    assert MIGRATION.exists(), "the live database needs a migration, not just schema.sql"
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "CREATE TABLE" in sql and "submissions" in sql


def test_migration_and_schema_carry_every_spec_column():
    for path in (MIGRATION, SITE / "db" / "schema.sql"):
        sql = path.read_text(encoding="utf-8")
        block = sql.split("submissions", 1)[1]
        for col in SUBMISSION_COLUMNS:
            assert re.search(rf"\b{col}\b", block), f"{path.name} is missing {col}"


def test_status_defaults_to_pending_not_approved():
    """The single most important default in the feature. An approved default
    would publish an unmoderated image the moment it is posted, which is the
    one outcome §5.1 exists to prevent."""
    sql = MIGRATION.read_text(encoding="utf-8")
    m = re.search(r"status\s+ENUM\([^)]*\)[^,]*", sql)
    assert m, "status column not found"
    assert "DEFAULT 'pending'" in m.group(0), m.group(0)
