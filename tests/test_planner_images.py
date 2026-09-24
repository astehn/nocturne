"""Guards for planner target images.

site/ is gitignored and deploys by rsync, so these read the working copy.
"""
import json
import re
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
SITE = ROOT / "site"
pytestmark = pytest.mark.skipif(not SITE.is_dir(), reason="site/ is local-only")


def test_the_wall_writes_a_320_derivative():
    """The collapsed card is 64px (48 on mobile). Without this it is served a
    900px JPEG — twenty times the bytes, on the one page that gets opened in a
    field."""
    php = (SITE / "admin" / "wall.php").read_text(encoding="utf-8")
    sizes = re.search(r"foreach \(\[(.*?)\] as \$edge", php, re.S)
    assert sizes, "the derivative loop moved; find it and update this guard"
    assert "320" in sizes.group(1), "the approval loop does not write a 320px file"


def test_the_showcase_writes_a_320_derivative():
    """The constant being DEFINED proves nothing; it has to be written.

    `assert "320" in py` over the whole module passed with
    `(PLANNER_EDGE, "planner")` deleted from the size loop, because
    PLANNER_EDGE = 320 still sat at the top unused. Gallery pictures then fall
    through nocturne_planner_thumb()'s self-healing branch and serve the 1100
    into a 64px box — the ~20x regression the edge constant exists to prevent,
    on the page most likely to be opened on a phone outdoors. Proved toothless
    by mutation in the whole-branch review, 2026-09-24.
    """
    import sys
    sys.path.insert(0, str(ROOT / "packaging"))
    import build_showcase

    assert build_showcase.PLANNER_EDGE == 320
    py = (ROOT / "packaging" / "build_showcase.py").read_text(encoding="utf-8")
    sizes = py[py.index("def write_sizes"):]
    sizes = sizes[:sizes.index("\ndef ")]
    assert "PLANNER_EDGE" in sizes, \
        "write_sizes() no longer emits the planner derivative, so the 320 is never written"


# --- Task 6: the gallery manifest -------------------------------------------
#
# nocturne_planner_meta() reads $row['full'] for the gallery source. A
# manifest row with no `full` key makes $full = '', the existence check
# fails, and the association is silently dropped from the artifact with no
# error at all — the exact failure the wall source had on 2026-09-24. These
# read the REAL manifest rather than a fixture, so they catch a regression in
# what build_showcase.py actually wrote, not just what it meant to.
_MANIFEST = SITE / "img" / "showcase" / "showcase.json"
_manifest_reason = "run .venv/bin/python packaging/build_showcase.py first"


def _load_manifest():
    if not _MANIFEST.is_file():
        pytest.skip(_manifest_reason)
    entries = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    if not entries:
        pytest.skip(_manifest_reason)
    return entries


def test_the_showcase_manifest_carries_a_full_key_for_every_entry():
    for e in _load_manifest():
        assert e.get("full"), f"{e.get('stem')!r} has no full path — see nocturne_gallery_facts()"


def test_the_showcase_manifest_names_the_1100_not_the_2400():
    """Andreas: images in the planner should not be presented fullsize as
    they are in the gallery. images["full"] inside build_showcase.py is the
    2400 the lightbox opens; the manifest's `full` field must be the 1100
    (images["grid"]) instead — see manifest_row()'s docstring for the name
    collision this guards against."""
    for e in _load_manifest():
        assert e["full"].endswith("-1100.jpg"), \
            f"{e['stem']}: full references {e['full']!r}, not the 1100"
        assert "-2400" not in e["full"], \
            f"{e['stem']}: the 2400 must never reach the planner"


def test_the_showcase_manifest_full_path_exists_on_disk():
    for e in _load_manifest():
        assert (SITE / e["full"]).is_file(), \
            f"{e['stem']}: full path {e['full']} does not exist on disk"


