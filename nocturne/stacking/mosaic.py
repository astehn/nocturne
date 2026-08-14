"""Turning many pointings into one canvas.

`run_stack` registers every frame to one reference and integrates onto a canvas
the shape of that frame, so a panel that does not overlap the reference has no
transform to find. This module groups the subs by pointing, stacks each group
with the ordinary stacker, and places the resulting masters by their plate
solutions — geometry between panels comes from astrometry rather than star
matching, because a similarity transform cannot represent the mapping between
two gnomonic projections, and the error it leaves grows with panel separation
(measured on real M 31 panels: 0.52 px against a homography's 0.16 px).
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass

from ..core.fits_io import load_fits
from .stacker import StackOptions, run_stack


@dataclass(frozen=True)
class Panel:
    centre_ra: float
    centre_dec: float
    paths: tuple[str, ...]


def _separation_deg(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Small-angle sky separation. Exact enough below a few degrees, which is
    every mosaic a Seestar can shoot, and it keeps the maths readable."""
    dec_mid = math.radians((a[1] + b[1]) / 2.0)
    dra = (a[0] - b[0]) * math.cos(dec_mid)
    return math.hypot(dra, a[1] - b[1])


def discover_panels(pointings: dict[str, tuple[float, float]],
                    max_spread_deg: float) -> list[Panel]:
    """Group frames into panels by COMPLETE LINKAGE: no panel may span more than
    `max_spread_deg` from end to end.

    Single linkage — join if within the threshold of ANY member — was tried
    first and is unusable here. It chains: on the real 392-sub M 31 set at the
    0.56 deg threshold it produced TWO panels, one of them holding 390 frames,
    because a dense grid of overlapping pointings always offers some pair close
    enough to bridge. Nor is there a threshold that works, since a dithered
    panel spans 0.16-0.37 deg while neighbouring panels sit 0.73 deg apart, and
    chaining bites long before that gap. Bounding the DIAMETER instead forbids
    the bridge outright: two panels 0.73 deg apart cannot form a group of spread
    0.56. The same data then yields 39 panels of 16-25 subs.

    Order independence still matters — a greedy centroid gave 22 panels and 29
    on one set depending only on iteration order — so paths are sorted before
    clustering and every tie is therefore broken the same way whatever order the
    caller passes.

    Header RA/DEC is the mount's COMMANDED pointing, useless for measuring
    dither (99% of consecutive frames report no movement) and exactly right
    here: the mount's intent is what defines a panel.
    """
    import numpy as np
    from scipy.cluster.hierarchy import fcluster, linkage
    from scipy.spatial.distance import pdist

    paths = sorted(pointings)
    if not paths:
        # nothing to group: frames with no pointing cards, or no frames at all.
        # pdist on an empty array raises, and the UI calls this on whatever the
        # folder happens to hold.
        return []
    if len(paths) == 1:
        ra, dec = pointings[paths[0]]
        return [Panel(ra, dec, (paths[0],))]

    # tangent-plane projection about the median declination, so plain euclidean
    # distance is the sky separation — the same small-angle assumption
    # _separation_deg makes, and valid over any field a Seestar can shoot
    decs = [pointings[p][1] for p in paths]
    cos_ref = math.cos(math.radians(sum(decs) / len(decs)))
    xy = np.array([[pointings[p][0] * cos_ref, pointings[p][1]] for p in paths])

    labels = fcluster(linkage(pdist(xy), method="complete"),
                      t=max_spread_deg, criterion="distance")

    groups: dict[int, list[str]] = {}
    for p, label in zip(paths, labels):
        groups.setdefault(int(label), []).append(p)

    panels = []
    for members in groups.values():
        ras = [pointings[m][0] for m in members]
        decs = [pointings[m][1] for m in members]
        panels.append(Panel(sum(ras) / len(ras), sum(decs) / len(decs),
                            tuple(sorted(members))))
    # deterministic output order: north first, then east
    return sorted(panels, key=lambda p: (-p.centre_dec, p.centre_ra))


@dataclass
class PanelStack:
    panel: Panel
    master_path: str
    peak: float
    frame_count: int
    integration_seconds: float


