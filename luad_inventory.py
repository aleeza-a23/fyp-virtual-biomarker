#!/usr/bin/env python3
"""
TCGA-LUAD dataset inventory builder.

MULTI-CANCER USE (new)
    python luad_inventory.py inventory --projects TCGA-LUAD,TCGA-BRCA,TCGA-COAD --max-per-project 200 \
           --prefix tcga --out-dir tcga_out
    python luad_inventory.py inventory --all-tcga --max-per-project 200 --prefix tcga --out-dir tcga_out
  The funnel then prints one line per cancer so you can choose cancers. --max-per-project picks a
  seeded random subset (cases usable for both tasks first) so the download stays manageable.
  Note: only primary-tumour (sample code 01) slides are kept, so cancers whose samples are mostly
  metastatic or blood (e.g. TCGA-SKCM, TCGA-LAML) will show few usable cases.

Stage 1  (python luad_inventory.py inventory)
    Queries the public GDC API for METADATA ONLY (no slides are downloaded) and builds:
        case -> diagnostic slide(s) -> primary-tumour RNA-seq file -> survival -> flags
    Outputs (in --out-dir, default ./luad_out):
        luad_slides_all.csv         every slide image GDC lists for TCGA-LUAD
        luad_inventory.csv          one row per patient (the table we will work from)
        gdc_manifest_dx_usable.tsv  gdc-client manifest for tumour DX slides of usable cases
        and a printed "funnel" showing how many cases survive each filter.

Stage 2  (python luad_inventory.py rna)
    Downloads ONLY the small open-access RNA-seq files (a few MB each) for cases that
    have both a tumour DX slide and tumour RNA-seq, and extracts the target genes:
        CD8A, CD8B, FOXP3, CD274 (PD-L1 proxy), MKI67 (Ki-67 proxy)
    Output: luad_inventory_with_targets.csv

Nothing here binarises the targets. Thresholds (median / tertile) must be computed on the
TRAINING split only, after the patient-level split is frozen, to avoid leakage.

Requires: pandas, requests.   Needs internet access to api.gdc.cancer.gov.
"""
import argparse
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

GDC = "https://api.gdc.cancer.gov"
PROJECT = "TCGA-LUAD"  # default; overridden by --projects / --all-tcga
SCOPE = {"projects": [PROJECT], "program": None}


def scope_filter(prefix):
    """Filter selecting the chosen project(s); prefix is 'cases.' for the files endpoint."""
    if SCOPE["program"]:
        return f_in(f"{prefix}project.program.name", [SCOPE["program"]])
    return f_in(f"{prefix}project.project_id", SCOPE["projects"])
TARGET_GENES = ["CD8A", "CD8B", "FOXP3", "CD274", "MKI67"]
PRIMARY_TUMOUR_CODE = "01"  # TCGA sample-type code: 01 = Primary Solid Tumor


# ----------------------------------------------------------------------------
# GDC helpers
# ----------------------------------------------------------------------------
def f_and(*conds):
    return {"op": "and", "content": list(conds)}


def f_in(field, values):
    return {"op": "in", "content": {"field": field, "value": values}}


def gdc_query(endpoint, filters, fields, page_size=500):
    """Paginated POST query against a GDC list endpoint ('files' or 'cases')."""
    hits, start = [], 0
    while True:
        body = {
            "filters": filters,
            "fields": ",".join(fields),
            "size": page_size,
            "from": start,
            "format": "JSON",
        }
        r = requests.post(f"{GDC}/{endpoint}", json=body, timeout=120)
        r.raise_for_status()
        data = r.json()["data"]
        hits.extend(data["hits"])
        start += page_size
        if start >= data["pagination"]["total"]:
            break
    return hits


def sample_code(barcode):
    """'TCGA-05-4244-01Z-00-DX1' or 'TCGA-05-4244-01A' -> '01' (None if unparseable)."""
    parts = (barcode or "").split("-")
    if len(parts) >= 4 and len(parts[3]) >= 2:
        return parts[3][:2]
    return None


