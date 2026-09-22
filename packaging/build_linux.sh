#!/usr/bin/env bash
#
# Build the Linux release: a tarball of the PyInstaller directory.
#
#     packaging/build_linux.sh [git-ref]
#
# Runs ON a Linux machine, in a checkout of this repo. Deliberately a plain
# script with no knowledge of SSH, deploy.py or the website: `deploy.py --linux`
# runs it over SSH on the laptop, and a GitHub Actions runner could run exactly
# the same file without a line changing. Glue belongs in the caller.
#
# WHATEVER MACHINE RUNS THIS SETS THE COMPATIBILITY FLOOR. A PyInstaller binary
# is forward-compatible but not backward: built against glibc 2.39 (Ubuntu
# 24.04) it will not start on 22.04. That is a decision, not an accident — it is
# why the build host is an LTS and why upgrading it eagerly is the wrong move.
#
# Tarball rather than AppImage, chosen 2026-09-18: it is what GraXpert itself
# ships, it needs no extra tooling, and an AppImage is a second failure mode to
# debug remotely. Revisit when somebody actually asks.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

REF="${1:-}"
if [ -n "$REF" ]; then
    # Fetch first: the tag being built was very likely pushed seconds ago.
    git fetch --quiet --tags origin
    git checkout --quiet "$REF"
fi

VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' nocturne/__init__.py)"
[ -n "$VERSION" ] || { echo "could not read __version__ from nocturne/__init__.py" >&2; exit 1; }
ARCH="$(uname -m)"
NAME="Nocturne-${VERSION}-linux-${ARCH}"

echo "building $NAME"
echo "  ref      $(git rev-parse --short HEAD)  $(git log -1 --pretty=%s | cut -c1-60)"
echo "  glibc    $(ldd --version | head -1 | awk '{print $NF}')  <- the floor this binary sets"
echo "  python   $(.venv/bin/python -V 2>&1)"

# PyInstaller is not a runtime dependency and is deliberately absent from
# pyproject's extras, so the build host installs it here rather than every
# contributor carrying it.
.venv/bin/python -m pip install --quiet --upgrade pyinstaller
.venv/bin/python -m pip install --quiet -e ".[dev]"

rm -rf build dist
.venv/bin/pyinstaller packaging/nocturne.spec --noconfirm --clean --log-level WARN

[ -x "dist/Nocturne/Nocturne" ] || { echo "no executable at dist/Nocturne/Nocturne" >&2; exit 1; }

# The smoke test that matters: does the thing we just built actually start?
# --check-network returns before any window is created, so it works headless and
# still exercises the bundle's Python, its imports and its certificate path.
echo "  smoke    $(dist/Nocturne/Nocturne --check-network 2>&1 | tail -1)"

# BLOCKING, unlike the network one. imagecodecs imports its codecs dynamically
# so PyInstaller collected none of them, and every Linux tarball from v0.35.0 to
# v0.39.0 shipped one of its sixty extension modules — star separation failed
# for every user without RC-Astro, after the whole run had already happened.
# Nothing local or flaky here: the codecs are in the tarball or they are not.
if ! dist/Nocturne/Nocturne --check-codecs; then
  echo "the build cannot decode a compressed TIFF — star separation and opening a user's TIFF would fail for every user" >&2
  exit 1
fi

tar -czf "dist/${NAME}.tar.gz" -C dist Nocturne
echo "  artifact dist/${NAME}.tar.gz  ($(du -h "dist/${NAME}.tar.gz" | cut -f1))"
echo "  sha256   $(sha256sum "dist/${NAME}.tar.gz" | cut -d' ' -f1)"
