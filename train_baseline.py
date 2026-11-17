#!/usr/bin/env python3
"""
Baseline: mean-pooled patch features + logistic regression, using the FROZEN 5-fold split.

    python train_baseline.py --target MKI67
    python train_baseline.py --target CD274 --features-dir features_uni --out results_uni

What it does
  * Uses ONLY development cases (split == "dev"). The test split is never read or scored.
  * Case-level feature = mean of all kept patch features over all of that case's slides.
    Patches with white_frac > --max-white (mostly empty glass) are dropped.
  * Label (high / low) = value above the MEDIAN of the training folds, computed SEPARATELY FOR EACH CANCER TYPE.
    The threshold uses training cases only, so nothing leaks from the validation fold, and because classes are
    balanced inside every cancer, the model cannot score well just by recognising the cancer type.
  * 5-fold cross-validation with the `fold` column from splits_frozen.csv; logistic regression with the
    regularisation strength chosen by an inner 3-fold CV on the training folds only.
  * Reports AUROC pooled and per cancer type with bootstrap 95% CIs, plus per-fold mean +- SD.
  * CONTROL (permutation test): repeats the experiment --control-repeats times with the training labels shuffled
    within each cancer. The average over repeats should be about 0.5; a single run can land well away from 0.5
    by chance (a model fitted to random labels points in a random direction), so only the average and the spread
    are meaningful. Your real AUROC is then compared with this null distribution (permutation p-value).
    If the average is far from 0.5, something is leaking and the real result cannot be trusted.

Only slides that already have features are used, so you can run this while extraction is still going.
Targets: MKI67 (Ki-67), CD274 (PD-L1), FOXP3, CD8 (mean of CD8A and CD8B), or any *_log2tpm column name.
Requires: numpy, pandas, h5py, scikit-learn.
"""
import argparse
import warnings
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegressionCV
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

ALIASES = {"MKI67": "MKI67_log2tpm", "KI67": "MKI67_log2tpm", "CD274": "CD274_log2tpm",
           "PDL1": "CD274_log2tpm", "FOXP3": "FOXP3_log2tpm", "CD8": "CD8_mean_log2tpm"}


def load_case_features(features_dir, max_white, min_lapvar):
    """case id (first 12 chars of the slide name) -> mean feature vector over all kept patches of all its slides."""
    acc = {}
    for p in sorted(Path(features_dir).glob("*.h5")):
        with h5py.File(p) as f:
            X = f["features"][:].astype(np.float32)
            w, lv = f["white_frac"][:], f["lapvar"][:]
        keep = (w <= max_white) & (lv >= min_lapvar)
        if not keep.any():
            continue
        s, n = acc.get(p.stem[:12], (0.0, 0))
        acc[p.stem[:12]] = (s + X[keep].sum(0, dtype=np.float64), n + int(keep.sum()))
    return {c: s / n for c, (s, n) in acc.items()}


def labels_from_train_median(train, test, col):
    med = train.groupby("project_id")[col].median()
    ytr = (train[col] > train["project_id"].map(med)).astype(int).values
    yte = (test[col] > test["project_id"].map(med)).astype(int).values
    return ytr, yte


def shuffle_within_cancer(y, projects, rng):
    y = y.copy()
    for p in np.unique(projects):
        idx = np.where(projects == p)[0]
        y[idx] = rng.permutation(y[idx])
    return y


def fit_predict(Xtr, ytr, Xte, seed):
    model = make_pipeline(
        StandardScaler(),
        LogisticRegressionCV(Cs=[1e-3, 1e-2, 1e-1, 1.0], cv=3, scoring="roc_auc", max_iter=3000,
                             class_weight="balanced", random_state=seed))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model.fit(Xtr, ytr)
    return model.predict_proba(Xte)[:, 1]


def auc_ci(y, p, n_boot, rng):
    y, p = np.asarray(y), np.asarray(p)
    if len(np.unique(y)) < 2:
        return np.nan, np.nan, np.nan
    auc = roc_auc_score(y, p)
    boots = []
    for _ in range(n_boot):
        i = rng.integers(0, len(y), len(y))
        if len(np.unique(y[i])) == 2:
            boots.append(roc_auc_score(y[i], p[i]))
    lo, hi = np.percentile(boots, [2.5, 97.5]) if boots else (np.nan, np.nan)
    return auc, lo, hi


def cross_validate(dev, X, col, seed, control=False):
    rng = np.random.default_rng(seed)
    rows = []
    for k in sorted(dev["fold"].unique()):
        tr, te = dev[dev["fold"] != k], dev[dev["fold"] == k]
        ytr, yte = labels_from_train_median(tr, te, col)
        if control:
            ytr = shuffle_within_cancer(ytr, tr["project_id"].values, rng)
        p = fit_predict(X.loc[tr["case_submitter_id"]].values, ytr, X.loc[te["case_submitter_id"]].values, seed)
        rows.append(pd.DataFrame({"fold": k, "case_submitter_id": te["case_submitter_id"].values,
                                  "project_id": te["project_id"].values, "y": yte, "p": p}))
    return pd.concat(rows, ignore_index=True)