def read_pointings(paths: list[str]) -> dict[str, tuple[float, float]]:
    """Commanded RA/DEC per frame, in degrees.

    Frames without a numeric pointing are omitted rather than guessed at. The
    loader prefers OBJCTRA/OBJCTDEC over RA/DEC and those are sexagesimal
    strings on some files; a frame that cannot be placed belongs in no panel,
    and putting it in the wrong one would corrupt a stack rather than lose a
    frame.

    HEADER ONLY. `load_fits` decodes and debayers the whole frame: 191 ms against
    `getheader`'s 1 ms — 306x, or 75 seconds of dead air on a 392-sub set before
    the first progress line appears. Grouping needs two cards. `_parse_metadata`
    is reused rather than re-reading the cards here so the OBJCTRA-before-RA
    precedence keeps exactly one definition.
    """
    from astropy.io import fits

    from ..core.fits_io import _parse_metadata

    out = {}
    for p in paths:
        try:
            header = fits.getheader(p)
        except Exception:
            continue
        meta = _parse_metadata(header, int(header.get("NAXIS2", 0) or 0),
                               int(header.get("NAXIS1", 0) or 0))
        try:
            ra, dec = float(meta["ra"]), float(meta["dec"])
        except (KeyError, TypeError, ValueError):
            continue
        out[p] = (ra, dec)
    return out


def stack_panels(panels, workdir, *, method, kappa, min_panel_subs,
                 on_progress=None):
    """Stack each panel with the ORDINARY stacker.

    Grading, sigma-clipping, sky normalization and coverage-aware integration
    all apply per panel for free — which is why this is orchestration rather
    than a second stacker. Returns (stacks, dropped), where dropped is
    (path, reason) for every frame that will not reach the mosaic.
    """
    stacks, dropped = [], []
    for i, panel in enumerate(panels, start=1):
        if len(panel.paths) < min_panel_subs:
            for p in panel.paths:
                dropped.append((p, f"panel has only {len(panel.paths)} subs"))
            continue
        out = os.path.join(workdir, f"panel_{i:02d}.fits")
        if os.path.exists(out):
            # Resuming: the expensive part is already done. master_metadata
            # stores "exposure" as the TOTAL integration and "frames" as the
            # count, so both survive in the file. The peak does not, but it is
            # only a per-panel scale factor and the overlap matching absorbs it.
            meta = load_fits(out, normalize=False).metadata
            stacks.append(PanelStack(
                panel, out, 1.0,
                int(meta.get("frames") or len(panel.paths)),
                float(meta.get("exposure") or 0.0)))
            continue
        if on_progress is not None:
            on_progress(i, len(panels), f"Step 1 of 3 — stacking panel {i}")
        try:
            res = run_stack(StackOptions(method, kappa, list(panel.paths), out))
        except ValueError as exc:
            for p in panel.paths:
                dropped.append((p, f"panel failed to stack: {exc}"))
            continue
        stacks.append(PanelStack(panel, res.output_path, res.peak,
                                 res.frame_count, res.integration_seconds))
        dropped.extend(res.rejected)
    return stacks, dropped


@dataclass
class SolvedPanel:
    stack: PanelStack
    wcs: object
    shape: tuple[int, int]


class CanvasTooLarge(Exception):
    pass


def _astap_solver(astap_path: str):
    """Solve a panel MASTER through the existing ASTAP wrapper.

    Masters rather than subs: a stacked panel is far deeper than a 10 s frame,
    so it solves far more reliably, and it is one solve per panel instead of one
    per sub.
    """
    from ..tools.astap import ASTAP, solve_with_scale_fallback

    astap = ASTAP(astap_path)

    def solve(master_path: str):
        img = load_fits(master_path, normalize=False)
        try:
            res, _source = solve_with_scale_fallback(astap, img, img.metadata,
                                                     img.data.shape[0])
        except OSError:
            # a binary that vanished mid-run is one panel's problem, not the
            # run's; run_mosaic checks up front that it was there to begin with
            return None
        if not res.solved or res.wcs is None:
            return None
        return res.wcs, img.data.shape[:2]

    return solve


def check_astap(astap_path: str) -> None:
    """Fail before any stacking if ASTAP is not usable.

    Mosaic geometry comes from astrometry, so a missing solver is fatal — and
    the benchmark showed what discovering that late costs: every panel stacked,
    twenty minutes spent, then an error. One stat call up front instead.
    """
    if not (astap_path and os.path.isfile(astap_path)
            and os.access(astap_path, os.X_OK)):
        raise ValueError(
            f"mosaic stacking needs ASTAP to place the panels on the sky, and "
            f"there is no runnable solver at {astap_path!r} — set the ASTAP "
            f"path in Settings")


def solve_panels(stacks, astap_path, *, solver=None, on_progress=None):
    """Place each panel on the sky. Panels that will not solve are REPORTED, not
    guessed at — an invented position puts real stars in the wrong sky."""
    solver = solver or _astap_solver(astap_path)
    solved, unsolved = [], []
    for i, s in enumerate(stacks, start=1):
        if on_progress is not None:
            on_progress(i, len(stacks), f"Step 2 of 3 — solving panel {i}")
        got = solver(s.master_path)
        if got is None:
            unsolved.append((s.master_path, "panel could not be solved"))
            continue
        wcs, shape = got
        solved.append(SolvedPanel(s, wcs, shape))
    return solved, unsolved


