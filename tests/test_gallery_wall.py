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


# --- gallery.php, the dynamic wall ----------------------------------------

GALLERY_PHP = SITE / "gallery.php"


def test_gallery_php_uses_the_shared_renderer():
    src = GALLERY_PHP.read_text(encoding="utf-8")
    assert "gallery_render.php" in src, "must not re-implement the caption"
    assert "nocturne_figure" in src


def test_gallery_php_shows_only_approved():
    """A pending row on the public wall is the failure approval exists for."""
    src = GALLERY_PHP.read_text(encoding="utf-8")
    assert "status = 'approved'" in src


def test_gallery_php_degrades_to_the_static_page_instead_of_erroring():
    """Spec 2.1. This is the first page on the site that can be down, and a
    visitor came to look at photographs."""
    src = GALLERY_PHP.read_text(encoding="utf-8")
    assert "catch" in src and "gallery.html" in src
    # The catch must not also emit a 500 — that would defeat the fallback.
    tail = src.split("} catch (Throwable $e) {", 1)[1].split("}", 1)[0]
    assert "http_response_code" not in tail, "the fallback must still be served"


def test_an_empty_approved_set_does_not_blank_the_page():
    """Before the seed runs there are no rows. Replacing the static tiles with
    nothing would turn the wall into an empty page rather than leaving it as
    the truthful content it already is."""
    src = GALLERY_PHP.read_text(encoding="utf-8")
    assert "if ($rows)" in src


def test_gallery_php_sends_an_etag_and_honours_it():
    src = GALLERY_PHP.read_text(encoding="utf-8")
    assert "ETag" in src and "Cache-Control" in src
    assert "HTTP_IF_NONE_MATCH" in src and "304" in src


def test_every_new_endpoint_is_in_the_deploy_allowlist():
    """The include list is a non-recursive glob and every .php is named
    individually. The spec calls this the THIRD time it would have bitten."""
    toml = (ROOT / "packaging" / "deploy.example.toml").read_text(encoding="utf-8")
    include = toml.split("include", 1)[1].split("]", 1)[0]
    for php in ("gallery.php", "gallery_render.php", "submit.php"):
        assert php in include, f"deploy.example.toml does not ship {php}"


# --- submit.php, the endpoint ---------------------------------------------

SUBMIT_PHP = SITE / "submit.php"


