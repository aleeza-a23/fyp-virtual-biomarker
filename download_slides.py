#!/usr/bin/env python3
"""
Download slides listed in a GDC manifest, without installing gdc-client.

    python download_slides.py --manifest tcga_out\\gdc_manifest_dx_usable.tsv --out slides --limit 3
    python download_slides.py --manifest tcga_out\\gdc_manifest_dx_usable.tsv --out slides --offset 3 --limit 100

* Works on open-access TCGA slides (no login or token needed).
* Resumable: an interrupted file continues from where it stopped; finished files are skipped.
* Verifies size and md5 for every file before it counts as done.
* Same layout as gdc-client:  <out>/<file_id>/<file_name>
* Checks free disk space before starting.
* --offset / --limit let you download in batches (e.g. 100 slides at a time).
* --workers N downloads N slides at once (each file is still resumable and md5-checked).

Requires: pandas, requests.
"""
import argparse
import hashlib
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import requests

DEFAULT_BASE = "https://api.gdc.cancer.gov/data"


def md5_of(path, chunk=1 << 20):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def download_one(session, base, row, out_dir, retries=6, timeout=(15, 120), sleep=time.sleep):
    fid, fname, md5, size = row["id"], row["filename"], row["md5"], int(row["size"])
    folder = out_dir / fid
    folder.mkdir(parents=True, exist_ok=True)
    dest, part = folder / fname, folder / (fname + ".part")
    if dest.exists() and dest.stat().st_size == size:
        return "cached"

    last = None
    for attempt in range(retries):
        try:
            have = part.stat().st_size if part.exists() else 0
            if have > size:
                part.unlink()
                have = 0
            if have < size:
                headers = {"Range": f"bytes={have}-"} if have else {}
                with session.get(f"{base}/{fid}", headers=headers, stream=True, timeout=timeout) as r:
                    if r.status_code == 416:       # server says our offset is invalid -> start over
                        part.unlink(missing_ok=True)
                        raise IOError("range rejected, restarting")
                    r.raise_for_status()
                    mode = "ab"
                    if have and r.status_code != 206:   # server ignored Range -> full restart
                        mode = "wb"
                    with open(part, mode) as f:
                        for chunk in r.iter_content(1 << 20):
                            f.write(chunk)
            if part.stat().st_size != size:
                raise IOError(f"size {part.stat().st_size} != expected {size}")
            if md5 and md5_of(part) != md5:
                part.unlink()
                raise IOError("md5 mismatch, re-downloading")
            part.replace(dest)
            return "downloaded"
        except (requests.RequestException, IOError) as e:
            last = e
            wait = min(2 ** attempt, 30)
            print(f"    retry {attempt + 1}/{retries} for {fname} ({type(e).__name__}: {e}); waiting {wait}s",
                  flush=True)
            sleep(wait)
    raise RuntimeError(f"Failed to download {fname}: {last}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--out", default="slides")
    ap.add_argument("--offset", type=int, default=0, help="skip this many manifest rows")
    ap.add_argument("--limit", type=int, default=None, help="download at most this many slides")
    ap.add_argument("--base-url", default=DEFAULT_BASE)
    ap.add_argument("--min-free-gb", type=float, default=20, help="keep at least this much disk free")
    ap.add_argument("--workers", type=int, default=1,
                    help="slides downloaded in parallel (try 3-4 if one download does not use your full bandwidth)")
    args = ap.parse_args()

    man = pd.read_csv(args.manifest, sep="\t")
    need = {"id", "filename", "md5", "size"}
    if not need <= set(man.columns):
        sys.exit(f"Manifest must have columns {sorted(need)}; found {list(man.columns)}")
    man = man.iloc[args.offset:]
    if args.limit:
        man = man.iloc[: args.limit]

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    todo_bytes = sum(int(r["size"]) for _, r in man.iterrows()
                     if not (out_dir / r["id"] / r["filename"]).exists())
    free = shutil.disk_usage(out_dir).free
    print(f"{len(man)} slides in this batch; about {todo_bytes / 1e9:.1f} GB still to download; "
          f"{free / 1e9:.0f} GB free on this drive.")
    if todo_bytes + args.min_free_gb * 1e9 > free:
        sys.exit("Not enough free disk space for this batch. Use a smaller --limit or free up space.")

    t0 = time.time()
    lock = threading.Lock()
    state = {"done": 0, "bytes": 0}
    local = threading.local()
    failed = []

    def work(row):
        sess = getattr(local, "s", None)
        if sess is None:
            sess = local.s = requests.Session()
        return row, download_one(sess, args.base_url, row, out_dir)

    rows = [r for _, r in man.iterrows()]
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        futs = {ex.submit(work, r): r for r in rows}
        for fu in as_completed(futs):
            r = futs[fu]
            try:
                _, status = fu.result()
            except Exception as e:
                with lock:
                    failed.append(r["filename"])
                    print(f"FAILED {r['filename']}: {e}", flush=True)
                continue
            with lock:
                state["done"] += 1
                if status == "downloaded":
                    state["bytes"] += int(r["size"])
                rate = state["bytes"] / 1e6 / max(time.time() - t0, 1)
                print(f"[{state['done']}/{len(rows)}] {r['filename']}  {status}  "
                      f"({int(r['size']) / 1e9:.2f} GB, overall {rate:.1f} MB/s)", flush=True)
    if failed:
        print(f"\n{len(failed)} slide(s) failed. Re-run the same command to retry them.")
        sys.exit(1)
    print("Batch finished. Re-run the same command at any time; finished slides are skipped.")


if __name__ == "__main__":
    main()
