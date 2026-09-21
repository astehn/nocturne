"""The support page and the Help menu entry that leads to it.

Built 2026-09-20 because users were reporting GUI sizing problems on Reddit,
where Andreas cannot ask a follow-up question and will not publish an email
address to be scraped. The point of the feature is not the form; it is that a
report arrives with enough context to be FIXED WITHOUT A REPLY, because most
reporters never send a second message.
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


def _html() -> str:
    return (SITE / "support.html").read_text(encoding="utf-8")


def test_the_form_asks_for_the_thing_the_reports_were_missing():
    """Screen size, because "a MacBook Pro" is four panels and several scaling
    settings and only the LOGICAL size decides whether a toolbar fits."""
    h = _html()
    for field in ("problem", "email", "app_version", "os", "screen",
                  "window_size", "log", "attachment"):
        assert f'name="{field}"' in h, field
    assert 'action="support.php"' in h
    assert 'enctype="multipart/form-data"' in h


def test_the_form_works_without_javascript():
    """A support page must not have a second way to fail. The prefill is
    progressive enhancement; the form itself is a plain POST."""
    h = _html()
    assert 'method="post"' in h
    # No submit handler, no fetch: the browser submits it.
    assert "onsubmit" not in h.lower()


def test_andreas_s_email_address_is_NOT_on_the_page():
    """His explicit wish — *"id rather not post my email directly on Reddit"* —
    and a public address on a linked page is the same exposure by a slower
    route. The form collects the REPORTER's address instead, so he can reply
    without ever publishing his own.
    """
    h = _html()
    assert "andreas@stehn.com" not in h
    assert not re.search(r"mailto:", h), "no mailto link either"


def test_the_honeypot_is_hidden_from_everyone():
    """Visible to a screen reader would be worse than not having one."""
    h = _html()
    i = h.index('name="website"')
    assert 'aria-hidden="true"' in h[max(0, i - 400):i]
    assert 'tabindex="-1"' in h[i - 200:i + 200]


def test_the_page_says_what_happens_to_what_is_sent():
    h = _html()
    assert "privacy.html" in h
    assert "28 days" in h, "retention is a promise and must be stated"


def test_every_page_links_to_support_from_the_footer():
    """In the footer, not the nav: the nav is nine items and collapses at
    1000px, and support is not a destination anyone browses to."""
    for page in ("index.html", "planner.html", "faq.html", "download.html"):
        assert 'href="support.html"' in (SITE / page).read_text(encoding="utf-8"), page


def test_the_backend_would_actually_ship():
    """support.php must be in the deploy allowlist. The glob is NOT recursive
    and does not cover *.php — get.php, ping.php and cleanup.php are each named
    individually, so a new endpoint is silently left behind, working in local
    preview and 404ing in production."""
    import sys
    import tomllib
    sys.path.insert(0, str(ROOT / "packaging"))
    with open(ROOT / "packaging" / "deploy.example.toml", "rb") as f:
        include = tomllib.load(f)["website"]["include"]
    assert "support.php" in include, "the form would post to a 404"


def test_the_prefill_only_reads_the_fields_it_owns():
    """A query string is attacker-supplied. The script sets .value on a fixed
    list of ids and never touches innerHTML, so a crafted link cannot inject
    markup into the page."""
    js = (SITE / "support.js").read_text(encoding="utf-8")
    # Strip comments before looking: the file's own comment says ".value, never
    # innerHTML", and a test that greps for the word flags the explanation
    # rather than the behaviour.
    code = re.sub(r"//.*", "", js)
    assert "innerHTML" not in code, "a query-string value must never reach innerHTML"
    assert ".value =" in code, "it sets .value, which cannot execute markup"
    assert "['topic', 'app_version', 'os', 'screen', 'window_size', 'log']" in code, \
        "the allowed fields must be an explicit list, not whatever the URL carries"
    # 'topic' joined the list on 2026-09-21 so index.html can deep-link a
    # donated-file removal request straight into the right topic. It is a
    # <select>: an unknown value leaves it on its current option, so a stale
    # link degrades to the default rather than filing under nothing.


# --- the styled response page (2026-09-21) -------------------------------
# Andreas, after the first real report: the thank-you page "is totally unstyled,
# it breaks the experience". support.php answers a POST with a whole page, so it
# needs the whole shell. The shell is GENERATED, and these tests exist to catch
# the two ways that goes wrong silently.

SHELL = SITE / "_shell.php"


def test_build_site_generates_the_php_shell():
    assert SHELL.exists(), "run packaging/build_site.py"
    src = SHELL.read_text()
    assert "function nocturne_shell(" in src
    assert 'class="nav"' in src and 'class="footer"' in src


def test_shell_asks_for_the_CURRENT_stylesheet_hash():
    """The reason the shell is generated rather than hand-written.

    head_html() cache-busts styles.css by content hash. A hand-copied shell
    keeps requesting a hash that no longer exists the moment anyone edits the
    stylesheet, and the page renders unstyled again with nothing to say so —
    the exact defect this change was made to fix.
    """
    import sys
    sys.path.insert(0, str(ROOT / "packaging"))
    import build_site

    expected = build_site.asset_url("styles.css")
    assert expected in SHELL.read_text(), (
        f"_shell.php does not reference {expected} — rebuild the site")


def test_shell_leaves_no_placeholder_behind():
    src = SHELL.read_text()
    # Both placeholders must survive into the file (they are substituted at
    # request time by PHP), and neither may leak into the nowdoc terminator.
    assert "@@NOCTURNE_TITLE@@" in src and "@@NOCTURNE_BODY@@" in src
    body = src.split("<<<'NOCTURNE_SHELL_HTML'", 1)[1]
    assert "NOCTURNE_SHELL_HTML;" in body


def test_support_php_renders_through_the_shell_and_survives_without_it():
    src = (SITE / "support.php").read_text()
    assert "nocturne_shell($title, $body)" in src
    # The fallback matters: a missing shell must degrade to an ugly page, never
    # to a fatal error after someone has already typed out their problem.
    assert "function_exists('nocturne_shell')" in src
    assert "is_file($shell)" in src


def test_error_list_is_escaped_not_interpolated():
    src = (SITE / "support.php").read_text()
    assert "htmlspecialchars($e, ENT_QUOTES, 'UTF-8')" in src


def test_shell_is_named_in_the_deploy_allowlist():
    """The include list is an allowlist resolved by a NON-recursive glob, and
    every .php is named individually. A new one that is not listed simply never
    ships, and the live page falls back to unstyled with nothing failing."""
    toml = (ROOT / "packaging" / "deploy.example.toml").read_text()
    include = toml.split("include", 1)[1].split("]", 1)[0]
    assert "_shell.php" in include, "add _shell.php to the deploy include list"


# --- report topics, and the address that is no longer on the site (2026-09-21)
# Andreas: his personal address was published in two places, "very easy for
# scrapers to grab" and people "will simply send questions and support requests
# directly to it (it has already happened)". The address is gone; the topic
# selector is what has to carry what it used to.

TOPIC_KEYS = ("problem", "question", "privacy", "donated-file")


def test_no_personal_address_anywhere_in_the_site_source():
    """The whole point of the change. A regression here is a live mailto: on a
    public page, which cannot be un-scraped once it ships."""
    hits = []
    for f in list(SITE.glob("_src/*.html")) + list(SITE.glob("*.php")) \
            + list(SITE.glob("*.js")) + list(SITE.glob("admin/*.php")):
        if "andreas@stehn.com" in f.read_text(encoding="utf-8", errors="ignore"):
            hits.append(f.relative_to(SITE).as_posix())
    assert hits == [], f"personal address still present in: {hits}"


def test_privacy_page_keeps_a_REAL_contact_not_only_a_form():
    """A privacy notice that offers only a web form is a weaker notice. The
    role address is the point — it is durable and can be rotated; it is not an
    invitation to drop the contact entirely."""
    t = (SITE / "_src" / "privacy.html").read_text(encoding="utf-8")
    assert "mailto:privacy@nocturneastro.com" in t
    assert "report form" in t, "privacy page must send non-privacy mail elsewhere"


def test_form_offers_every_topic_and_defaults_to_problem():
    t = (SITE / "_src" / "support.html").read_text(encoding="utf-8")
    for key in TOPIC_KEYS:
        assert f'value="{key}"' in t, f"topic {key} missing from the form"
    assert 'value="problem" selected' in t, "the existing bug flow must be the default"


def test_php_topic_list_matches_the_form():
    php = (SITE / "support.php").read_text(encoding="utf-8")
    keys = set(re.findall(r"'([a-z-]+)'\s*=>\s*'[^']+',", php.split(
        "NOCTURNE_REPORT_TOPICS = [", 1)[1].split("];", 1)[0]))
    assert keys == set(TOPIC_KEYS), f"php topics {keys} != form topics {set(TOPIC_KEYS)}"


def test_unknown_topic_falls_back_rather_than_erroring():
    """A stale link or a mistyped POST must not cost someone their report."""
    php = (SITE / "support.php").read_text(encoding="utf-8")
    fn = php.split("function nocturne_report_topic", 1)[1].split("\n}", 1)[0]
    assert "array_key_exists" in fn and "NOCTURNE_REPORT_TOPIC_DEFAULT" in fn


def test_topic_is_stored_and_reaches_the_subject_line():
    php = (SITE / "support.php").read_text(encoding="utf-8")
    assert "INSERT INTO reports (topic," in php
    assert "nocturne_report_topic($_POST['topic'] ?? null)" in php
    assert "NOCTURNE_REPORT_TOPICS[nocturne_report_topic($r['topic'] ?? null)]" in php


def test_migration_and_schema_both_carry_the_column():
    mig = SITE / "db" / "migrate-2026-09-21-report-topic.sql"
    assert mig.exists(), "the live table needs a migration, not just schema.sql"
    assert "ADD COLUMN topic" in mig.read_text(encoding="utf-8")
    assert "topic" in (SITE / "db" / "schema.sql").read_text(encoding="utf-8")


def test_admin_shows_the_topic():
    """admin/ is excluded from the deploy rsync and is copied by hand, so this
    test is the only thing that notices when the two drift."""
    t = (SITE / "admin" / "admin.php").read_text(encoding="utf-8")
    assert "$TOPICS" in t and "<th>Topic</th>" in t


def test_notification_sender_stays_on_a_domain_whose_SPF_allows_the_VPS():
    """THE TRAP, pinned 2026-09-21.

    Cloudflare Email Routing gave nocturneastro.com an SPF of
    `v=spf1 include:_spf.mx.cloudflare.net ~all`, which does NOT list the VPS.
    stehn.com's SPF does (ip4:162.19.137.95). Moving report_from to the new
    domain would make every notification fail SPF — silently, because the local
    queue accepts it either way and only the recipient sees the quarantine.
    """
    php = (SITE / "support.php").read_text(encoding="utf-8")
    default = re.search(r"\$cfg\['report_from'\] \?\? '([^']+)'", php)
    assert default, "report_from default not found"
    assert default.group(1).endswith("@stehn.com"), (
        f"{default.group(1)} is on a domain whose SPF may not authorise the VPS — "
        "add the VPS ip4 to that domain's SPF before changing this")