def global_frame(solved, *, max_megapixels: float = 250.0):
    """A TAN frame covering every panel, tangent at the mosaic centre.

    Tangent at the CENTRE rather than at the first panel: gnomonic distortion
    grows with distance from the tangent point, so centring it halves the worst
    case across the field.
    """
    import numpy as np
    from astropy.wcs import WCS

    ras, decs = [], []
    for p in solved:
        h, w = p.shape
        sky = p.wcs.pixel_to_world_values([0, w, 0, w], [0, 0, h, h])
        ras.extend(np.asarray(sky[0]).ravel())
        decs.extend(np.asarray(sky[1]).ravel())
    ras, decs = np.asarray(ras), np.asarray(decs)

    scale = float(np.sqrt(abs(np.linalg.det(solved[0].wcs.pixel_scale_matrix))))

    wcs = WCS(naxis=2)
    wcs.wcs.crval = [float(ras.mean()), float(decs.mean())]
    wcs.wcs.cdelt = [-scale, scale]
    wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    wcs.wcs.crpix = [1.0, 1.0]

    x, y = wcs.world_to_pixel_values(ras, decs)
    x0, y0 = float(np.floor(x.min())), float(np.floor(y.min()))
    w_px = int(np.ceil(x.max()) - x0) + 1
    h_px = int(np.ceil(y.max()) - y0) + 1

    mp = (w_px * h_px) / 1e6
    if mp > max_megapixels:
        # one decimal, not zero: a limit that prints as "0 megapixels" tells the
        # user nothing about how far over they are
        raise CanvasTooLarge(
            f"the mosaic would be {w_px} x {h_px} px ({mp:.1f} megapixels); "
            f"the limit is {max_megapixels:.1f} megapixels")

    # shift the reference pixel so the canvas starts at (0, 0)
    wcs.wcs.crpix = [1.0 - x0, 1.0 - y0]
    return wcs, (h_px, w_px)


def reproject_panel(data, panel_wcs, global_wcs, out_shape):
    """Resample a panel onto the global frame, and say which pixels it reached.

    Coordinates run canvas -> sky -> panel, which is the direction a resampler
    needs: for every OUTPUT pixel, where in the input did it come from.

    Bilinear, matching `register.warp_to`, so a mosaic and an ordinary stack
    resample alike. Validity is a warped ones-mask on the same 0.999 threshold
    `warp_with_validity` uses, because zero is a legitimate pixel value and
    integration must be able to tell "dark sky" from "this panel did not see
    here".
    """
    import numpy as np
    from scipy.ndimage import map_coordinates

    h, w = out_shape
    yy, xx = np.mgrid[0:h, 0:w]
    sky = global_wcs.pixel_to_world_values(xx.ravel(), yy.ravel())
    px, py = panel_wcs.world_to_pixel_values(sky[0], sky[1])
    # map_coordinates indexes (row, column) — py before px. Reversing these
    # transposes the sky, which is exactly the class of mistake FITS_Y_DOWN was.
    coords = np.array([np.asarray(py).reshape(h, w), np.asarray(px).reshape(h, w)])

    ones = np.ones(data.shape[:2], dtype=np.float32)
    valid = map_coordinates(ones, coords, order=1, mode="constant",
                            cval=0.0) >= 0.999

    if data.ndim == 2:
        out = map_coordinates(data.astype(np.float32), coords, order=1,
                              mode="constant", cval=0.0)
        out = np.where(valid, out, 0.0)
    else:
        out = np.stack(
            [map_coordinates(data[:, :, c].astype(np.float32), coords, order=1,
                             mode="constant", cval=0.0)
             for c in range(data.shape[2])], axis=2)
        out = np.where(valid[:, :, None], out, 0.0)
    return out.astype(np.float32), valid


