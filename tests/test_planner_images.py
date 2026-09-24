"""Guards for planner target images.

site/ is gitignored and deploys by rsync, so these read the working copy.
"""
import json
import re
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
    py = (ROOT / "packaging" / "build_showcase.py").read_text(encoding="utf-8")
    assert "320" in py, "build_showcase.py does not produce a 320px size"


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


def test_the_artifact_is_not_in_the_deploy_allowlist():
    """It is SERVER-GENERATED. Listing it would let a site publish overwrite it
    with whatever is (not) in the local tree. rsync runs without --delete, so an
    unlisted server-side file survives untouched — the same arrangement
    uploads/ relies on."""
    for name in ("deploy.local.toml", "deploy.example.toml"):
        p = ROOT / "packaging" / name
        if not p.is_file():
            continue
        assert "planner-images.json" not in p.read_text(encoding="utf-8"), \
            f"{name} lists planner-images.json; a deploy would clobber it"


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
    the thing that makes the arrangement fair."""
    js = (SITE / "planner.js").read_text(encoding="utf-8")
    code = "\n".join(l for l in js.splitlines() if not l.strip().startswith("//"))
    assert ".by" in code or "['by']" in code, "the credit is never rendered"


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
