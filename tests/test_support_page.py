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
    assert "['app_version', 'os', 'screen', 'window_size', 'log']" in code, \
        "the allowed fields must be an explicit list, not whatever the URL carries"


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