def match_offsets(layers, valids):
    """A constant per panel, chosen so every overlap agrees as nearly as it can.

    Measured in the OVERLAP, never over the whole frame: panels see different
    objects, so a panel holding a galaxy has a higher median for real reasons
    and matching on that would subtract the signal the user came for.

    Solved over EVERY overlap at once rather than chaining each panel to the
    first neighbour it happens to touch. Real overlaps are mutually
    inconsistent — a panel with a sky gradient implies one offset against its
    left neighbour and another against its right — and chaining satisfies the
    edges it walks while dumping the whole disagreement on the ones it skips.
    Measured on a four-panel ring: four seams at 0.0000 and two at 0.0375.
    Least squares spreads that instead, which is what stops a single seam being
    the visible one.

    This is a weighted graph Laplacian, `L o = b`, with each overlap weighted by
    its area — a bigger shared region is a better measurement. Each connected
    component is anchored on its first panel, so the picture keeps its overall
    level and a panel overlapping nothing keeps its own: there is nothing to
    match it to, and inventing an offset would move real signal.
    """
    import numpy as np

    n = len(layers)
    A = np.zeros((n, n), np.float64)
    b = np.zeros(n, np.float64)
    adjacency = {i: set() for i in range(n)}

    for i in range(n):
        for j in range(i + 1, n):
            both = valids[i] & valids[j]
            area = int(both.sum())
            if area < 50:
                continue
            li, lj = layers[i][both], layers[j][both]
            if li.ndim > 1:
                li, lj = li.mean(axis=-1), lj.mean(axis=-1)
            # want (li + o_i) == (lj + o_j), i.e. o_i - o_j = median(lj) - median(li)
            d = float(np.median(lj) - np.median(li))
            w = float(area)
            A[i, i] += w; A[j, j] += w
            A[i, j] -= w; A[j, i] -= w
            b[i] += w * d
            b[j] -= w * d
            adjacency[i].add(j)
            adjacency[j].add(i)

    offsets = [0.0] * n
    seen = set()
    for root in range(n):
        if root in seen:
            continue
        component, queue = [], [root]
        seen.add(root)
        while queue:                                   # breadth-first component
            node = queue.pop()
            component.append(node)
            for nb in adjacency[node]:
                if nb not in seen:
                    seen.add(nb)
                    queue.append(nb)
        component.sort()
        if len(component) < 2:
            continue                                   # nothing to match against
        # anchor the component's first panel at zero, then solve the rest
        free = component[1:]
        sub_a = A[np.ix_(free, free)]
        sub_b = b[free]
        solution, *_ = np.linalg.lstsq(sub_a, sub_b, rcond=None)
        for idx, value in zip(free, solution):
            offsets[idx] = float(value)
    return offsets


def feather_weights(valid, width: float):
    """A 0..1 ramp rising from a panel's border inward over `width` pixels.

    Without it every coverage boundary is a step: two panels that disagree by a
    constant meet at a cliff, which is exactly the seam the Stage 1 mosaic
    showed. Fading each panel out at its own edge turns the cliff into a
    gradient, and the overlap decides how quickly.

    The ramp is normalised by the panel's OWN maximum distance rather than by
    `width`, so a sliver of coverage narrower than the feather still reaches
    full weight somewhere. Weighting a sliver to nothing would discard the only
    data covering that part of the sky.
    """
    import numpy as np
    from scipy.ndimage import distance_transform_edt

    dist = distance_transform_edt(valid)
    reach = min(float(width), float(dist.max()) if dist.max() > 0 else 1.0)
    w = np.clip(dist / max(reach, 1e-6), 0.0, 1.0)
    return np.where(valid, w, 0.0).astype(np.float32)


def combine_panels(layers, valids, weights, offsets=None, weights_map=None):
    """Weighted average over the panels that reached each pixel.

    Weighted by integration time rather than equally: an overlap between a
    48-sub panel and a 4-sub one should look mostly like the deep one. Pixels no
    panel reached stay zero AND report zero coverage, so a later trim can tell
    them from genuinely dark sky.
    """
    import numpy as np

    offsets = offsets if offsets is not None else [0.0] * len(layers)
    maps = weights_map if weights_map is not None else [None] * len(layers)
    shape = layers[0].shape
    colour = len(shape) == 3
    acc = np.zeros(shape, np.float32)
    wsum = np.zeros(shape[:2], np.float32)
    coverage = np.zeros(shape[:2], np.int32)
    for data, valid, weight, off, wmap in zip(layers, valids, weights, offsets, maps):
        # a per-pixel feather multiplies the panel's flat weight, so depth and
        # distance-from-edge both count
        pix = valid * weight if wmap is None else wmap * weight
        mask = valid[:, :, None] if colour else valid
        acc += np.where(mask, (data + off) * (pix[:, :, None] if colour else pix), 0.0)
        wsum += pix
        coverage += valid
    safe = np.maximum(wsum, 1e-6)
    master = acc / (safe[:, :, None] if colour else safe)
    hit = coverage > 0
    master = np.where(hit[:, :, None] if colour else hit, master, 0.0)
    return master.astype(np.float32), coverage