# ----------------------------------------------------------------------------
# Fetchers
# ----------------------------------------------------------------------------
def fetch_slides():
    filters = f_and(
        scope_filter("cases."),
        f_in("data_type", ["Slide Image"]),
    )
    fields = [
        "file_id", "file_name", "file_size", "md5sum", "state", "access",
        "experimental_strategy", "cases.submitter_id", "cases.case_id", "cases.project.project_id",
    ]
    rows = []
    for h in gdc_query("files", filters, fields):
        case = h["cases"][0]
        barcode = h["file_name"].split(".")[0]
        rows.append({
            "case_submitter_id": case["submitter_id"],
            "case_uuid": case["case_id"],
            "project_id": (case.get("project") or {}).get("project_id"),
            "slide_barcode": barcode,
            "sample_code": sample_code(barcode),
            "experimental_strategy": h.get("experimental_strategy"),
            "file_id": h["file_id"],
            "file_name": h["file_name"],
            "file_size": h.get("file_size"),
            "md5sum": h.get("md5sum"),
            "state": h.get("state"),
            "access": h.get("access"),
        })
    return pd.DataFrame(rows)


def fetch_rna_files():
    filters = f_and(
        scope_filter("cases."),
        f_in("data_type", ["Gene Expression Quantification"]),
        f_in("analysis.workflow_type", ["STAR - Counts"]),
        f_in("access", ["open"]),
    )
    fields = [
        "file_id", "file_name", "file_size",
        "cases.submitter_id", "cases.samples.submitter_id", "cases.samples.sample_type",
    ]
    rows = []
    for h in gdc_query("files", filters, fields):
        case = h["cases"][0]
        samples = case.get("samples") or [{}]
        s = samples[0]
        barcode = s.get("submitter_id")
        rows.append({
            "case_submitter_id": case["submitter_id"],
            "rna_sample_barcode": barcode,
            "sample_code": sample_code(barcode),
            "sample_type": s.get("sample_type"),
            "rna_file_id": h["file_id"],
            "rna_file_name": h["file_name"],
            "rna_file_size": h.get("file_size"),
        })
    return pd.DataFrame(rows)


def _max_or_none(values):
    vals = [v for v in values if v is not None]
    return max(vals) if vals else None


