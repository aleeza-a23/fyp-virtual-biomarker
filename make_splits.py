#!/usr/bin/env python3
"""
Freeze the patient-level train/validation/test split for TCGA-LUAD.

    python make_splits.py create            # run ONCE; refuses to overwrite
    python make_splits.py verify            # check the frozen file was not modified

Design
  * Unit of splitting = PATIENT (case_submitter_id). All of a patient's slides go to the
    same side, so no patient ever appears in both training and testing.
  * One split shared by both tasks (biomarker prediction and survival), so a patient is
    never training data for one task and test data for the other.
  * split = "test" (fixed hold-out, touched once at the very end) or "dev".
    Dev patients get fold 0..K-1 for K-fold cross-validation; the held-out fold is the
    validation set in each round.
  * Stratified by survival event (0 / 1 / unknown) so event rates stay similar everywhere.
  * Deterministic: same inventory + same seed -> same split.

If a patient is later dropped (e.g. slide quality control), REMOVE them. Never reassign
other patients, and never re-run `create` with a different seed after seeing any results.

Inputs : luad_out/luad_inventory.csv  (from luad_inventory.py inventory)
Outputs: luad_out/splits_frozen.csv       one row per patient
         luad_out/slide_splits.csv        one row per slide (inherits patient's split)
         luad_out/splits_frozen.sha256    hash for verify
"""
import argparse
import hashlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd


def make_cohort(inv):
    inv = inv.copy()
    for col in ["has_dx", "usable_biomarker", "usable_survival"]:
        inv[col] = inv[col].astype(bool)
    cohort = inv[inv["has_dx"] & (inv["usable_biomarker"] | inv["usable_survival"])].copy()
    if "selected" in cohort.columns:  # multi-cancer runs with a per-cancer cap
        cohort = cohort[cohort["selected"].astype(bool)].copy()
    ev = cohort["os_event"].map(lambda v: "event_unknown" if pd.isna(v) else f"event_{int(v)}")
    if "project_id" in cohort.columns and cohort["project_id"].nunique() > 1:
        # stratify by cancer type too, so every cancer appears in test and in every fold
        cohort["stratum"] = cohort["project_id"].astype(str) + "|" + ev
    else:
        cohort["stratum"] = ev
    return cohort


def assign(cohort, test_frac, n_folds, seed):
    rng = np.random.default_rng(seed)
    split_map, fold_map = {}, {}
    offset = 0  # running counter so fold sizes stay balanced across strata
    for s in sorted(cohort["stratum"].unique()):
        ids = sorted(cohort.loc[cohort["stratum"] == s, "case_submitter_id"])
        ids = list(rng.permutation(ids))
        n_test = int(round(len(ids) * test_frac))
        for cid in ids[:n_test]:
            split_map[cid], fold_map[cid] = "test", -1
        for cid in ids[n_test:]:
            split_map[cid], fold_map[cid] = "dev", offset % n_folds
            offset += 1
    cols = ["case_submitter_id", "n_dx_slides", "os_days", "os_event", "stage",
            "usable_biomarker", "usable_survival", "stratum"]
    if "project_id" in cohort.columns:
        cols.insert(1, "project_id")
    out = cohort[cols].copy()
    out["split"] = out["case_submitter_id"].map(split_map)
    out["fold"] = out["case_submitter_id"].map(fold_map).astype(int)
    return out.sort_values("case_submitter_id").reset_index(drop=True)


def slide_table(cohort, patient_splits):
    rows = []
    for r in cohort.itertuples():
        barcodes = str(r.dx_slide_barcodes).split(";")
        fids = str(r.dx_file_ids).split(";")
        for b, f in zip(barcodes, fids):
            rows.append({"case_submitter_id": r.case_submitter_id, "slide_barcode": b, "file_id": f})
    sl = pd.DataFrame(rows)
    return sl.merge(patient_splits[["case_submitter_id", "split", "fold"]], on="case_submitter_id")


def sanity_checks(ps, sl, n_folds):
    assert ps["case_submitter_id"].is_unique, "duplicate patient rows"
    assert ps["split"].isin(["dev", "test"]).all()
    assert (ps.loc[ps["split"] == "test", "fold"] == -1).all()
    assert ps.loc[ps["split"] == "dev", "fold"].between(0, n_folds - 1).all()
    # no patient's slides on both sides
    sides = sl.groupby("case_submitter_id")["split"].nunique()
    assert (sides == 1).all(), "leakage: a patient's slides span multiple splits"
    assert set(sl["case_submitter_id"]) == set(ps["case_submitter_id"])


def report(ps, sl):
    def block(df, label):
        ev = df["os_event"].dropna()
        evr = f"{100 * ev.mean():.0f}% deaths ({int(ev.sum())}/{len(ev)} with survival)" if len(ev) else "n/a"
        print(f"  {label:<10} patients={len(df):>4}  biomarker-eligible={int(df['usable_biomarker'].sum()):>4}  "
              f"survival-eligible={int(df['usable_survival'].sum()):>4}  {evr}")
    print("\n=== Frozen split ===")
    block(ps[ps["split"] == "test"], "TEST")
    block(ps[ps["split"] == "dev"], "DEV (all)")
    for k in sorted(ps.loc[ps["split"] == "dev", "fold"].unique()):
        block(ps[(ps["split"] == "dev") & (ps["fold"] == k)], f"  fold {k}")
    if "project_id" in ps.columns and ps["project_id"].nunique() > 1:
        print("\nPatients per cancer type (test / dev):")
        print(pd.crosstab(ps["project_id"], ps["split"]).to_string())
    print(f"\nSlides: {len(sl)} total  "
          f"(test {int((sl['split'] == 'test').sum())}, dev {int((sl['split'] == 'dev').sum())})")


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["create", "verify"])
    ap.add_argument("--out-dir", default="luad_out")
    ap.add_argument("--prefix", default="luad", help="same prefix used with luad_inventory.py")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--test-frac", type=float, default=0.20)
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--force", action="store_true", help="overwrite an existing frozen split (don't)")
    args = ap.parse_args()
    out = Path(args.out_dir)
    frozen, hashf = out / "splits_frozen.csv", out / "splits_frozen.sha256"

    if args.cmd == "verify":
        if not frozen.exists() or not hashf.exists():
            sys.exit("No frozen split / hash file found.")
        ok = sha256(frozen) == hashf.read_text().split()[0]
        print("OK: split is unchanged." if ok else "MISMATCH: splits_frozen.csv was modified!")
        sys.exit(0 if ok else 1)

    if frozen.exists() and not args.force:
        sys.exit(f"{frozen} already exists. The split is frozen; not overwriting. "
                 "(Use --force only if you have NOT used it for any experiment.)")

    inv = pd.read_csv(out / f"{args.prefix}_inventory.csv")
    cohort = make_cohort(inv)
    ps = assign(cohort, args.test_frac, args.folds, args.seed)
    sl = slide_table(cohort, ps)
    sanity_checks(ps, sl, args.folds)

    ps.to_csv(frozen, index=False)
    sl.to_csv(out / "slide_splits.csv", index=False)
    hashf.write_text(f"{sha256(frozen)}  splits_frozen.csv  seed={args.seed}\n")
    report(ps, sl)
    print(f"\nWrote {frozen}, slide_splits.csv and the hash file. Back them up now.")


if __name__ == "__main__":
    main()
