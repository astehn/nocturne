"""Where the training data lives — in ONE place.

Twenty-nine hardcoded literals pointing at the old Work2 volume, across fifteen
files, became
dead on 2026-08-25 when that disk failed. Every one of them was a default
argument that still parses, still runs, and fails only when something tries to
read it — which for `nightly.py` meant building a dataset for over two hours
before dying on a missing directory.

So the roots live here and nothing else spells them out. Overridable by
environment so a second machine, or a restore onto a different volume, is a
variable rather than a patch.

DELIBERATELY NOT THE NAS. Andreas, 2026-08-30: "I don't want under any
circumstances that the data on the NAS is changed — use the local data in
/Volumes/Work/Astro and then copy what you need from there." The NAS holds the
only surviving copy of an archive that has already been lost once; training
writes gigabytes and must not point at it even by accident. `check_splits.refuse_nas`
enforces that for the reader; this module simply never names it.
"""
from __future__ import annotations

import os
from pathlib import Path

# The local archive of raw subs, recovered off the Seestar after the disk loss.
ARCHIVE = Path(os.environ.get("NOCTURNE_ARCHIVE", "/Volumes/Work/Astro"))

# Everything training MAKES. Kept beside the archive on the same 931 GB volume
# (543 GB free as of 2026-08-30) rather than inside it, so a stray glob for
# "*_sub" or "*.fit" over the archive cannot pick up generated data.
WORK = Path(os.environ.get("NOCTURNE_TRAINING_WORK", "/Volumes/Work/AstroTraining"))

PAIRS = WORK / "TrainingPairs"      # ladder pairs, and the gate's held-out pairs
DATASETS = WORK / "datasets"        # injection tiles
RUNS = WORK / "denoise_runs"        # checkpoints, exports, reports


# The deep-end reference: the one real deep stack on this machine, checked
# truth-free because no ground truth for it exists — it IS the deepest stack
# there is, and it is the master the 2026-08-22 model damaged.
#
# It was a 405-frame stack that died with Work2. Rebuilt from the 460 subs that
# survived on the Seestar, so the DEPTH CHANGED and any threshold calibrated
# against 405 has to be re-measured, not carried over.
M8_MASTER = WORK / "reference" / "M8_460x10s.fits"
M8_DEPTH = 460


def ensure() -> None:
    """Create the output roots. The archive is NOT created — if it is missing
    that is a mounting problem and inventing an empty directory would turn it
    into a confusing 'no groups found' hours later."""
    for p in (WORK, PAIRS, DATASETS, RUNS, M8_MASTER.parent):
        p.mkdir(parents=True, exist_ok=True)


def describe() -> str:
    lines = [f"archive   {ARCHIVE}  {'ok' if ARCHIVE.is_dir() else 'MISSING'}"]
    for name, p in (("work", WORK), ("pairs", PAIRS),
                    ("datasets", DATASETS), ("runs", RUNS)):
        lines.append(f"{name:<10}{p}  {'ok' if p.is_dir() else 'not created yet'}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(describe())
