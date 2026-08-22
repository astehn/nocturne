#!/usr/bin/env python3
"""CLI entry point for Nocturne's automated training-pair generator."""

from pathlib import Path
import sys

# Make ``python scripts/generate_training_pairs.py`` work from a source
# checkout as well as ``python -m nocturne.training.pairs``.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nocturne.training.pairs import main


if __name__ == "__main__":
    raise SystemExit(main())
