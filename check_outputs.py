#!/usr/bin/env python3
"""
Check the pipeline's outputs after an interruption (or at the end of a run).

    python check_outputs.py                  # report only
    python check_outputs.py --delete-bad     # also delete unreadable .h5 files so the pipeline redoes them
    python check_outputs.py --full           # read every feature value (slower, ~minutes for 655 files)

Looks at patches/, features/ and features_uni/ (whichever exist):
  * every .h5 must open and have consistent shapes (and finite feature values),
  * leftover temporary files (.*.tmp) are reported and removed with --delete-bad,
  * slides still on disk and partial downloads (*.part) are counted (partial downloads resume by themselves),
  * patch files that still lack features for an encoder are counted (the pipeline will process them).
Then rerun the same run_pipeline.py command: finished work is skipped, deleted files are recomputed.
"""
import argparse
from pathlib import Path

import h5py
import numpy as np


def check_h5(path, kind, full):
    try:
        with h5py.File(path) as f:
            if kind == "patches":
                c = f["coords"]
                assert c.ndim == 2 and c.shape[1] == 2 and c.shape[0] > 0, f"bad coords shape {c.shape}"
            else:
                F, C = f["features"], f["coords"]
                n = F.shape[0]
                assert n > 0 and C.shape[0] == n and f["white_frac"].shape[0] == n and f["lapvar"].shape[0] == n, \
                    "feature/coord/quality lengths differ"
                block = F[:] if full else F[: min(n, 300)]
                assert np.isfinite(block.astype(np.float32)).all(), "non-finite feature values"
        return None
    except Exception as e:
        return f"{type(e).__name__}: {e}"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--patches-dir", default="patches")
    ap.add_argument("--feature-dirs", default="features,features_uni")
    ap.add_argument("--slides-dir", default="slides")
    ap.add_argument("--delete-bad", action="store_true")
    ap.add_argument("--full", action="store_true")
    args = ap.parse_args()

    dirs = [("patches", Path(args.patches_dir))] + [("features", Path(d.strip())) for d in args.feature_dirs.split(",") if d.strip()]
    stems, bad_total = {}, 0
    for kind, d in dirs:
        if not d.exists():
            print(f"{d}: (folder not found, skipped)")
            continue
        files = sorted(d.glob("*.h5"))
        bad = []
        for p in files:
            err = check_h5(p, kind, args.full)
            if err:
                bad.append((p, err))
        tmp = list(d.glob(".*.tmp"))
        stems[d.name] = {p.stem for p in files} - {p.stem for p, _ in bad}
        print(f"{d}: {len(files)} files, {len(bad)} unreadable, {len(tmp)} leftover temp files")
        for p, err in bad[:10]:
            print(f"    BAD {p.name[:55]}  ({err})")
        if args.delete_bad:
            for p, _ in bad:
                p.unlink()
            for p in tmp:
                p.unlink()
        bad_total += len(bad)

    sd = Path(args.slides_dir)
    if sd.exists():
        n_svs = sum(1 for _ in sd.rglob("*.svs"))
        n_part = sum(1 for _ in sd.rglob("*.part"))
        print(f"{sd}: {n_svs} finished slides, {n_part} partial downloads (these resume automatically)")

    base = stems.get(Path(args.patches_dir).name, set())
    for name, s in stems.items():
        if name != Path(args.patches_dir).name:
            print(f"{name}: {len(base - s)} patched slides still need features")
    if bad_total and not args.delete_bad:
        print(f"\n{bad_total} unreadable file(s). Run again with --delete-bad, then rerun your pipeline command.")
    elif bad_total:
        print(f"\nDeleted {bad_total} unreadable file(s). Rerun your pipeline command to recompute them.")
    else:
        print("\nAll files readable.")


if __name__ == "__main__":
    main()