def fetch_clinical():
    base_fields = [
        "submitter_id", "case_id", "project.project_id",
        "demographic.gender", "demographic.vital_status", "demographic.days_to_death",
        "diagnoses.days_to_last_follow_up", "diagnoses.ajcc_pathologic_stage",
        "diagnoses.age_at_diagnosis", "diagnoses.primary_diagnosis",
    ]
    filters = scope_filter("")
    try:
        # Follow-up times for living patients are often stored in follow_ups, not diagnoses
        hits = gdc_query("cases", filters, base_fields + ["follow_ups.days_to_follow_up"])
    except requests.HTTPError as e:
        print(f"WARNING: follow_ups field rejected by GDC ({e}); using diagnoses only. "
              "Survival counts may be understated.", file=sys.stderr)
        hits = gdc_query("cases", filters, base_fields)

    rows = []
    for h in hits:
        demo = h.get("demographic") or {}
        diags = h.get("diagnoses") or [{}]
        fups = h.get("follow_ups") or []
        d = diags[0]
        vital = demo.get("vital_status")

        # Latest known follow-up across ALL diagnoses and ALL follow-up records
        last_fu = _max_or_none(
            [x.get("days_to_last_follow_up") for x in diags]
            + [x.get("days_to_follow_up") for x in fups]
        )
        if vital == "Dead":
            os_days, os_event = demo.get("days_to_death"), 1
            os_source = "days_to_death"
        elif vital == "Alive":
            os_days, os_event = last_fu, 0
            os_source = "last_follow_up"
        else:
            os_days, os_event, os_source = None, None, None
        age_days = d.get("age_at_diagnosis")
        rows.append({
            "case_submitter_id": h["submitter_id"],
            "case_uuid": h["case_id"],
            "project_id": (h.get("project") or {}).get("project_id"),
            "gender": demo.get("gender"),
            "vital_status": vital,
            "os_days": os_days,
            "os_event": os_event,
            "os_source": os_source,
            "stage": d.get("ajcc_pathologic_stage"),
            "primary_diagnosis": d.get("primary_diagnosis"),
            "age_years": round(age_days / 365.25, 1) if age_days else None,
            "n_diagnoses": len(diags),
            "n_followups": len(fups),
        })
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------
# Inventory
# ----------------------------------------------------------------------------
def build_inventory(slides, rna, clin):
    """Pure function (no network) so it can be tested offline."""
    # Tumour diagnostic (FFPE) slides only
    dx = slides[
        (slides["experimental_strategy"] == "Diagnostic Slide")
        & (slides["sample_code"] == PRIMARY_TUMOUR_CODE)
    ]
    dx_agg = (
        dx.sort_values("slide_barcode")
        .groupby("case_submitter_id")
        .agg(
            n_dx_slides=("file_id", "count"),
            dx_slide_barcodes=("slide_barcode", ";".join),
            dx_file_ids=("file_id", ";".join),
            dx_total_bytes=("file_size", "sum"),
        )
        .reset_index()
    )

    # Primary-tumour RNA-seq; if several aliquots, take the first deterministically
    rna_t = rna[rna["sample_code"] == PRIMARY_TUMOUR_CODE].sort_values(
        ["rna_sample_barcode", "rna_file_id"]
    )
    rna_agg = (
        rna_t.groupby("case_submitter_id")
        .agg(
            n_tumour_rna=("rna_file_id", "count"),
            rna_file_id=("rna_file_id", "first"),
            rna_sample_barcode=("rna_sample_barcode", "first"),
        )
        .reset_index()
    )

    inv = clin.merge(dx_agg, on="case_submitter_id", how="left").merge(
        rna_agg, on="case_submitter_id", how="left"
    )
    inv["n_dx_slides"] = inv["n_dx_slides"].fillna(0).astype(int)
    inv["n_tumour_rna"] = inv["n_tumour_rna"].fillna(0).astype(int)
    inv["dx_total_bytes"] = inv["dx_total_bytes"].fillna(0)

    inv["has_dx"] = inv["n_dx_slides"] > 0
    inv["has_tumour_rna"] = inv["n_tumour_rna"] > 0
    inv["has_survival"] = inv["os_days"].notna() & (inv["os_days"] > 0) & inv["os_event"].notna()
    inv["usable_biomarker"] = inv["has_dx"] & inv["has_tumour_rna"]
    inv["usable_survival"] = inv["has_dx"] & inv["has_survival"]
    inv["qc_status"] = "pending"  # filled after visual / tissue-detection QC
    return inv


def apply_cap(inv, max_per_project=None, seed=42):
    """Mark the cases to download. Without a cap: every case usable for either task."""
    inv = inv.copy()
    base = inv["usable_biomarker"] | inv["usable_survival"]
    inv["selected"] = False
    if not max_per_project:
        inv["selected"] = base
        return inv
    rng = np.random.default_rng(seed)
    for proj, grp in inv[base].groupby("project_id", dropna=False):
        grp = grp.sort_values("case_submitter_id")
        both = grp["usable_biomarker"] & grp["usable_survival"]
        prio = np.where(both, 0, np.where(grp["usable_biomarker"], 1, 2))
        order = np.lexsort((rng.random(len(grp)), prio))
        chosen = grp.iloc[order[:max_per_project]]["case_submitter_id"]
        inv.loc[inv["case_submitter_id"].isin(chosen), "selected"] = True
    return inv


def per_project_table(inv):
    g = inv.groupby("project_id", dropna=False)
    t = pd.DataFrame({
        "cases": g.size(),
        "with_DX": g["has_dx"].sum(),
        "biomarker": g["usable_biomarker"].sum(),
        "survival": g["usable_survival"].sum(),
        "both": g.apply(lambda d: int((d["usable_biomarker"] & d["usable_survival"]).sum()), include_groups=False),
        "selected": g["selected"].sum() if "selected" in inv.columns else g["usable_biomarker"].sum(),
        "GB_selected": g.apply(lambda d: round(d.loc[d.get("selected", d["usable_biomarker"]).astype(bool), "dx_total_bytes"].sum() / 1e9, 1),
                               include_groups=False),
    }).astype(int, errors="ignore")
    t.loc["TOTAL"] = t.sum()
    return t