def summarise(oof, n_boot, seed):
    rng = np.random.default_rng(seed)
    out = []
    a, lo, hi = auc_ci(oof["y"], oof["p"], n_boot, rng)
    out.append(("ALL (pooled)", len(oof), a, lo, hi))
    for proj, g in oof.groupby("project_id"):
        a, lo, hi = auc_ci(g["y"], g["p"], n_boot, rng)
        out.append((proj, len(g), a, lo, hi))
    fold_aucs = [roc_auc_score(g["y"], g["p"]) for _, g in oof.groupby("fold") if g["y"].nunique() == 2]
    return pd.DataFrame(out, columns=["group", "n_cases", "AUROC", "CI_low", "CI_high"]), fold_aucs


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target", default="MKI67")
    ap.add_argument("--features-dir", default="features")
    ap.add_argument("--splits", default=r"tcga_out\splits_frozen.csv")
    ap.add_argument("--targets-file", default=r"tcga_out\tcga_inventory_with_targets.csv")
    ap.add_argument("--out", default="results")
    ap.add_argument("--max-white", type=float, default=0.8, help="drop patches with more white than this")
    ap.add_argument("--min-lapvar", type=float, default=0.0, help="drop blurrier patches (0 = keep all)")
    ap.add_argument("--bootstrap", type=int, default=1000)
    ap.add_argument("--control-repeats", type=int, default=10, help="shuffled-label repeats (0 = skip)")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    col = ALIASES.get(args.target.upper(), args.target)
    sp = pd.read_csv(args.splits)
    tg = pd.read_csv(args.targets_file)
    if col not in tg.columns:
        raise SystemExit(f"Column {col} not found in {args.targets_file}. Available: "
                         f"{[c for c in tg.columns if c.endswith('log2tpm')]}")
    df = sp.merge(tg[["case_submitter_id", col]], on="case_submitter_id", how="left")

    dev_all = df[df["split"] == "dev"]
    assert "test" not in set(dev_all["split"]), "the test split must never be used here"
    feats = load_case_features(args.features_dir, args.max_white, args.min_lapvar)
    dev = dev_all[dev_all["case_submitter_id"].isin(feats) & dev_all[col].notna()
                  & dev_all["usable_biomarker"].astype(bool)].copy()
    print(f"Target {args.target} ({col}). Dev cases in frozen split: {len(dev_all)}; "
          f"with features and a label: {len(dev)}")
    print(dev.groupby("project_id").size().rename("cases per cancer").to_string())
    if dev["fold"].nunique() < 2 or len(dev) < 30:
        raise SystemExit("Too few cases with features yet. Let the pipeline run longer, then try again.")
    X = pd.DataFrame(feats).T.loc[dev["case_submitter_id"]]

    oof = cross_validate(dev, X, col, args.seed)
    tab, fold_aucs = summarise(oof, args.bootstrap, args.seed)
    real_auc = tab.iloc[0]["AUROC"]
    ctrl_aucs = []
    for r in range(args.control_repeats):
        c = cross_validate(dev, X, col, args.seed + 1000 + r, control=True)
        ctrl_aucs.append(roc_auc_score(c["y"], c["p"]))
    ctrl_aucs = np.array(ctrl_aucs)

    print("\n=== Baseline: mean-pooled features + logistic regression (5-fold CV on dev) ===")
    print(tab.round(3).to_string(index=False))
    if fold_aucs:
        print(f"Per-fold AUROC: mean {np.mean(fold_aucs):.3f} +- {np.std(fold_aucs):.3f} over {len(fold_aucs)} folds")
    if len(ctrl_aucs):
        m, sd = ctrl_aucs.mean(), ctrl_aucs.std()
        p = (1 + int((ctrl_aucs >= real_auc).sum())) / (len(ctrl_aucs) + 1)
        print(f"\n=== Control: training labels shuffled, {len(ctrl_aucs)} repeats ===")
        print(f"Pooled AUROC of shuffled runs: mean {m:.3f}, SD {sd:.3f}, range {ctrl_aucs.min():.3f} to {ctrl_aucs.max():.3f}")
        print(f"Real pooled AUROC {real_auc:.3f}; permutation p-value {p:.3f} "
              f"(smallest possible with {len(ctrl_aucs)} repeats: {1 / (len(ctrl_aucs) + 1):.3f})")
        tol = max(0.05, 3 * sd / np.sqrt(len(ctrl_aucs)))
        print("Control OK: shuffled runs average about 0.5." if abs(m - 0.5) <= tol else
              "WARNING: shuffled runs do not average 0.5. Possible leakage. Do not trust the result yet.")

    out = Path(args.out)
    out.mkdir(exist_ok=True)
    oof.to_csv(out / f"baseline_oof_{args.target}.csv", index=False)
    tab.to_csv(out / f"baseline_{args.target}.csv", index=False)
    print(f"\nSaved to {out}\\ (test split was not used)")


if __name__ == "__main__":
    main()
