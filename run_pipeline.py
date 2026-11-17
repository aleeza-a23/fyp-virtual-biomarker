"""Unattended pipeline: download -> patch -> extract features (1 or more encoders) -> (optionally) delete slides.

Runs in batches. Every step resumes, so if you stop it (Ctrl+C) or the PC restarts, run the same command again.

Examples:
    python run_pipeline.py --start 0 --end 5 --batch 5                       (small test: first 5 slides)
    python run_pipeline.py --batch 40                                        (all slides, ResNet50, slides KEPT)
    python run_pipeline.py --batch 40 --encoders resnet50,uni                (both encoders; needs UNI access + HF_TOKEN)
    python run_pipeline.py --batch 40 --encoders resnet50,uni --delete-slides  (delete each slide after the LAST encoder)

Feature folders: resnet50 -> features, uni -> features_uni.

SAFETY
* Slides are KEPT unless you pass --delete-slides. Deleting means re-downloading (hours) if you later want
  another encoder, so only use it when disk space really requires it, and with ALL the encoders you need.
* After every batch the script checks that each slide in the batch has patch coordinates and features for every
  encoder. Missing ones are listed and saved to pipeline_failures.txt (the sub-scripts keep going when a single
  slide fails, so this check is the only way to notice). If more than 25% of a batch fails, it stops.
"""
import argparse
import csv
import subprocess
import sys
import time
from pathlib import Path

OUT_DIR = {"resnet50": "features", "uni": "features_uni"}


def read_manifest(path):
    with open(path, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    if rows and not {"id", "filename"} <= set(rows[0]):
        sys.exit("Manifest must have 'id' and 'filename' columns.")
    return rows


def run(cmd, retries=1):
    for attempt in range(1, retries + 1):
        print(f"\n>>> {' '.join(cmd)}  (attempt {attempt}/{retries})", flush=True)
        if subprocess.run(cmd).returncode == 0:
            return True
        if attempt < retries:
            time.sleep(30)
    return False


def missing_outputs(rows, patches_dir, encoders):
    bad = {}
    for r in rows:
        stem = Path(r["filename"]).stem
        miss = []
        if not (Path(patches_dir) / f"{stem}.h5").exists():
            miss.append("patches")
        for e in encoders:
            if not (Path(OUT_DIR[e]) / f"{stem}.h5").exists():
                miss.append(e)
        if miss:
            bad[stem] = miss
    return bad


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", default=r"tcga_out\gdc_manifest_dx_usable.tsv")
    ap.add_argument("--slides-dir", default="slides")
    ap.add_argument("--patches-dir", default="patches")
    ap.add_argument("--encoders", default="resnet50", help="comma list: resnet50,uni")
    ap.add_argument("--start", type=int, default=0, help="first manifest row (0 = the beginning)")
    ap.add_argument("--end", type=int, default=None, help="stop before this manifest row (default: the end)")
    ap.add_argument("--batch", type=int, default=40, help="slides per batch (about 0.8 GB each)")
    ap.add_argument("--download-workers", type=int, default=1, help="slides downloaded in parallel (try 3-4)")
    ap.add_argument("--delete-slides", action="store_true",
                    help="delete each slide after the LAST encoder has finished on it (default: keep)")
    args = ap.parse_args()

    encoders = [e.strip() for e in args.encoders.split(",") if e.strip()]
    for e in encoders:
        if e not in OUT_DIR:
            sys.exit(f"Unknown encoder: {e}")

    rows = read_manifest(args.manifest)
    total = len(rows) if args.end is None else min(args.end, len(rows))
    py = sys.executable
    print(f"Manifest has {len(rows)} slides. Rows {args.start}..{total - 1}, batch {args.batch}, "
          f"encoders {encoders}. Slides will be {'DELETED after the last encoder' if args.delete_slides else 'KEPT'}.",
          flush=True)

    t0, offset, all_bad = time.time(), args.start, {}
    while offset < total:
        n = min(args.batch, total - offset)
        print(f"\n===== Batch: slides {offset}..{offset + n - 1} of {total} =====", flush=True)

        if not run([py, "download_slides.py", "--manifest", args.manifest, "--out", args.slides_dir,
                    "--offset", str(offset), "--limit", str(n),
                    "--workers", str(args.download_workers)], retries=3):
            print("Download kept failing. Check your internet and disk space, then rerun the same command.")
            sys.exit(1)

        if not run([py, "tissue_patch.py", "--slides-dir", args.slides_dir, "--out", args.patches_dir]):
            print("Patching crashed. Copy the error above.")
            sys.exit(1)

        for i, enc in enumerate(encoders):
            cmd = [py, "extract_features.py", "--patches-dir", args.patches_dir, "--out", OUT_DIR[enc],
                   "--encoder", enc, "--slides-dir", args.slides_dir]
            if args.delete_slides and i == len(encoders) - 1:
                cmd.append("--delete-slides")
            if not run(cmd):
                print(f"Feature extraction ({enc}) crashed. Copy the error above.")
                sys.exit(1)

        bad = missing_outputs(rows[offset:offset + n], args.patches_dir, encoders)
        if bad:
            all_bad.update(bad)
            with open("pipeline_failures.txt", "a", encoding="utf-8") as f:
                for stem, miss in bad.items():
                    f.write(f"{stem}\tmissing: {', '.join(miss)}\n")
            print(f"\nWARNING: {len(bad)} of {n} slides in this batch have missing outputs "
                  f"(listed in pipeline_failures.txt):")
            for stem, miss in list(bad.items())[:10]:
                print(f"   {stem[:50]}  missing {', '.join(miss)}")
            if n >= 4 and len(bad) > 0.25 * n:
                print("More than 25% of this batch failed, which points to a systematic problem "
                      "(token, disk, corrupt download). Stopping. Copy the messages above.")
                sys.exit(2)

        offset += n
        done = offset - args.start
        elapsed = (time.time() - t0) / 60
        eta = elapsed / done * (total - offset) if done else 0
        print(f"\nProgress: {offset}/{total}. Elapsed {elapsed:.0f} min, about {eta:.0f} min left.", flush=True)

    print(f"\nAll batches finished. Slides with missing outputs: {len(all_bad)}"
          + (" (see pipeline_failures.txt)" if all_bad else ""))


if __name__ == "__main__":
    main()
