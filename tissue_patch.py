#!/usr/bin/env python3
"""
Tissue detection + patch extraction (coordinates only) for whole-slide images.

    python tissue_patch.py --slides-dir slides --out patches --limit 1          # try one slide first
    python tissue_patch.py --slides-dir slides --out patches                    # all downloaded slides

For every slide it:
  1. reads a low-resolution thumbnail,
  2. builds a tissue mask (saturation + Otsu, smoothing, small-object removal),
  2b. removes marker-pen strokes (blue/green ink) from the mask,
  3. lays a grid of NON-overlapping patches at a fixed magnification (default 256 px at 0.5 um/px, i.e. 20x),
  4. keeps patches whose tissue fraction >= --tissue-thresh,
  5. optionally caps the number of patches per slide (seeded, reproducible),
  6. saves  <out>/<slide>.h5          patch coordinates (level-0 pixels) + settings
            <out>/overlays/<slide>.png  thumbnail with tissue outline and kept patches (figure for your report)
            <out>/summary.csv           one row per slide (magnification, patches kept, tissue %, errors)

Only coordinates are stored (small); patches are read from the slide later, when features are computed.
Resumable: slides that already have an .h5 file are skipped unless --overwrite is given.

Requires: tiffslide, opencv-python-headless, h5py, numpy, pandas, pillow.
"""
import argparse
import time
import zlib
from pathlib import Path

import cv2
import h5py
import numpy as np
import pandas as pd

SLIDE_EXT = {".svs", ".tif", ".tiff", ".ndpi", ".mrxs", ".scn"}


# ----------------------------------------------------------------------------
def open_slide(path):
    import tiffslide
    return tiffslide.TiffSlide(str(path))


def get_base_mpp(props, assume_mpp=None):
    """Microns per pixel at level 0, from slide metadata (falls back to objective power, then --assume-mpp)."""
    for key in ("openslide.mpp-x", "tiffslide.mpp-x", "aperio.MPP"):
        v = props.get(key)
        try:
            if v is not None and float(v) > 0:
                return float(v), f"metadata:{key}"
        except (TypeError, ValueError):
            pass
    for key in ("openslide.objective-power", "tiffslide.objective-power", "aperio.AppMag"):
        v = props.get(key)
        try:
            if v is not None and float(v) > 0:
                return 10.0 / float(v), f"objective-power:{key}"   # 40x -> 0.25, 20x -> 0.5
        except (TypeError, ValueError):
            pass
    if assume_mpp:
        return float(assume_mpp), "assumed"
    raise ValueError("no magnification metadata found; pass --assume-mpp (e.g. 0.25 for 40x, 0.5 for 20x)")


def pick_thumb_level(slide, max_side=4096):
    """Highest-resolution level whose longest side is <= max_side (else the lowest-resolution level)."""
    for lvl, (w, h) in enumerate(slide.level_dimensions):
        if max(w, h) <= max_side:
            return lvl
    return slide.level_count - 1


def tissue_mask(img_rgb, min_sat=15, min_area_frac=2e-4):
    hsv = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2HSV)
    sat = cv2.medianBlur(hsv[..., 1], 7)
    thr, _ = cv2.threshold(sat, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    mask = (sat > max(thr, min_sat)).astype(np.uint8)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    min_area = max(50, min_area_frac * mask.size)
    out = np.zeros_like(mask)
    kept = [c for c in contours if cv2.contourArea(c) >= min_area]
    cv2.drawContours(out, kept, -1, 1, thickness=cv2.FILLED)   # fills holes inside tissue
    return out, kept


def pen_mask(img_rgb, min_area_frac=5e-5, dilate=9):
    """Marker-pen ink (blue/cyan or green strokes) -> 1. H&E tissue is pink/purple (hue ~130-180 in OpenCV
    units), so strongly saturated blue-cyan (95-128) or green (40-85) pixels are ink, not tissue.
    Nearby ink fragments are joined, tiny blobs are ignored (stain, not pen), and strokes are dilated
    to cover their halo. The size cutoff is relative to the thumbnail so it works at any resolution."""
    hsv = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2HSV)
    h, s = hsv[..., 0], hsv[..., 1]
    ink = (((h >= 95) & (h <= 128) & (s >= 90)) | ((h >= 40) & (h <= 85) & (s >= 70))).astype(np.uint8)
    joined = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(joined, connectivity=8)
    min_area = max(20, min_area_frac * ink.size)
    keep_ids = [i for i in range(1, n) if stats[i, cv2.CC_STAT_AREA] >= min_area]
    keep = (np.isin(lab, keep_ids) & (joined > 0)).astype(np.uint8)
    if dilate and keep.any():
        keep = cv2.dilate(keep, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (dilate, dilate)))
    return keep


