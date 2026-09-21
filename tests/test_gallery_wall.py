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


# --- the caption renderer, and the contract between its two halves ---------
import subprocess
import sys

sys.path.insert(0, str(ROOT / "packaging"))


def test_php_caption_renderer_suite_passes():
    """Runs the PHP assertions inside the Python suite, so `pytest tests/ -q`
    is a complete gate and the PHP tests cannot rot unnoticed."""
    php = SITE / "tests" / "gallery_render_test.php"
    assert php.exists()
    r = subprocess.run(["php", str(php)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_the_two_renderers_emit_the_same_CLASSES():
    """THE MARKUP CONTRACT.

    gallery.php renders the wall from the database; build_showcase.py renders
    the statically built page that gallery.php falls back to when the database
    is unreachable. If their class vocabularies drift, a database outage
    changes what the wall LOOKS like as well as where it comes from — and the
    stylesheet only covers one of them.

    `.frame-common` is the one known difference: the common-name overlay is a
    hand-written Python dict (catalogue names SIMBAD cannot supply) and there
    is no column for it, so a submitted row has no common name to show.
    """
    import re as _re
    import build_showcase

    py = build_showcase.caption_html("ngc7000-drizzle-163x20s-54min-original")
    php = subprocess.run(
        ["php", "-r",
         'require "site/gallery_render.php";'
         'echo nocturne_caption_fields(["target"=>"NGC 7000","frames"=>163,'
         '"sub_s"=>"20.00","integration_s"=>3260,"handle"=>"@andreas"]);'],
        capture_output=True, text=True, cwd=ROOT)
    assert php.returncode == 0, php.stderr

    cls = lambda s: set(_re.findall(r'class="([a-z-]+)"', s))
    py_classes, php_classes = cls(py), cls(php.stdout)
    assert php_classes <= py_classes, (
        f"the dynamic wall emits classes the fallback does not: "
        f"{php_classes - py_classes}")
    assert py_classes - php_classes == {"frame-common"}, (
        f"unexpected divergence: {py_classes - php_classes}")


def test_every_caption_class_is_styled():
    """A class with no rule renders as unstyled inline text — the defect
    Andreas reported on the thank-you page, in a different place."""
    import build_showcase
    import re as _re
    css = (SITE / "styles.css").read_text(encoding="utf-8")
    used = _re.findall(r'class="(frame-[a-z-]+)"',
                       build_showcase.caption_html("m16-drizzle-333x10s-56min-original"))
    for c in set(used):
        assert f".{c}" in css, f"{c} has no rule in styles.css"