def print_funnel(inv):
    n = len(inv)
    lines = [
        ("Cases in TCGA-LUAD (GDC)", n),
        ("... with >=1 tumour diagnostic (DX) slide", int(inv["has_dx"].sum())),
        ("... with primary-tumour RNA-seq", int(inv["has_tumour_rna"].sum())),
        ("... DX slide AND RNA-seq  [usable_biomarker]", int(inv["usable_biomarker"].sum())),
        ("... valid overall-survival data", int(inv["has_survival"].sum())),
        ("... DX slide AND survival  [usable_survival]", int(inv["usable_survival"].sum())),
        ("... usable for BOTH", int((inv["usable_biomarker"] & inv["usable_survival"]).sum())),
        ("Cases with >1 DX slide (patient-level split matters)", int((inv["n_dx_slides"] > 1).sum())),
        ("Cases with >1 tumour RNA aliquot (first one used)", int((inv["n_tumour_rna"] > 1).sum())),
    ]
    print("\n=== TCGA-LUAD inventory funnel ===")
    for label, val in lines:
        print(f"{label:<58} {val:>5}")
    ub = inv[inv["usable_biomarker"]]
    print(f"\nTumour DX slides for usable_biomarker cases: {int(ub['n_dx_slides'].sum())}")
    print(f"Approx. download size for those slides: {ub['dx_total_bytes'].sum() / 1e9:.1f} GB")
    surv = inv[inv["usable_survival"]]
    if len(surv):
        cens = 100 * (1 - surv["os_event"].mean())
        print(f"Survival cohort: {int(surv['os_event'].sum())} events / {len(surv)} cases "
              f"({cens:.0f}% censored)")
        if cens < 20:
            print("WARNING: censoring is implausibly low for this cohort -> survival "
                  "extraction is probably missing living patients. Check diagnostics below.")

    if "project_id" in inv.columns and inv["project_id"].nunique() > 1:
        print("\n--- Per cancer type ---")
        print(per_project_table(inv).to_string())

    print("\n--- Survival diagnostics (all cases) ---")
    print("vital_status counts:", inv["vital_status"].value_counts(dropna=False).to_dict())
    alive = inv[inv["vital_status"] == "Alive"]
    dead = inv[inv["vital_status"] == "Dead"]
    print(f"Alive with a valid follow-up time: {int((alive['os_days'] > 0).sum())}/{len(alive)}")
    print(f"Dead with a valid days_to_death:   {int((dead['os_days'] > 0).sum())}/{len(dead)}")
    if "n_followups" in inv.columns:
        print(f"Cases with >=1 follow_ups record:  {int((inv['n_followups'] > 0).sum())}")


def write_manifest(slides, inv, path):
    sel = inv["selected"].astype(bool) if "selected" in inv.columns else (inv["usable_biomarker"] | inv["usable_survival"])
    keep = set(inv[sel]["case_submitter_id"])
    m = slides[
        (slides["experimental_strategy"] == "Diagnostic Slide")
        & (slides["sample_code"] == PRIMARY_TUMOUR_CODE)
        & (slides["case_submitter_id"].isin(keep))
    ]
    out = pd.DataFrame({
        "id": m["file_id"], "filename": m["file_name"],
        "md5": m["md5sum"], "size": m["file_size"], "state": m["state"],
    })
    out.to_csv(path, sep="\t", index=False)
    return len(out)


# ----------------------------------------------------------------------------
# Stage 2: RNA targets
# ----------------------------------------------------------------------------
def download_file(file_id, dest, session=None, retries=4):
    if dest.exists() and dest.stat().st_size > 0:
        return False  # already downloaded
    get = (session or requests).get
    last = None
    for attempt in range(retries):
        try:
            # (connect timeout, read timeout) so a stalled server fails fast and retries
            r = get(f"{GDC}/data/{file_id}", timeout=(10, 60))
            r.raise_for_status()
            tmp = dest.with_suffix(".part")
            tmp.write_bytes(r.content)
            tmp.replace(dest)  # atomic: a half-written file never looks complete
            return True
        except requests.RequestException as e:
            last = e
            wait = 2 ** attempt
            print(f"  retry {attempt + 1}/{retries} for {file_id} ({type(e).__name__}); waiting {wait}s",
                  flush=True)
            time.sleep(wait)
    raise RuntimeError(f"Failed to download {file_id}: {last}")