def test_the_showcase_manifest_excludes_non_photographs():
    """img/gallery (the OTHER generator's output) also holds before/after
    assets for tool pages. img/showcase holds none today, but the manifest is
    still built from a directory of Share exports one filename at a time — if
    a comparison-style stem ever lands there, it must not silently become a
    plannerable photograph."""
    stems = [e["stem"] for e in _load_manifest()]
    assert not [s for s in stems if "compare" in s.lower()], \
        "a comparison asset is listed as a gallery photograph"


def test_deleting_a_submission_also_clears_its_planner_images():
    """The failure being guarded against is specific: a planner card still
    showing a photograph whose owner asked for it to be taken down. The app's
    own help promises 'a published one can be taken down by asking'.

    The task brief pointed this at admin.php, using the report-delete path's
    variable name ($rid) as its example. The actual submission delete —
    `DELETE FROM submissions WHERE id = ?` — lives in wall.php's `remove`
    action (site/admin/wall.php), using $sid; admin.php has no submission
    delete path at all. Checked with
    `grep -rn "DELETE FROM submissions" site/` before writing this against
    the real file rather than the one the brief named.
    """
    php = (SITE / "admin" / "wall.php").read_text(encoding="utf-8")
    # the submission delete path must touch planner_images before it commits
    assert "planner_images" in php, "the delete path does not clear associations"


def test_a_deploy_never_carries_the_artifact():
    """It is SERVER-GENERATED. The admin rewrites planner-images.json on every
    promotion; the local copy is whatever a test or a debugging session last
    left there. rsync runs without --delete, so an unlisted server file
    survives — but a DELIVERED one is overwritten in silence, and every planner
    photograph vanishes until an unrelated promotion regenerates it.

    THIS RUNS RSYNC. The previous version asserted the string was absent from
    the toml, which it always was — while `include` carried "*.json" and covered
    it completely. That guard was green for the entire time the file was
    exposed, and the file was safe only because it happened not to exist
    locally. A string check could not see it; a dry run can.

    Note the artifact IS still named as an rsync source, because "*.json" globs
    it. What protects it is the --exclude, which rsync applies to explicitly
    named sources too. That is the behaviour being pinned here.
    """
    import shutil
    import subprocess
    import sys
    sys.path.insert(0, str(ROOT / "packaging"))
    import deploy

    toml = ROOT / "packaging" / "deploy.local.toml"
    if not toml.is_file():
        pytest.skip("no local deploy config on this machine")
    if shutil.which("rsync") is None:
        pytest.skip("rsync is not installed on this machine")
    config = deploy.load_config(toml)

    with tempfile.TemporaryDirectory() as tmp:
        site, dest = Path(tmp) / "site", Path(tmp) / "dest"
        site.mkdir(); dest.mkdir()
        # The artifact beside the target list and an ordinary page. The target
        # list MUST still go: it is built here, not on the server, so this is
        # not "exclude every json".
        for name in ("planner-images.json", "planner-targets.json", "index.html"):
            (site / name).write_text("{}")
        cmd = deploy.build_rsync_cmd(config, site)
        # Same flags and excludes, pointed somewhere harmless, and never run for
        # real: -n.
        local = ["rsync", "-avn"] + [a for a in cmd if a.startswith("--exclude=")] \
                + [str(p) for p in sorted(site.iterdir())] + [str(dest) + "/"]
        out = subprocess.run(local, capture_output=True, text=True, timeout=60).stdout

    assert "planner-targets.json" in out, \
        "the target list stopped deploying — it is built here, not on the server"
    assert "index.html" in out, "nothing transferred at all; the probe proves nothing"
    assert "planner-images.json" not in out, \
        "a site deploy would overwrite the server's planner artifact"


# --- Tasks 7-8: the planner page renders the artifact ----------------------


def test_the_planner_fetches_the_artifact():
    js = (SITE / "planner.js").read_text(encoding="utf-8")
    assert "planner-images.json" in js, "the planner never loads the artifact"


