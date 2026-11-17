#!/usr/bin/env python3
"""
Extract patch features for every slide that has patch coordinates (made by tissue_patch.py).

    python extract_features.py --patches-dir patches --out features --encoder resnet50 --limit 1   # try one slide
    python extract_features.py --patches-dir patches --out features --encoder resnet50
    python extract_features.py --patches-dir patches --out features --encoder uni                  # after UNI access
    python extract_features.py --encoder dummy --limit 1     # dry run with no GPU / no model download

Per slide it writes  <out>/<slide>.h5  containing
    features   (N, D)  float16   one embedding per patch from a FROZEN encoder
    coords     (N, 2)  level-0 pixel positions (same order as features)
    lapvar     (N,)    blur measure (variance of Laplacian; low = blurry)
    white_frac (N,)    fraction of near-white pixels (high = mostly empty glass)
No patches are removed here; quality values are saved so thresholds can be chosen later,
after you have looked at their distribution.

* Resumable: slides with a finished .h5 are skipped. Files are written under a temporary name and
  renamed only when complete, so an existing .h5 is always a finished one.
* --delete-slides removes the slide file ONLY after its feature file has been written and re-read
  successfully. Use it when disk space is short. Never combine it with --limit on slides you still need.
* Patches are read in parallel threads (no multiprocessing issues on Windows).

Encoders: resnet50 (ImageNet, works without approval), uni (needs your approved Hugging Face login), dummy (tests).
Requires: numpy, h5py, opencv-python-headless, pandas, tiffslide; torch + timm for resnet50/uni.
"""
import argparse
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2
import h5py
import numpy as np
import pandas as pd


# ----------------------------------------------------------------------------
def open_slide(path):
    import tiffslide
    return tiffslide.TiffSlide(str(path))