def read_targets(path):
    """Extract target-gene values from a GDC STAR gene-counts TSV."""
    df = pd.read_csv(path, sep="\t", comment="#")
    out = {}
    for g in TARGET_GENES:
        sub = df[df["gene_name"] == g]
        if len(sub) != 1:
            print(f"  WARNING: {g} matched {len(sub)} rows in {path.name}", file=sys.stderr)
        if len(sub) == 0:
            out[f"{g}_counts"] = math.nan
            out[f"{g}_log2tpm"] = math.nan
            continue
        row = sub.iloc[0]
        out[f"{g}_counts"] = row["unstranded"]
        out[f"{g}_log2tpm"] = math.log2(row["tpm_unstranded"] + 1)
    out["CD8_mean_log2tpm"] = (out["CD8A_log2tpm"] + out["CD8B_log2tpm"]) / 2
    return out


def stage_rna(out_dir, prefix="luad"):
    inv = pd.read_csv(out_dir / f"{prefix}_inventory.csv")
    todo = inv[inv["usable_biomarker"]]
    if "selected" in inv.columns:
        todo = todo[todo["selected"].astype(bool)]
    raw_dir = out_dir / "rna_raw"
    raw_dir.mkdir(exist_ok=True)
    records = []
    session = requests.Session()
    t0 = time.time()
    print(f"Downloading RNA files for {len(todo)} cases into {raw_dir} "
          "(safe to Ctrl+C and rerun; finished files are skipped)", flush=True)
    for i, row in enumerate(todo.itertuples(), 1):
        dest = raw_dir / f"{row.rna_file_id}.tsv"
        fresh = download_file(row.rna_file_id, dest, session=session)
        rec = {"case_submitter_id": row.case_submitter_id}
        rec.update(read_targets(dest))
        records.append(rec)
        print(f"  [{i}/{len(todo)}] {row.case_submitter_id} "
              f"{'downloaded' if fresh else 'cached'}  ({time.time() - t0:.0f}s elapsed)", flush=True)
    merged = inv.merge(pd.DataFrame(records), on="case_submitter_id", how="left")
    merged.to_csv(out_dir / f"{prefix}_inventory_with_targets.csv", index=False)
    print(f"Wrote {out_dir / (prefix + '_inventory_with_targets.csv')}")


# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("stage", choices=["inventory", "rna"])
    ap.add_argument("--out-dir", default="luad_out")
    ap.add_argument("--prefix", default="luad", help="file-name prefix (e.g. tcga for multi-cancer runs)")
    ap.add_argument("--projects", default="TCGA-LUAD", help="comma-separated GDC project ids")
    ap.add_argument("--all-tcga", action="store_true", help="every TCGA project (very large; use with a cap)")
    ap.add_argument("--max-per-project", type=int, default=None, help="cap selected cases per cancer type")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    SCOPE["projects"] = [p.strip() for p in args.projects.split(",") if p.strip()]
    SCOPE["program"] = "TCGA" if args.all_tcga else None
    pre = args.prefix

    if args.stage == "inventory":
        what = "all TCGA projects" if args.all_tcga else ", ".join(SCOPE["projects"])
        print(f"Querying GDC (metadata only) for: {what}")
        slides = fetch_slides()
        rna = fetch_rna_files()
        clin = fetch_clinical()
        slides.to_csv(out_dir / f"{pre}_slides_all.csv", index=False)
        inv = apply_cap(build_inventory(slides, rna, clin), args.max_per_project, args.seed)
        inv.to_csv(out_dir / f"{pre}_inventory.csv", index=False)
        n = write_manifest(slides, inv, out_dir / "gdc_manifest_dx_usable.tsv")
        print_funnel(inv)
        sel = inv[inv["selected"]]
        print(f"\nSelected {len(sel)} cases; manifest has {n} slides, about "
              f"{sel['dx_total_bytes'].sum() / 1e9:.0f} GB.")
        print(f"Wrote inventory + manifest to {out_dir}/")
    else:
        stage_rna(out_dir, pre)


if __name__ == "__main__":
    main()