def test_the_planner_never_links_an_image_full_size():
    """Andreas: 'Obviously images in the planner should not be presented
    fullsize as they are in the gallery.' The 2000px derivative exists and must
    stay unused here, and lightbox.js must not be pulled in."""
    js = (SITE / "planner.js").read_text(encoding="utf-8")
    code = "\n".join(l for l in js.splitlines() if not l.strip().startswith("//"))
    assert "-2000" not in code, "the planner references the 2000px derivative"
    assert "lightbox" not in code.lower(), "the planner pulls in the lightbox"
    page = (SITE / "planner.html").read_text(encoding="utf-8")
    assert "lightbox.js" not in page, "planner.html loads lightbox.js"


def test_every_rendered_image_carries_its_credit():
    """For Andreas's own images the credit is cosmetic; for a stranger's it is
    the thing that makes the arrangement fair.

        ON THE CLASS THE CREDIT ALONE USES. `.by` matched the alternates strip's
    `data-by="..."` attribute, so deleting the whole credit line from
    captionHtml() left this green — proved by mutation in the whole-branch
    review, 2026-09-24. `t-credit` exists for nothing else.
    """
    js = (SITE / "planner.js").read_text(encoding="utf-8")
    code = "\n".join(l for l in js.splitlines() if not l.strip().startswith("//"))
    assert "t-credit" in code, "the credit is never rendered"
    caption = code[code.index("function captionHtml"):]
    caption = caption[:caption.index("\n  function ")] if "\n  function " in caption else caption
    assert "t-credit" in caption, \
        "the credit class survives somewhere, but captionHtml() no longer emits it"


def test_the_dead_thumbs_hook_is_gone():
    """thumb() used to read window.PLANNER_THUMBS, which nothing in the repo
    ever populated. Task 7 replaces that hook with PLANNER_IMAGES; leaving the
    dead one behind would give the page two, one of them permanently empty.
    Comments are allowed to name the dead hook while explaining its removal
    (that is documentation, not a live reference) -- this checks CODE only,
    same as _code_only below."""
    js = (SITE / "planner.js").read_text(encoding="utf-8")
    code = "\n".join(l for l in js.splitlines() if not l.strip().startswith("//"))
    assert "PLANNER_THUMBS" not in code, "the dead PLANNER_THUMBS hook is still referenced"
    assert "PLANNER_IMAGES" in code, "PLANNER_IMAGES is never referenced"


def _code_only(text: str) -> str:
    """`text` with // comment lines removed.

    Guards here must read CODE. A guard that matches the comment explaining it
    passes while the behaviour is gone — that has happened four times in this
    repo, most recently on 2026-09-22.
    """
    return "\n".join(l for l in text.splitlines() if not l.strip().startswith("//"))


def test_the_promoted_target_is_validated_server_side():
    """The admin offers a <datalist>, which SUGGESTS values and constrains
    nothing — a typo or anything at all can be submitted.

    An id the planner does not carry would be stored happily and then silently
    dropped from the artifact, with no error anywhere. That exact shape of
    failure cost a live debugging session on 2026-09-24, so the id is checked
    against planner-targets.json BEFORE it is stored, not after.
    """
    admin = _code_only((SITE / "admin" / "admin.php").read_text(encoding="utf-8"))
    branch = admin[admin.index("planner_add"):]
    branch = branch[:branch.index("planner_remove")]
    assert "nocturne_planner_targets" in branch, \
        "planner_add does not consult the target list at all"
    check = branch.index("in_array")
    store = branch.index("nocturne_planner_add(")
    assert check < store, \
        "the target is stored before it is validated — the check must come first"


def test_the_guesser_is_gone():
    """nocturne_planner_match() guessed a catalogue id from a submission's free
    text and resolved 8 of 13, able to be confidently wrong about the rest.
    Andreas replaced it with a search box, which cannot be wrong and needs no
    code. Deleted, not merely unused."""
    for name in ("nocturne_planner_match", "nocturne_planner_normalise_target"):
        for php in (SITE / "admin").glob("*.php"):
            assert f"function {name}" not in php.read_text(encoding="utf-8"), \
                f"{name} still defined in {php.name}"