def patch_grid(W0, H0, patch_l0, mask, thresh, pen=None, max_pen=0.02):
    """Level-0 top-left coordinates of non-overlapping patches with tissue fraction >= thresh
    and (if a pen mask is given) at most max_pen of the patch covered by pen ink / its halo."""
    sx, sy = mask.shape[1] / W0, mask.shape[0] / H0
    xs = np.arange(0, W0 - patch_l0 + 1, patch_l0)
    ys = np.arange(0, H0 - patch_l0 + 1, patch_l0)
    if len(xs) == 0 or len(ys) == 0:
        return np.zeros((0, 2), dtype=np.int64)
    integ = cv2.integral(mask.astype(np.uint8)).astype(np.float64)
    X, Y = np.meshgrid(xs, ys)
    x0 = np.clip((X * sx).astype(int), 0, mask.shape[1] - 1)
    y0 = np.clip((Y * sy).astype(int), 0, mask.shape[0] - 1)
    x1 = np.clip(np.maximum(x0 + 1, ((X + patch_l0) * sx).astype(int)), 1, mask.shape[1])
    y1 = np.clip(np.maximum(y0 + 1, ((Y + patch_l0) * sy).astype(int)), 1, mask.shape[0])
    area = (x1 - x0) * (y1 - y0)
    tot = integ[y1, x1] - integ[y0, x1] - integ[y1, x0] + integ[y0, x0]
    keep = (tot / area) >= thresh
    if pen is not None and pen.any():
        ip = cv2.integral(pen.astype(np.uint8)).astype(np.float64)
        pen_tot = ip[y1, x1] - ip[y0, x1] - ip[y1, x0] + ip[y0, x0]
        keep &= (pen_tot / area) <= max_pen
    return np.stack([X[keep], Y[keep]], axis=1).astype(np.int64)


def draw_overlay(img_rgb, contours, coords, W0, patch_l0, path, max_side=1600):
    vis = img_rgb.copy()
    s = vis.shape[1] / W0
    for x, y in coords:
        x0, y0 = int(x * s), int(y * s)
        x1, y1 = max(x0 + 1, int((x + patch_l0) * s)), max(y0 + 1, int((y + patch_l0) * s))
        cv2.rectangle(vis, (x0, y0), (x1, y1), (255, 0, 0), 1)
    cv2.drawContours(vis, contours, -1, (0, 160, 0), 2)
    h, w = vis.shape[:2]
    if max(h, w) > max_side:
        f = max_side / max(h, w)
        vis = cv2.resize(vis, (int(w * f), int(h * f)), interpolation=cv2.INTER_AREA)
    cv2.imwrite(str(path), cv2.cvtColor(vis, cv2.COLOR_RGB2BGR))


