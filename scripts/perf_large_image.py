"""Where does the time go on a large image? Run this before optimising anything.

    .venv/bin/python scripts/perf_large_image.py [master.fits]

Baseline on a 39.5 Mpx M 31 mosaic (8548 x 4618), 2026-08-16:

    one live-preview tick   2.661 s  ->  0.541 s   after sampling the statistics
      apply_stretch           2.176  ->  0.317
      histogram               0.292  ->  0.033
      to_rgb8                 0.123  ->  0.124
    opening the master     12.396 s  ->  5.555 s

A regression here is a number, not a feeling. If a change puts a full-frame
median back, this says so.

Drives the REAL MainWindow, not isolated functions, because the question is not
"how fast is autostretch" but "what does one slider tick cost". A live preview
runs a chain — reload the pre-stage state, apply the step, clip, convert to
uint8, wrap in a QImage, hand it to Qt, rebuild the histogram, recompute the
clipping line — and any of those could dominate.

Changes nothing. Uses a temporary settings path so the app's real snapshot cache
is never touched.
"""
import os
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, "/Volumes/Work/Code/Editor")

import numpy as np  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

MASTER = sys.argv[1] if len(sys.argv) > 1 else (
    "/Volumes/Work2/Images/Astro/Work/M 31_mosaic_sub/lights/M31_302x10s_50min.fits")


class T:
    def __init__(self, label, store):
        self.label, self.store = label, store

    def __enter__(self):
        self.t = time.perf_counter()
        return self

    def __exit__(self, *a):
        self.store.append((self.label, time.perf_counter() - self.t))


def main():
    app = QApplication.instance() or QApplication([])
    from nocturne.core.autostretch import neutral_stretch, _TARGET_BG
    from nocturne.core.histogram import histogram
    from nocturne.core.image import AstroImage
    from nocturne.core.stretch import apply_stretch
    from nocturne.ui.main_window import MainWindow
    from nocturne.ui.preview import rgb_to_qimage, to_rgb8

    tmp = tempfile.mkdtemp(prefix="nocturne_perf_")
    win = MainWindow(settings_path=os.path.join(tmp, "settings.json"),
                     check_updates=False)
    win._async_enabled = False
    win.resize(1600, 1000)

    times = []
    with T("open the master (decode + first snapshot)", times):
        win.open_fits(MASTER)
    img = win.project.current()
    h, w = img.data.shape[:2]
    print(f"{os.path.basename(MASTER)}  {w} x {h} = {h*w/1e6:.1f} Mpx  "
          f"({img.data.nbytes/1e6:.0f} MB per copy)\n")

    # --- the chain one live-preview tick runs -------------------------------
    with T("  state_at()  reload the pre-stage image", times):
        base = win.project.state_at(0)
    with T("  apply_stretch()  the actual maths", times):
        out = apply_stretch(base, 0.5).data
    with T("  np.clip + float32 copy", times):
        clipped = np.clip(out, 0.0, 1.0).astype(np.float32)
    shown = AstroImage(clipped, is_linear=False)
    with T("  to_rgb8()  float -> uint8", times):
        rgb = to_rgb8(shown)
    with T("  QImage wrap + copy", times):
        qim = rgb_to_qimage(rgb)
    with T("  canvas set_image (QPixmap + scene)", times):
        win.image_view.set_image(qim)
    with T("  histogram", times):
        histogram(shown)
    with T("  clipping line", times):
        win._update_clipping_line()

    print("ONE LIVE-PREVIEW TICK, broken down")
    total = 0.0
    for label, dt in times:
        if label.startswith("  "):
            total += dt
        print(f"  {label:<46}{dt:8.3f} s")
    print(f"  {'TOTAL for one slider tick':<46}{total:8.3f} s")
    print(f"  the debounce is 90 ms, so a drag queues these back to back\n")

    # --- what a linear image costs to merely display -------------------------
    d2 = []
    with T("autostretch alone (linear display)", d2):
        neutral_stretch(img.data, _TARGET_BG)
    with T("to_rgb8 on a LINEAR image (stretch + convert)", d2):
        to_rgb8(img)
    print("DISPLAYING A LINEAR IMAGE (every repaint before the stretch step)")
    for label, dt in d2:
        print(f"  {label:<46}{dt:8.3f} s")

    # --- how much of that is wasted on pixels nobody sees --------------------
    print("\nHOW MUCH OF THIS IS VISIBLE?")
    vw, vh = win.image_view.viewport().width(), win.image_view.viewport().height()
    print(f"  canvas viewport            {vw} x {vh} = {vw*vh/1e6:.2f} Mpx")
    print(f"  image                      {w} x {h} = {h*w/1e6:.2f} Mpx")
    print(f"  ratio                      {(h*w)/(vw*vh):.0f}x more pixels processed "
          f"than the screen can show")

    # --- committing a step ---------------------------------------------------
    c = []
    with T("run_step (apply + snapshot to disk)", c):
        win._apply_process("stretch", "0.5") if hasattr(win, "_apply_process") else None
    for label, dt in c:
        print(f"\nCOMMITTING A STEP\n  {label:<46}{dt:8.3f} s")

    import shutil
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