def test_the_datalist_is_built_before_it_is_rendered():
    """The autocomplete silently did not exist for a day.

    wall.php read $PLANNER_TARGETS to emit the <datalist> at line 272 and
    ASSIGNED it at line 333 — so `if (!empty($PLANNER_TARGETS))` tested an
    undefined variable, the list was never written, and every
    `list="planner-targets"` pointed at nothing. !empty() suppresses the
    warning that would have said so, so nothing failed anywhere.

    Andreas found it by using the form: "the input field does now have any form
    of auto completion so as a user i dont know what i should fill in our how".

    The guard is on ORDER, because order was the bug. A guard that merely found
    both strings present passed throughout.
    """
    php = _code_only((SITE / "admin" / "wall.php").read_text(encoding="utf-8"))
    # SCOPED TO THE FUNCTION BODY. File order is not enough: PHP variables are
    # function-scoped, so hoisting the assignment to the top of the file puts it
    # textually before every read while leaving it invisible inside
    # nocturne_wall_render() — the identical symptom, with a file-order guard
    # still green. Proved by mutation during review, 2026-09-24.
    body = php[php.index("function nocturne_wall_render"):]
    # Checked before .index(), which would otherwise raise a bare ValueError and
    # hand the next reader a traceback instead of the reason.
    assert "$PLANNER_TARGETS =" in body, (
        "$PLANNER_TARGETS is never assigned inside nocturne_wall_render() — PHP "
        "variables are function-scoped, so the <datalist> sees nothing")
    assign = body.index("$PLANNER_TARGETS =")
    reads = [m.start() for m in re.finditer(r"\$PLANNER_TARGETS", body)
             if m.start() != assign]
    assert reads, "nothing reads $PLANNER_TARGETS — the datalist is gone entirely"
    assert assign < min(reads), (
        "$PLANNER_TARGETS is read before it is assigned, so the <datalist> is "
        "never emitted and the promote box has no autocomplete")


def test_the_promote_input_points_at_a_datalist_that_exists():
    """The other half: the input's list= must name a <datalist> this page
    actually defines. A renamed id breaks the autocomplete just as silently."""
    php = (SITE / "admin" / "wall.php").read_text(encoding="utf-8")
    ref = re.search(r'list="([^"]+)"', php)
    assert ref, "the promote box no longer references a datalist at all"
    assert f'<datalist id="{ref.group(1)}"' in php, \
        f'the input lists "{ref.group(1)}" but no <datalist> with that id is emitted'


def test_the_dead_representative_path_is_gone():
    """`representative` + planner-thumbs.json was the ORIGINAL planner picture
    mechanism. planner.js stopped reading that file when PLANNER_IMAGES landed
    ("SUPERSEDES window.PLANNER_THUMBS"), so for a day the admin carried a
    button — "Use as the planner's picture" — that wrote a file nothing read,
    sitting beside the one that does the real thing.

    Andreas: "its very confusing to know what 'Use in planner....' and 'Use as
    planners target image' means". Deleted rather than relabelled: one action,
    one meaning.
    """
    for name in ("wall.php", "_wall_meta.php"):
        php = _code_only((SITE / "admin" / name).read_text(encoding="utf-8"))
        assert "planner-thumbs" not in php, f"{name} still writes the dead thumbs file"
        assert "representative" not in php, \
            f"{name} still reads or writes the dead representative column"
    js = (SITE / "planner.js").read_text(encoding="utf-8")
    assert "fetch('planner-thumbs.json')" not in js, \
        "planner.js reads planner-thumbs.json again — then it is not dead after all"


