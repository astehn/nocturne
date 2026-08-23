"""Ship a staged model. Run by a person, after looking at the morning report.

Deliberately separate from nightly.py: the runner passed its own gate on
2026-08-23 and shipped a model that damaged a real master anyway. The gate is
better now but still blind to non-chroma damage, so the last step is a human
one.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

_MODELS = Path(__file__).resolve().parent.parent / "nocturne" / "assets" / "models"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run", required=True, help="run directory containing staged/")
    ap.add_argument("--sensor", default="s30")
    ap.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    args = ap.parse_args(argv)

    staged = Path(args.run) / "staged"
    onnx = staged / f"denoise_{args.sensor}_v1.onnx"
    if not onnx.is_file():
        print(f"nothing staged at {onnx}", file=sys.stderr)
        return 2

    dest = _MODELS / onnx.name
    print(f"{onnx}\n  -> {dest}")
    if dest.is_file():
        print(f"  (replacing {dest.stat().st_size} bytes currently shipped)")
    if not args.yes:
        if input("promote? [y/N] ").strip().lower() != "y":
            print("aborted")
            return 1

    dest.parent.mkdir(parents=True, exist_ok=True)
    # Sidecar first, .onnx last: the .onnx is the file the app checks for, so
    # it must never appear ahead of the metadata that describes it. Each copy
    # goes via a dot-prefixed temp name that the app's *.onnx/*.json lookups
    # cannot match, then os.replace -- atomic on the same filesystem.
    for src in (staged / f"denoise_{args.sensor}_v1.json", onnx):
        if not src.is_file():
            continue
        tmp = dest.parent / f".{src.name}.tmp{os.getpid()}"
        try:
            shutil.copyfile(src, tmp)
            os.replace(tmp, dest.parent / src.name)
        finally:
            if tmp.exists():
                tmp.unlink()
    print("promoted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