@dataclass
class MosaicOptions:
    include: list
    output_path: str
    astap_path: str
    method: str = "sigma_clip"
    kappa: float = 3.0
    autocrop: bool = True
    min_panel_subs: int = 4
    max_spread_deg: float = 0.56
    # Where panel masters live. None uses a temporary directory and
    # discards them; a path keeps them, so a 40-minute stack survives and
    # a re-run reuses it instead of repeating the expensive part.
    work_dir: str | None = None


@dataclass
class MosaicResult:
    image: object
    panel_count: int
    frame_count: int
    integration_seconds: float
    dropped: list
    output_path: str
    wcs: object = None


def run_mosaic(opts: MosaicOptions, *, on_progress=None, solver=None) -> MosaicResult:
    """Group, stack, solve, reproject, combine.

    The master carries the global WCS, so plate-solve annotations work on a
    mosaic without re-solving it.
    """
    import contextlib
    import tempfile

    import numpy as np

    from ..core.export import save_fits          # NOT fits_io — save lives in export
    from ..core.image import AstroImage
    from .coverage import full_coverage_bounds

    if solver is None:
        check_astap(opts.astap_path)

    panels = discover_panels(read_pointings(list(opts.include)), opts.max_spread_deg)
    if len(panels) < 2:
        raise ValueError(
            "these frames are all one pointing — stack them normally rather "
            "than as a mosaic")

    if opts.work_dir:
        os.makedirs(opts.work_dir, exist_ok=True)
        work_ctx = contextlib.nullcontext(opts.work_dir)
    else:
        work_ctx = tempfile.TemporaryDirectory(prefix="nocturne_mosaic_")

    with work_ctx as work:
        stacks, dropped = stack_panels(
            panels, work, method=opts.method, kappa=opts.kappa,
            min_panel_subs=opts.min_panel_subs, on_progress=on_progress)
        solved, unsolved = solve_panels(stacks, opts.astap_path, solver=solver,
                                        on_progress=on_progress)
        dropped.extend(unsolved)
        if len(solved) < 2:
            raise ValueError(
                "fewer than two panels could be placed on the sky — a mosaic "
                "needs at least two solved panels")

        wcs, shape = global_frame(solved)
        layers, valids, weights = [], [], []
        for i, p in enumerate(solved, start=1):
            if on_progress is not None:
                on_progress(i, len(solved), f"Step 3 of 3 — placing panel {i}")
            img = load_fits(p.stack.master_path, normalize=False)
            # undo run_stack's per-master peak normalisation: two panels whose
            # brightest star differs are otherwise on different scales, and the
            # step that produces looks like a background fault
            data = img.data * (p.stack.peak or 1.0)
            out, valid = reproject_panel(data, p.wcs, wcs, shape)
            layers.append(out)
            valids.append(valid)
            weights.append(p.stack.integration_seconds)

        offsets = match_offsets(layers, valids)
        # feather over a tenth of the panel's short side: wide enough to hide a
        # residual step, narrow enough that a panel still dominates its own middle
        panel_short = min(min(p.shape) for p in solved)
        feather = [feather_weights(v, panel_short / 10.0) for v in valids]
        master, coverage = combine_panels(layers, valids, weights, offsets,
                                          weights_map=feather)
        frame_count = sum(s.frame_count for s in stacks)
        integration = sum(s.integration_seconds for s in stacks)

    top = left = 0
    if opts.autocrop:
        # frac against ONE frame: a mosaic's coverage is 1 nearly everywhere by
        # design, so the stack's "nearly every frame saw this" test would throw
        # the whole picture away
        top, bottom, left, right = full_coverage_bounds(coverage, 1)
        master = master[top:bottom, left:right]

    peak = float(master.max())
    if peak > 0:
        master = master / peak
    image = AstroImage(np.clip(master, 0.0, 1.0).astype(np.float32),
                       is_linear=True,
                       metadata={"panels": len(solved), "frames": frame_count})
    # The WCS goes INTO THE FILE, not just the result object. Placing panels
    # astrometrically and then discarding the solution would leave a mosaic that
    # cannot be annotated, cannot be re-solved cheaply, and cannot even report
    # its own scale. CRPIX moves with the trim: cropping the canvas shifts the
    # reference pixel by exactly the pixels removed.
    cards = dict(wcs.to_header())
    if opts.autocrop:
        cards["CRPIX1"] = float(cards.get("CRPIX1", 1.0)) - left
        cards["CRPIX2"] = float(cards.get("CRPIX2", 1.0)) - top
    save_fits(image, opts.output_path, header=cards)
    return MosaicResult(image, len(solved), frame_count, integration,
                        dropped, opts.output_path, wcs)