def test_php_submit_validate_suite_passes():
    php = SITE / "tests" / "submit_validate_test.php"
    assert php.exists()
    r = subprocess.run(["php", str(php)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_status_is_never_named_on_insert():
    """The pending default is the guard. An INSERT that names `status` is one
    word from publishing every submission unmoderated; one that omits it
    cannot be."""
    src = SUBMIT_PHP.read_text(encoding="utf-8")
    cols = src.split("INSERT INTO submissions (", 1)[1].split(")", 1)[0]
    assert "status" not in cols, f"let the column default supply 'pending': {cols}"


def test_rate_limit_comes_from_config():
    src = SUBMIT_PHP.read_text(encoding="utf-8")
    assert "submission_rate_per_hour" in src
    assert "?? 5" in src, "5/hour is the documented default"


def test_pending_files_go_outside_the_web_root():
    """Nothing pending may have a public address, even if the filename is
    guessed. submission_dir is configured outside every DocumentRoot."""
    src = SUBMIT_PHP.read_text(encoding="utf-8")
    assert "submission_dir" in src
    assert "stored_pending" in src
    # It must not write into the servable image directories.
    assert "img/showcase" not in src and "img/gallery" not in src


def test_derivatives_are_not_generated_on_upload():
    """Nothing expensive happens here, so a flood costs disk and nothing else
    (spec 5). Resizing belongs to approval."""
    src = SUBMIT_PHP.read_text(encoding="utf-8")
    for expensive in ("imagecopyresampled", "imagescale", "thumbnail", "Imagick"):
        assert expensive not in src, f"{expensive} belongs in approval, not upload"


def test_no_location_field_is_accepted():
    """Global constraint: never a location, in any payload or column."""
    src = SUBMIT_PHP.read_text(encoding="utf-8")
    cols = src.split("INSERT INTO submissions (", 1)[1].split(")", 1)[0]
    for leak in ("lat", "lon", "location", "site"):
        assert leak not in cols, f"{leak} reached the insert"


# --- moderation, retention and the privacy rewrite -------------------------

# The wall's moderation moved to admin/wall.php when the admin became tabs on
# 2026-09-22. These tests kept their assertions and changed where they look —
# which is the split being visible rather than silent.
ADMIN = SITE / "admin" / "wall.php"
ADMIN_ENTRY = SITE / "admin" / "admin.php"


def test_admin_lists_pending_submissions_first():
    src = ADMIN.read_text(encoding="utf-8")
    assert "FROM submissions" in src
    assert "CASE status WHEN 'pending' THEN 0" in src, \
        "pending must sort first; FIELD() was dropped so a SQLite fixture can run this"


def test_every_moderation_action_is_token_guarded():
    src = ADMIN.read_text(encoding="utf-8")
    block = src.split("isset($_POST['sub_action'])", 1)[1][:400]
    assert "hash_equals" in block and "nocturne_admin_token" in block


def test_rejection_deletes_the_file_rather_than_flagging_it():
    """Keeping a copy of something you rejected is the worst of both."""
    src = ADMIN.read_text(encoding="utf-8")
    block = src.split("$act === 'reject'", 1)[1][:700]
    assert "unlink" in block


def test_approval_is_the_only_step_that_resizes():
    """Nothing expensive on upload, so a flood costs disk and nothing else."""
    src = ADMIN.read_text(encoding="utf-8")
    assert "imagescale" in src.split("$act === 'approve'", 1)[1][:1600]
    assert "imagescale" not in SUBMIT_PHP.read_text(encoding="utf-8")


def test_approval_never_upscales():
    src = ADMIN.read_text(encoding="utf-8")
    assert "min(1.0," in src, "a share is never upscaled — it adds pixels, not detail"


def test_pending_images_are_streamed_not_linked():
    dl = (SITE / "admin" / "download.php").read_text(encoding="utf-8")
    assert "submission" in dl and "stored_pending" in dl
    meta = (SITE / "admin" / "wall.php").read_text(encoding="utf-8")
    assert "download.php?submission=" in meta


def test_only_an_approved_catalogue_match_can_be_the_planner_picture():
    src = ADMIN.read_text(encoding="utf-8")
    fn = src.split("function nocturne_wall_actions", 1)[1].split("\n}", 1)[0]
    assert "'approved'" in fn and "catalogue_id" in fn


def test_planner_thumbs_is_written_whole_not_patched():
    src = ADMIN.read_text(encoding="utf-8")
    fn = src.split("function nocturne_wall_write_planner_thumbs", 1)[1].split("\n}", 1)[0]
    assert "file_put_contents" in fn and "json_encode" in fn
    assert "representative = 1" in fn and "status = 'approved'" in fn


def test_cleanup_expires_the_ip_but_never_the_picture():
    """An approved picture is the thing the page is for."""
    src = (SITE / "cleanup.php").read_text(encoding="utf-8")
    block = src.split("Wall submissions", 1)[1].split("// Download-click", 1)[0]
    assert "SET ip = NULL" in block
    assert "stored_900" not in block and "stored_2000" not in block, \
        "the derivatives must never be deleted by retention"


def test_privacy_page_no_longer_claims_images_never_leave():
    """The wall makes the old sentence false. Shipping with it live would have
    left the site stating something untrue."""
    t = (SITE / "_src" / "privacy.html").read_text(encoding="utf-8")
    assert "<h2>The gallery</h2>" in t, "the section naming the third route out"
    assert "handle is public" in t.lower()
    assert "deleted rather than" in t, "rejection must be described"
    assert "support.html" in t, "the takedown route must be stated"
    # The old absolute claim must be gone.
    assert "your images never do" not in t.lower()


def test_faq_moved_with_the_privacy_page():
    """faq.html repeated the same claim in two answers."""
    t = (SITE / "_src" / "faq.html").read_text(encoding="utf-8")
    assert "only exception is" not in t.lower(), \
        "the FAQ still names one exception where there are now three"
    assert "gallery" in t.lower()


def test_the_wall_states_its_own_takedown_route():
    """No accounts, so someone who later wants their picture gone cannot do it
    themselves. It will happen, so the page has to say where to ask."""
    t = (SITE / "_src" / "gallery.html").read_text(encoding="utf-8")
    assert "support.html" in t


def test_privacy_and_faq_agree_on_how_many_ways_an_image_can_leave():
    """Three: the sample-data form, a report attachment, and the wall. A page
    that names two is the same defect as the one just fixed, later."""
    priv = (SITE / "_src" / "privacy.html").read_text(encoding="utf-8").lower()
    for route in ("sample-data", "problem report", "gallery"):
        assert route in priv, f"privacy.html does not mention {route}"


def test_an_approved_picture_can_be_taken_off_the_wall():
    """privacy.html tells people a published picture will come down if they
    ask. Until 2026-09-21 nothing in the admin could do it — the same gap the
    reports table had, in a place where the site makes a promise about it."""
    src = ADMIN.read_text(encoding="utf-8")
    assert "'unpublish'" in src
    fn = src.split("function nocturne_wall_actions", 1)[1].split("\n}", 1)[0]
    assert "unpublish" in fn, "the action must be reachable from an approved row"


def test_taking_a_picture_down_DELETES_the_files():
    """'I took it down' has to mean the file is gone, not hidden. Spec 5.1: a
    picture that is not published is not kept."""
    src = ADMIN.read_text(encoding="utf-8")
    block = src.split("$act === 'unpublish'", 1)[1].split("elseif ($act === 'represent')", 1)[0]
    assert "unlink" in block
    assert "stored_2000" in block and "stored_900" in block
    assert "stored_2000=NULL" in block, "the columns must be cleared, not left dangling"


def test_taking_a_picture_down_clears_the_planner_slot():
    """It may have been the planner's picture for an object. Leaving it
    representative would keep a deleted file in planner-thumbs.json."""
    src = ADMIN.read_text(encoding="utf-8")
    block = src.split("$act === 'unpublish'", 1)[1].split("elseif ($act === 'represent')", 1)[0]
    assert "representative=0" in block
    assert "nocturne_wall_write_planner_thumbs" in block


def test_every_row_can_be_deleted_outright():
    src = ADMIN.read_text(encoding="utf-8")
    fn = src.split("function nocturne_wall_actions", 1)[1].split("\n}", 1)[0]
    assert "'remove'" in fn
    assert fn.index("$acts['remove']") > fn.index("if ($s['status'] === 'approved')"), \
        "remove must be offered for every status, not only approved"


def test_the_SHARE_page_no_longer_claims_to_submit():
    """Moved to the Export step on 2026-09-22 (spec §2.4). A page still
    describing a button that is not there is worse than one that is silent."""
    t = (SITE / "_src" / "share.html").read_text(encoding="utf-8")
    assert "Send to the wall" not in t


def test_the_pages_point_at_EXPORT():
    """The wall's only route in is the Export step, so the pages that describe
    submitting have to name it."""
    priv = (SITE / "_src" / "privacy.html").read_text(encoding="utf-8")
    assert "Export</strong> step can send" in priv
    assert "location is never sent" in priv.lower() or "never sent" in priv.lower()
    gal = (SITE / "_src" / "gallery.html").read_text(encoding="utf-8")
    assert "Export" in gal and "support.html" in gal
    assert "Share window" not in gal


def test_the_gallery_copy_lives_in_its_GENERATOR():
    """_src/gallery.html is written whole by build_showcase.py every run, so an
    edit there is undone by the next build — which happened on 2026-09-21 and
    silently reverted a prose review."""
    gen = (ROOT / "packaging" / "build_showcase.py").read_text(encoding="utf-8")
    assert "Export</strong>\n          step" in gen or "<strong>Export</strong>" in gen


def test_the_admin_can_inspect_a_submission_full_size():
    """Andreas: "right now its pretty hard to see what you are approving
    because they are small." A 280px tile is not enough to judge a photograph,
    and approving is the irreversible-ish half of moderation."""
    src = ADMIN.read_text(encoding="utf-8")
    assert 'id="lb"' in src, "no lightbox"
    assert "data-full" in src
    assert "Escape" in src, "it must be closable from the keyboard"


def test_a_PENDING_image_is_inspected_through_the_STREAM():
    """It has no public address by design, so the lightbox must open the same
    authenticated stream the tile does — not a guessed path."""
    src = ADMIN.read_text(encoding="utf-8")
    block = src.split("Waiting for you", 1)[1][:900]
    assert 'data-full="download.php?submission=' in block
    assert "srv/nocturne-submissions" not in block, \
        "the pending store path must never reach the markup"


def test_an_APPROVED_image_opens_its_2000px_derivative():
    """The tile shows the 900; inspecting it should not just scale that up."""
    src = ADMIN.read_text(encoding="utf-8")
    assert "stored_2000'] ?: $s['stored_900']" in src, \
        "the lightbox must prefer the 2000, falling back if it is missing"


def test_the_admin_lightbox_does_not_depend_on_a_deployed_site_file():
    """admin/ is excluded from the deploy rsync. Depending on lightbox.js —
    which rsync DOES ship — would break the moment the two drifted."""
    # BEHAVIOUR only. Since 2026-09-22 the admin deliberately links the site's
    # ../styles.css — a DESIGN dependency, where drift is the point and the
    # worst failure is looking wrong. lightbox.js would be a BEHAVIOURAL one,
    # where drift breaks the page silently, and that is still refused.
    src = ADMIN.read_text(encoding="utf-8") + \
        (SITE / "admin" / "_common.php").read_text(encoding="utf-8")
    assert not re.search(r'(src)\s*=\s*["\'][^"\']*lightbox\.js', src), \
        "the admin must not load the site's lightbox script"
    assert "<script" in ADMIN.read_text(encoding="utf-8"), "it carries its own"


# --- the admin became tabs (2026-09-22) ------------------------------------

ADMIN_DIR = SITE / "admin"
COMMON = ADMIN_DIR / "_common.php"
WALL_PHP = ADMIN_DIR / "wall.php"


def test_every_admin_file_parses():
    """Four files now, hand-copied to the server. A parse error is a page that
    is simply gone, behind auth where nobody would see it fail."""
    for f in ("admin.php", "_common.php", "wall.php", "_wall_meta.php", "download.php"):
        r = subprocess.run(["php", "-l", str(ADMIN_DIR / f)], capture_output=True, text=True)
        assert r.returncode == 0, f"{f}: {r.stdout}{r.stderr}"


def test_the_include_only_files_refuse_to_run_alone():
    """Reached directly they either open a database connection nobody asked for
    or die on an undefined variable, printing a server path in the error."""
    for f in ("_common.php", "wall.php", "_wall_meta.php"):
        src = (ADMIN_DIR / f).read_text(encoding="utf-8")
        assert "defined('NOCTURNE_ADMIN')" in src, f"{f} is not guarded"
    assert "define('NOCTURNE_ADMIN'" in (ADMIN_DIR / "admin.php").read_text(encoding="utf-8")


def test_the_wall_renders_through_a_FUNCTION_so_actions_run_first():
    """wall.php handles its own POSTs and redirects. If admin.php emitted the
    page head before requiring it, header() would fail with 'headers already
    sent' and a refresh would repeat the action — which is exactly what the
    first version did."""
    a = (ADMIN_DIR / "admin.php").read_text(encoding="utf-8")
    i_require = a.index("require __DIR__ . '/wall.php'")
    i_head = a.index("nocturne_admin_head('wall'")
    assert i_require < i_head, "the head must not be emitted before wall.php runs"
    assert "nocturne_wall_render(" in a
    assert "function nocturne_wall_render(" in WALL_PHP.read_text(encoding="utf-8")


def test_the_ordering_sql_is_portable():
    """MySQL's FIELD() made the whole tab a fatal error against the SQLite
    fixture, which is the only way to exercise this page outside production.
    Untestable SQL is how a page reaches the server having never been run."""
    src = WALL_PHP.read_text(encoding="utf-8")
    assert "FIELD(status" not in src
    assert "CASE status WHEN 'pending'" in src


def test_a_row_with_no_capture_facts_prints_nothing_rather_than_separators():
    """Row 25 — an M 31 finished from a TIFF — had no frames and no exposure,
    and the page printed a stray "× s"."""
    src = (ADMIN_DIR / "_wall_meta.php").read_text(encoding="utf-8")
    assert "$exposure !== ''" in src
    fn = WALL_PHP.read_text(encoding="utf-8").split(
        "function nocturne_wall_exposure", 1)[1].split("\n}", 1)[0]
    assert "return ''" in fn, "it must be able to produce nothing at all"


def test_acting_on_a_filtered_page_keeps_the_filter():
    """Acting on row three of page two must not throw you back to the top of
    page one."""
    src = WALL_PHP.read_text(encoding="utf-8")
    assert "array_flip(['tab', 'status', 'handle', 'p'])" in src


def test_the_tables_scroll_instead_of_the_page():
    """The reports table has eleven columns and dragged the whole document
    sideways at phone width — 483px of overflow, taking the tab strip with it,
    so the navigation moved when you scrolled the data."""
    assert ".adm-scroll" in COMMON.read_text(encoding="utf-8")
    for f in ("admin.php", "wall.php"):
        src = (ADMIN_DIR / f).read_text(encoding="utf-8")
        assert src.count('<table class="adm">') == src.count('adm-scroll"><table'), \
            f"{f} has an unwrapped table"


def test_the_admin_uses_the_SITE_stylesheet_and_its_tokens():
    """Andreas asked for the admin to look like the site. The tokens matter as
    much as the link: fresh hex here would be a second palette to maintain."""
    src = COMMON.read_text(encoding="utf-8")
    assert 'href="../styles.css"' in src
    for token in ("var(--ground)", "var(--ink)", "var(--muted)", "var(--rule)",
                  "var(--oxide-text)", "var(--mono)"):
        assert token in src, f"{token} unused — is this a second palette?"
    # The planner's verdict colours carry status, rather than a new green.
    for v in ("--verdict-go", "--verdict-warn", "--verdict-no"):
        assert v in src


def test_every_token_the_admin_uses_is_DEFINED_by_the_site():
    """A var() with no definition renders as nothing, which for a colour means
    transparent text."""
    import re as _re
    css = (SITE / "styles.css").read_text(encoding="utf-8")
    used = set(_re.findall(r"var\((--[a-z-]+)\)", COMMON.read_text(encoding="utf-8")))
    missing = [t for t in used if f"{t}:" not in css]
    assert missing == [], f"not defined in styles.css: {missing}"


def test_the_SITE_says_gallery_not_wall():
    """One nomenclature. The page is called Gallery everywhere else, so the
    pages describing submission say gallery too. The changelog is exempt: its
    v0.38.0 entry describes a button that really was called "Send to the wall",
    and rewriting history would make the record false."""
    for name in ("privacy.html", "gallery.html", "share.html", "faq.html"):
        t = (SITE / "_src" / name).read_text(encoding="utf-8")
        assert "the wall" not in t.lower(), f"{name} still says 'the wall'"