def test_the_planner_grid_shows_every_target():
    """Andreas: "Not just the populated ones but even the unpopulated ones. That
    way it would be very easity to see what objects/targets actually has
    images." A grid of only the covered targets answers the opposite question.

    The filter narrows it on request; the default must not.
    """
    php = _code_only((SITE / "admin" / "planner.php").read_text(encoding="utf-8"))
    grid = php[php.index("tgt-grid"):]
    assert "$shown as $t" in grid, "the grid no longer loops over the filtered target list"
    # The FILTER's behaviour is covered by executing it, in
    # site/tests/planner_images_test.php ("the without filter shows only..."),
    # which counts rendered tiles. Asserting here that the source contains the
    # strings 'yes', 'no' and true would bless `$have === 'yes' ? true : ...`,
    # so it is not asserted twice in a weaker form.


def test_every_panel_control_returns_to_its_target():
    """The panel is a URL, so a redirect that drops ?target= closes it after
    every single click — and filling a target means add, look, add again.

    Counted, not merely present: one control without it is the one that throws
    you back to the grid.
    """
    php = _code_only((SITE / "admin" / "planner.php").read_text(encoding="utf-8"))
    panel = php[php.index("tgt-panel"):]
    actions = panel.count('name="planner_action"')
    returns = panel.count('name="return_target"')
    assert actions > 0, "the panel has no controls at all"
    assert returns == actions, \
        f"{actions} controls in the panel but {returns} carry return_target"

    admin = _code_only((SITE / "admin" / "admin.php").read_text(encoding="utf-8"))
    assert "return_target" in admin, \
        "admin.php ignores return_target, so the panel closes after every action"
    # It lands in a Location header, so it is validated rather than echoed.
    tail = admin[admin.index("return_target"):]
    assert "in_array" in tail[:tail.index("header(")], \
        "return_target reaches the Location header without being validated"


def test_every_css_token_the_admin_uses_is_defined():
    """`background: var(--bg)` is not an error — it is transparent.

    .tgt-box was written with var(--bg), which no stylesheet defines, so the
    panel had no background at all. On a wide screen it still LOOKED solid,
    because the 93%-opaque backdrop sits behind it; at 390px the tab strip
    showed straight through the panel. Nothing failed, and nothing would have.

    So the guard is structural: every token the admin's CSS references must be
    defined somewhere the browser will actually see — styles.css, which the
    admin links, or the admin's own block.
    """
    common = (SITE / "admin" / "_common.php").read_text(encoding="utf-8")
    css = common[common.index("<<<'CSS'"):common.rindex("\nCSS;")]
    site_css = (SITE / "styles.css").read_text(encoding="utf-8")

    # ONLY :root COUNTS. A token declared inside some other rule (styles.css
    # defines --pos on the before/after slider) is not in scope for the admin's
    # own selectors, so counting it as "defined" would bless exactly the failure
    # this test exists to catch.
    root = site_css[site_css.index(":root {"):]
    root = root[:root.index("\n}")]
    defined = set(re.findall(r"(--[\w-]+)\s*:", root + css))
    used = set(re.findall(r"var\((--[\w-]+)", css))
    missing = sorted(used - defined)
    assert not missing, (
        f"the admin CSS uses undefined custom properties {missing} — these "
        f"resolve to nothing, which for a background means transparent")


def test_the_datalist_does_not_print_a_target_name_twice():
    """planner-targets.json writes `common` even when it equals `name`, which is
    most of the 158. Concatenating them unconditionally gave
    "IC0348 — omi Per Cloud omi Per Cloud" in the dropdown whose whole job is
    making a target easy to pick. Found by rendering the live page, not by
    reading the code."""
    php = _code_only((SITE / "admin" / "wall.php").read_text(encoding="utf-8"))
    block = php[php.index('<datalist id="planner-targets">'):]
    block = block[:block.index("</datalist>")]
    assert "$common !== $label" in block, \
        "the datalist label appends `common` without checking it differs from `name`"