class SlideReader:
    """One slide handle per worker thread; all handles can be closed afterwards (needed before deleting)."""

    def __init__(self, path):
        self.path, self.local, self.handles, self.lock = path, threading.local(), [], threading.Lock()

    def _slide(self):
        s = getattr(self.local, "s", None)
        if s is None:
            s = open_slide(self.path)
            self.local.s = s
            with self.lock:
                self.handles.append(s)
        return s

    def read(self, x, y, patch_l0, patch_px):
        img = np.array(self._slide().read_region((int(x), int(y)), 0, (patch_l0, patch_l0)).convert("RGB"))
        if patch_l0 != patch_px:
            img = cv2.resize(img, (patch_px, patch_px), interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
        lap = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        white = float((img.min(axis=2) > 220).mean())
        return img, lap, white

    def close(self):
        with self.lock:
            for s in self.handles:
                try:
                    s.close()
                except Exception:
                    pass
            self.handles.clear()


# ----------------------------------------------------------------------------
def build_encoder(name, device_name="auto"):
    """Returns (encode_fn, dim). encode_fn: uint8 array (B,H,W,3) -> float32 array (B,D)."""
    if name == "dummy":
        rng = np.random.default_rng(0)
        proj = rng.normal(size=(3, 64)).astype(np.float32)

        def enc(batch):
            m = batch.reshape(len(batch), -1, 3).mean(1) / 255.0
            return (m @ proj).astype(np.float32)
        return enc, 64

    import torch
    import torch.nn.functional as F
    import timm

    device = torch.device("cuda" if (device_name == "auto" and torch.cuda.is_available()) else
                          ("cpu" if device_name == "auto" else device_name))
    if name == "resnet50":
        model = timm.create_model("resnet50.tv_in1k", pretrained=True, num_classes=0)
    elif name == "uni":
        model = timm.create_model("hf-hub:MahmoodLab/uni", pretrained=True, init_values=1e-5,
                                  dynamic_img_size=True)
    else:
        raise ValueError(f"unknown encoder {name}")
    model = model.to(device).eval()
    mean = torch.tensor([0.485, 0.456, 0.406], device=device).view(1, 3, 1, 1)
    std = torch.tensor([0.229, 0.224, 0.225], device=device).view(1, 3, 1, 1)
    print(f"Encoder {name} on {device}" + (f" ({torch.cuda.get_device_name(0)})" if device.type == "cuda" else ""))

    @torch.inference_mode()
    def enc(batch):
        x = torch.from_numpy(batch).to(device).permute(0, 3, 1, 2).float() / 255.0
        x = F.interpolate(x, size=(224, 224), mode="bilinear", antialias=True, align_corners=False)
        x = (x - mean) / std
        with torch.autocast(device_type=device.type, dtype=torch.float16, enabled=device.type == "cuda"):
            f = model(x)
        return f.float().cpu().numpy()

    with torch.inference_mode():   # find the output size
        dim = enc(np.zeros((1, 256, 256, 3), np.uint8)).shape[1]
    return enc, dim


# ----------------------------------------------------------------------------
def find_slide(h5path, attrs, slides_dir):
    p = Path(str(attrs.get("slide_path", "")))
    if p.exists():
        return p
    if slides_dir:
        hits = list(Path(slides_dir).rglob(h5path.stem + ".*"))
        hits = [h for h in hits if h.suffix.lower() in {".svs", ".tif", ".tiff", ".ndpi", ".mrxs", ".scn"}]
        if hits:
            return hits[0]
    return None


def extract_slide(h5path, out_dir, encode, dim, enc_name, batch_size, threads, slides_dir, dtype, delete_slide):
    with h5py.File(h5path) as f:
        coords = f["coords"][:]
        attrs = dict(f.attrs)
    slide_path = find_slide(h5path, attrs, slides_dir)
    if slide_path is None:
        raise FileNotFoundError("slide file not found (already deleted or not downloaded yet?)")
    patch_px, patch_l0 = int(attrs["patch_px"]), int(attrs["patch_l0"])
    n = len(coords)
    if n == 0:
        raise ValueError("no patches in coordinate file")

    reader = SlideReader(slide_path)
    feats, laps, whites = [], [], []
    t0 = time.time()
    try:
        with ThreadPoolExecutor(max_workers=threads) as ex:
            def submit(i):
                return [ex.submit(reader.read, x, y, patch_l0, patch_px) for x, y in coords[i:i + batch_size]]
            pending = submit(0)
            for i in range(0, n, batch_size):
                cur = pending
                pending = submit(i + batch_size) if i + batch_size < n else None
                res = [fu.result() for fu in cur]
                batch = np.stack([r[0] for r in res])
                feats.append(encode(batch))
                laps += [r[1] for r in res]
                whites += [r[2] for r in res]
    finally:
        reader.close()

    feats = np.concatenate(feats).astype(dtype)
    assert feats.shape == (n, dim), (feats.shape, n, dim)
    out_dir.mkdir(parents=True, exist_ok=True)
    final = out_dir / f"{h5path.stem}.h5"
    tmp = out_dir / f".{h5path.stem}.h5.tmp"
    with h5py.File(tmp, "w") as f:
        f.create_dataset("features", data=feats, compression="gzip", compression_opts=1)
        f.create_dataset("coords", data=coords)
        f.create_dataset("lapvar", data=np.asarray(laps, np.float32))
        f.create_dataset("white_frac", data=np.asarray(whites, np.float32))
        f.attrs.update(dict(encoder=enc_name, dim=dim, patch_px=patch_px, patch_l0=patch_l0, n=n,
                            slide_path=str(slide_path)))
    with h5py.File(tmp) as f:                      # re-read to prove the file is good
        assert f["features"].shape == (n, dim) and np.isfinite(f["features"][:].astype(np.float32)).all()
    os.replace(tmp, final)

    deleted = False
    if delete_slide:
        os.remove(slide_path)
        try:
            slide_path.parent.rmdir()
        except OSError:
            pass
        deleted = True
    secs = time.time() - t0
    return dict(slide=h5path.stem, n_patches=n, dim=dim, seconds=round(secs, 1),
                patches_per_s=round(n / max(secs, 1e-9), 1),
                lapvar_median=float(np.median(laps)), white_frac_mean=float(np.mean(whites)),
                slide_deleted=deleted, error="")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--patches-dir", default="patches")
    ap.add_argument("--out", default="features")
    ap.add_argument("--encoder", default="resnet50", choices=["resnet50", "uni", "dummy"])
    ap.add_argument("--batch-size", type=int, default=128)
    ap.add_argument("--threads", type=int, default=min(8, os.cpu_count() or 4))
    ap.add_argument("--slides-dir", default=None, help="only needed if the slide path stored in the .h5 is wrong")
    ap.add_argument("--dtype", default="float16", choices=["float16", "float32"])
    ap.add_argument("--device", default="auto")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--delete-slides", action="store_true",
                    help="delete each slide file after its features are saved and verified")
    args = ap.parse_args()

    out_dir = Path(args.out)
    h5s = sorted(Path(args.patches_dir).glob("*.h5"))
    todo = [p for p in h5s if not (out_dir / f"{p.stem}.h5").exists()]
    if args.limit:
        todo = todo[: args.limit]
    print(f"{len(h5s)} slides have patch coordinates; {len(todo)} still need features.")
    if not todo:
        return
    encode, dim = build_encoder(args.encoder, args.device)

    rows = []
    for i, p in enumerate(todo, 1):
        try:
            r = extract_slide(p, out_dir, encode, dim, args.encoder, args.batch_size, args.threads,
                              args.slides_dir, args.dtype, args.delete_slides)
            print(f"[{i}/{len(todo)}] {p.stem[:40]}  {r['n_patches']} patches  {r['seconds']}s  "
                  f"({r['patches_per_s']} patches/s)  blur-median={r['lapvar_median']:.1f}  "
                  f"white={r['white_frac_mean']:.2f}" + ("  slide deleted" if r["slide_deleted"] else ""), flush=True)
        except Exception as e:
            r = dict(slide=p.stem, error=f"{type(e).__name__}: {e}")
            print(f"[{i}/{len(todo)}] {p.stem[:40]}  FAILED: {r['error']}", flush=True)
        rows.append(r)

    sp = out_dir / "summary.csv"
    new = pd.DataFrame(rows)
    if sp.exists():
        new = pd.concat([pd.read_csv(sp), new]).drop_duplicates("slide", keep="last")
    new.to_csv(sp, index=False)
    print(f"\nWrote {sp}")


if __name__ == "__main__":
    main()
