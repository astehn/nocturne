"""Run a real mosaic and report what a go/no-go decision needs.

Usage:
  .venv/bin/python scripts/mosaic_benchmark.py <subs-dir> <out-dir>

Prints panel count, canvas size, integration, dropped frames, and star FWHM at
the centre and the four corners. The corner numbers are the point: astrometric
placement is supposed to hold across the field where chain registration would
leave ~1 px median and ~2 px at p90. Corners close to centre means it held.

Compare the output against Siril 1.4.4's astrometric mosaic and the device's own
Stacked_373_mosaic.
"""
import glob
import os
import sys

import numpy as np
import sep

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nocturne.stacking.mosaic import MosaicOptions, run_mosaic   # noqa: E402

ASTAP = "/Applications/ASTAP.app/Contents/MacOS/astap"


def fwhm_in(lum, box):
    """Median FWHM of the stars in a box, or nan if too few to be meaningful."""
    y0, y1, x0, x1 = box
    cut = np.ascontiguousarray(lum[y0:y1, x0:x1], dtype=np.float32)
    try:
        bkg = sep.Background(cut)
        obj = sep.extract(cut - bkg, 5.0, err=bkg.globalrms)
    except Exception:
        return float("nan")
    if len(obj) < 5:
        return float("nan")
    return float(np.median(2.3548 * np.sqrt(np.abs(obj["a"] * obj["b"]))))


def main(subs_dir, out_dir):
    paths = sorted(glob.glob(os.path.join(subs_dir, "**", "*.fit"), recursive=True))
    paths = [p for p in paths if "process" not in p]
    print(f"{len(paths)} subs from {subs_dir}")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "mosaic.fits")

    def progress(i, n, label):
        print(f"  {label} ({i}/{n})", flush=True)

    res = run_mosaic(MosaicOptions(include=paths, output_path=out,
                                   astap_path=ASTAP), on_progress=progress)

    print(f"\npanels {res.panel_count} | frames {res.frame_count} | "
          f"{res.integration_seconds / 60:.0f} min | dropped {len(res.dropped)}")
    print(f"canvas {res.image.data.shape[1]} x {res.image.data.shape[0]}")

    lum = res.image.data.mean(axis=2)
    h, w = lum.shape
    s = min(h, w) // 6
    print("\nFWHM (px) — did the geometry hold across the field?")
    for name, box in (("centre", (h // 2 - s, h // 2 + s, w // 2 - s, w // 2 + s)),
                      ("top-left", (0, 2 * s, 0, 2 * s)),
                      ("top-right", (0, 2 * s, w - 2 * s, w)),
                      ("bottom-left", (h - 2 * s, h, 0, 2 * s)),
                      ("bottom-right", (h - 2 * s, h, w - 2 * s, w))):
        print(f"  {name:<13} {fwhm_in(lum, box):.2f}")

    if res.dropped:
        print(f"\ndropped ({len(res.dropped)}):")
        for path, reason in res.dropped[:20]:
            print(f"  {os.path.basename(path)}: {reason}")
        if len(res.dropped) > 20:
            print(f"  ... and {len(res.dropped) - 20} more")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        raise SystemExit(2)
    main(sys.argv[1], sys.argv[2])
