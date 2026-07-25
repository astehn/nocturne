---
name: deploy
description: Cut a full Nocturne release — version bump, changelog, PyInstaller build, GitHub push + release with the binary, and a safe website rsync to the VPS. One approval gate, then hands-off.
---

# Deploy Nocturne

Run the release pipeline in `packaging/deploy.py`. One human gate (approve
notes + version); tests + a successful build are automatic gates before
anything public.

## Steps

1. **Preflight.** Run `.venv/bin/python packaging/deploy.py --preflight`.
   If it exits non-zero, surface the exact reason and STOP (on main, clean
   tree, in sync with origin, tests green, gh authed, ssh + passwordless
   sudo reachable). Do not proceed.

2. **Draft the release notes.** Get the range with
   `git describe --tags --abbrev=0 --match 'v*'` then
   `git log <tag>..HEAD --pretty=%s`. Draft a one-line headline and
   categorized Added / Changed / Fixed bullets in the CHANGELOG house style
   (see `CHANGELOG.md`). `deploy.draft_notes_from_log` gives a first pass;
   refine it with judgment — real user-facing prose, not raw commit subjects.

3. **Suggest the version.** Default to a minor bump of the last tag
   (`0.3.0 → 0.4.0`); the user may override to any `x.y.z`.

4. **Flag hand-curated pages.** If there are new features (non-empty Added),
   tell the user these may need a manual edit BEFORE approving, and offer to
   open them: `site/index.html` (`#features`), `README.md` (`## Features`),
   `site/guide.html`. The skill does not auto-write these.

5. **THE GATE.** Show the drafted notes, the version, the files that will
   change, and what will publish (GitHub push + release + live-site rsync).
   Get explicit approval. This approval authorizes the whole hands-off tail.

6. **Rehearse (optional but recommended).** Write the approved notes to a
   temp JSON file `{"headline","added","changed","fixed"}` and run
   `.venv/bin/python packaging/deploy.py --version <v> --notes-json <path> --dry-run`.
   Show the printed plan.

7. **Publish.** Run the same command WITHOUT `--dry-run`. Stream its output.
   On success, report the release URL (`gh release view v<v> --json url -q .url`)
   and http://nocturne.stehn.com. If a remote step fails mid-sequence, surface
   the script's finish-by-hand command verbatim — do NOT retry blindly (a cut
   release / pushed tag cannot be silently rolled back).