def process_slide(path, out_dir, patch_px, target_mpp, tissue_thresh, max_patches, seed, assume_mpp,
                  pen_filter=True):
    stem = Path(path).stem
    slide = open_slide(path)
    W0, H0 = slide.dimensions
    base_mpp, mpp_src = get_base_mpp(slide.properties, assume_mpp)
    factor = target_mpp / base_mpp                    # level-0 pixels per output pixel
    patch_l0 = patch_px * factor
    if factor < 0.9:
        raise ValueError(f"slide resolution ({base_mpp:.3f} um/px) is coarser than target ({target_mpp} um/px)")

    lvl = pick_thumb_level(slide)
    tw, th = slide.level_dimensions[lvl]
    img = np.array(slide.read_region((0, 0), lvl, (tw, th)).convert("RGB"))
    mask, contours = tissue_mask(img)
    pen = pen_mask(img) if pen_filter else np.zeros_like(mask)
    pen_pct = float(round(100 * (mask & pen).sum() / max(mask.sum(), 1), 1))
    mask = (mask & (1 - pen)).astype(np.uint8)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    coords = patch_grid(W0, H0, int(round(patch_l0)), mask, tissue_thresh, pen=pen if pen_filter else None)
    n_all = len(coords)
    if max_patches and n_all > max_patches:
        rng = np.random.default_rng(seed + zlib.crc32(stem.encode()))
        coords = coords[np.sort(rng.choice(n_all, max_patches, replace=False))]

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "overlays").mkdir(exist_ok=True)
    with h5py.File(out_dir / f"{stem}.h5", "w") as f:
        f.create_dataset("coords", data=coords)
        f.attrs.update(dict(patch_px=patch_px, patch_l0=int(round(patch_l0)), target_mpp=target_mpp,
                            base_mpp=base_mpp, slide_w=W0, slide_h=H0, n_tissue_patches=n_all,
                            slide_path=str(path)))
    draw_overlay(img, contours, coords, W0, int(round(patch_l0)), out_dir / "overlays" / f"{stem}.png")
    return dict(slide=stem, width=W0, height=H0, base_mpp=round(base_mpp, 4), mpp_source=mpp_src,
                factor=round(factor, 3), tissue_pct=float(round(100 * mask.mean(), 1)), pen_removed_pct=pen_pct,
                patches_tissue=n_all, patches_kept=len(coords), error="")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--slides-dir", default="slides")
    ap.add_argument("--out", default="patches")
    ap.add_argument("--patch-px", type=int, default=256)
    ap.add_argument("--target-mpp", type=float, default=0.5, help="0.5 = 20x, 0.25 = 40x")
    ap.add_argument("--tissue-thresh", type=float, default=0.5)
    ap.add_argument("--max-patches", type=int, default=3000, help="cap per slide; 0 = keep all")
    ap.add_argument("--assume-mpp", type=float, default=None, help="used only if the slide has no magnification metadata")
    ap.add_argument("--no-pen-filter", action="store_true", help="keep marker-pen areas (not recommended)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args()

    out_dir = Path(args.out)
    slides = sorted(p for p in Path(args.slides_dir).rglob("*") if p.suffix.lower() in SLIDE_EXT)
    if args.limit:
        slides = slides[: args.limit]
    print(f"{len(slides)} slide(s) found in {args.slides_dir}")

    rows, t0 = [], time.time()
    for i, p in enumerate(slides, 1):
        if (out_dir / f"{p.stem}.h5").exists() and not args.overwrite:
            print(f"[{i}/{len(slides)}] {p.name}  skipped (already done)")
            continue
        try:
            r = process_slide(p, out_dir, args.patch_px, args.target_mpp, args.tissue_thresh,
                              args.max_patches, args.seed, args.assume_mpp, not args.no_pen_filter)
            print(f"[{i}/{len(slides)}] {p.name}  mpp={r['base_mpp']} ({r['mpp_source']})  "
                  f"tissue={r['tissue_pct']}% (pen removed {r['pen_removed_pct']}%)  patches {r['patches_kept']}/{r['patches_tissue']}  "
                  f"({time.time() - t0:.0f}s)", flush=True)
        except Exception as e:      # keep going; the error is recorded
            r = dict(slide=p.stem, error=f"{type(e).__name__}: {e}")
            print(f"[{i}/{len(slides)}] {p.name}  FAILED: {r['error']}", flush=True)
        rows.append(r)

    if rows:
        out_dir.mkdir(parents=True, exist_ok=True)
        sp = out_dir / "summary.csv"
        new = pd.DataFrame(rows)
        if sp.exists():
            new = pd.concat([pd.read_csv(sp), new]).drop_duplicates("slide", keep="last")
        new.to_csv(sp, index=False)
        print(f"\nWrote {sp}. Overlay figures are in {out_dir / 'overlays'}")


if __name__ == "__main__":
    main()
