#!/usr/bin/env python3
"""
Attention-based multiple-instance learning (gated ABMIL) on frozen patch features, frozen 5-fold dev CV.

    python train_abmil.py --target MKI67 --overfit 20                 # 1. sanity check: must memorise 20 slides
    python train_abmil.py --target MKI67 --seeds 1 --epochs 5         # 2. quick smoke test of the whole loop
    python train_abmil.py --target MKI67 --features-dir features_uni --out results_abmil_uni --save-attention
    python train_abmil.py --target MKI67 --features-dir features_uni --control-repeats 3   # 3. shuffled-label control

Put this file next to train_baseline.py: it imports the label, shuffle and bootstrap code from there, so the baseline
and ABMIL are scored with exactly the same rules.

Rules it follows (same as the baseline)
  * Only split == "dev" cases are read. The test split is never loaded.
  * High/low label = above the per-cancer MEDIAN of the TRAINING folds only.
  * 5-fold CV with the frozen `fold` column. For each round, an inner validation set is carved out of the TRAINING
    folds (stratified by cancer x label, by case) and used ONLY for early stopping. The held-out CV fold is used
    only to score the final model, once.
  * Several seeds; the reported probability is the mean over seeds. AUROC pooled and per cancer with bootstrap CIs.
  * Control: --control-repeats R repeats the whole CV with training labels shuffled within each cancer.

Model: patch features -> Linear+ReLU+Dropout -> gated attention (Ilse et al. 2018) -> weighted sum -> Linear -> logit.
Each training bag is randomly sub-sampled to --train-max-patches patches per epoch (speed + augmentation);
validation and test use ALL kept patches of the case (all of its slides).

Memory: all kept patch features of the dev cases are held in RAM as float16 (printed at start).
UNI (1024-d) needs about half of ResNet50 (2048-d). Lower --max-cases to test with less.

--save-attention writes results/attention/<target>/<case>.npz for each held-out case (from the model that did NOT
train on it, seed 0 only): attention, coords (level-0 pixels), slide_idx, slides, p_high.
Attention shows where the model looked, not proof that those regions cause the biomarker.

NOT TESTED WITH TORCH by the author: the data/fold/label/control logic was tested offline with a fake trainer;
the PyTorch model and training loop need a first run on your PC. Start with --overfit 20.
"""
import argparse
import time
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from sklearn.metrics import roc_auc_score

from train_baseline import ALIASES, labels_from_train_median, shuffle_within_cancer, summarise


# ----------------------------------------------------------------------------
class ABMIL(nn.Module):
    def __init__(self, dim, hidden=128, attn=64, dropout=0.25):
        super().__init__()
        self.embed = nn.Sequential(nn.Linear(dim, hidden), nn.ReLU(), nn.Dropout(dropout))
        self.att_v = nn.Linear(hidden, attn)
        self.att_u = nn.Linear(hidden, attn)
        self.att_w = nn.Linear(attn, 1)
        self.drop = nn.Dropout(dropout)
        self.head = nn.Linear(hidden, 1)

    def forward(self, x):                      # x: (N, D) one bag
        h = self.embed(x)                      # (N, hidden)
        a = self.att_w(torch.tanh(self.att_v(h)) * torch.sigmoid(self.att_u(h))).squeeze(-1)   # (N,)
        a = torch.softmax(a, dim=0)
        z = (a.unsqueeze(-1) * h).sum(0)       # (hidden,)
        return self.head(self.drop(z)).squeeze(-1), a


# ----------------------------------------------------------------------------
def load_bags(features_dir, cases, max_white, min_lapvar):
    """case id -> dict(X float16 (n,D), coords (n,2), slide (n,) index into slides, slides [names])."""
    want, raw = set(cases), {}
    for p in sorted(Path(features_dir).glob("*.h5")):
        case = p.stem[:12]
        if case not in want:
            continue
        with h5py.File(p) as f:
            X, C, w, lv = f["features"][:], f["coords"][:], f["white_frac"][:], f["lapvar"][:]
        keep = (w <= max_white) & (lv >= min_lapvar)
        if not keep.any():
            continue
        b = raw.setdefault(case, dict(X=[], coords=[], slide=[], slides=[]))
        b["slides"].append(p.stem)
        b["X"].append(X[keep])
        b["coords"].append(C[keep])
        b["slide"].append(np.full(int(keep.sum()), len(b["slides"]) - 1, np.int16))
    return {c: dict(X=np.concatenate(b["X"]), coords=np.concatenate(b["coords"]),
                    slide=np.concatenate(b["slide"]), slides=b["slides"]) for c, b in raw.items()}


def inner_split(ids, y, projects, val_frac, rng):
    """Indices (into ids) of (inner-train, inner-val), stratified by cancer x label. Uses training cases only."""
    keys = np.array([f"{p}|{v}" for p, v in zip(projects, y)])
    tr, va = [], []
    for k in np.unique(keys):
        idx = rng.permutation(np.where(keys == k)[0])
        n_val = int(round(len(idx) * val_frac))
        if len(idx) >= 4:
            n_val = max(n_val, 1)
        va += list(idx[:n_val])
        tr += list(idx[n_val:])
    return np.array(sorted(tr), dtype=int), np.array(sorted(va), dtype=int)


def bag_tensor(bag, max_patches, rng, device):
    X = bag["X"]
    if max_patches and len(X) > max_patches:
        X = X[np.sort(rng.choice(len(X), max_patches, replace=False))]
    return torch.from_numpy(np.ascontiguousarray(X)).to(device).float()


def predict(model, bags, cases, device):
    """-> logits (len(cases),), list of attention arrays. Uses ALL kept patches of each case."""
    model.eval()
    logits, atts = [], []
    with torch.no_grad():
        for c in cases:
            x = torch.from_numpy(np.ascontiguousarray(bags[c]["X"])).to(device).float()
            lg, a = model(x)
            logits.append(float(lg.item()))
            atts.append(a.cpu().numpy())
    return np.array(logits), atts


def bce_from_logits(logit, y):
    return float(np.mean(np.logaddexp(0, logit) - y * logit))


def train_model(bags, tr_ids, ytr, val_ids, yval, args, seed, device, dim, epochs, dropout, lr, verbose=True):
    """Train one ABMIL. Early stopping on inner-val loss if val_ids is non-empty; else the last epoch is used."""
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    model = ABMIL(dim, args.hidden, args.attn, dropout).to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=args.wd)
    lossf = nn.BCEWithLogitsLoss()
    best, best_state, best_ep, bad = float("inf"), None, 0, 0
    for ep in range(1, epochs + 1):
        model.train()
        order = rng.permutation(len(tr_ids))
        tl = 0.0
        opt.zero_grad()
        for j, i in enumerate(order, 1):
            x = bag_tensor(bags[tr_ids[i]], args.train_max_patches, rng, device)
            logit, _ = model(x)
            loss = lossf(logit, torch.tensor(float(ytr[i]), device=device))
            (loss / args.bag_batch).backward()
            tl += float(loss.item())
            if j % args.bag_batch == 0 or j == len(order):
                opt.step()
                opt.zero_grad()
        tl /= len(order)
        if len(val_ids):
            vlog, _ = predict(model, bags, val_ids, device)
            vl = bce_from_logits(vlog, np.asarray(yval, float))
            if vl < best - 1e-4:
                best, best_ep, bad = vl, ep, 0
                best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
            else:
                bad += 1
            if verbose and (ep == 1 or ep % 5 == 0):
                print(f"      epoch {ep:3d}  train loss {tl:.3f}  inner-val loss {vl:.3f}", flush=True)
            if bad >= args.patience:
                break
        elif verbose and (ep == 1 or ep % 10 == 0):
            print(f"      epoch {ep:3d}  train loss {tl:.3f}", flush=True)
    if best_state is not None:
        model.load_state_dict(best_state)
    return model, best_ep, best


# ----------------------------------------------------------------------------
def run_cv(dev, col, seeds, args, trainer, control=False, base_seed=0):
    """5-fold CV on the frozen folds. trainer(train_ids, ytr, val_ids, yval, test_ids, seed) -> (probs, info)."""
    parts = []
    for k in sorted(dev["fold"].unique()):
        tr, te = dev[dev["fold"] != k], dev[dev["fold"] == k]
        ytr, yte = labels_from_train_median(tr, te, col)
        if control:
            ytr = shuffle_within_cancer(ytr, tr["project_id"].values, np.random.default_rng(1000 * base_seed + k))
        tr_ids, te_ids = tr["case_submitter_id"].values, te["case_submitter_id"].values
        df = pd.DataFrame({"fold": k, "case_submitter_id": te_ids, "project_id": te["project_id"].values, "y": yte})
        for s in seeds:
            rng = np.random.default_rng(100000 * base_seed + 1000 * s + k)
            itr, iva = inner_split(tr_ids, ytr, tr["project_id"].values, args.val_frac, rng)
            t0 = time.time()
            p, info = trainer(tr_ids[itr], ytr[itr], tr_ids[iva], ytr[iva], te_ids, s)
            df[f"p_seed{s}"] = p
            auc = roc_auc_score(yte, p) if len(np.unique(yte)) == 2 else float("nan")
            print(f"  fold {k} seed {s}: held-out AUROC {auc:.3f} (n={len(te_ids)}), {info}, {time.time() - t0:.0f}s",
                  flush=True)
        parts.append(df)
    oof = pd.concat(parts, ignore_index=True)
    oof["p"] = oof[[f"p_seed{s}" for s in seeds]].mean(axis=1)
    return oof


def make_trainer(bags, args, device, dim, out_dir, target, first_seed, keep_attention):
    def trainer(tr_ids, ytr, val_ids, yval, te_ids, seed):
        model, best_ep, best = train_model(bags, tr_ids, ytr, val_ids, yval, args, seed, device, dim,
                                           args.epochs, args.dropout, args.lr)
        logits, atts = predict(model, bags, te_ids, device)
        p = 1.0 / (1.0 + np.exp(-logits))
        if keep_attention and seed == first_seed:
            d = out_dir / "attention" / target
            d.mkdir(parents=True, exist_ok=True)
            for c, a, pr in zip(te_ids, atts, p):
                b = bags[c]
                np.savez_compressed(d / f"{c}.npz", attention=a.astype(np.float32), coords=b["coords"],
                                    slide_idx=b["slide"], slides=np.array(b["slides"]), p_high=pr)
        return p, f"best epoch {best_ep}, inner-val loss {best:.3f}"
    return trainer


def overfit_check(bags, dev, col, args, device, dim):
    """Train on N cases with no dropout and no validation: the model must be able to memorise them (AUROC ~1)."""
    med = dev.groupby("project_id")[col].median()
    sub = dev.sample(n=min(args.overfit, len(dev)), random_state=args.seed)
    y = (sub[col] > sub["project_id"].map(med)).astype(int).values
    ids = sub["case_submitter_id"].values
    print(f"Overfit check on {len(ids)} cases ({int(y.sum())} high / {int((1 - y).sum())} low), no dropout, no val.")
    if len(np.unique(y)) < 2:
        raise SystemExit("Only one class in this sample; use a larger --overfit.")
    args.patience = 10 ** 9
    model, _, _ = train_model(bags, ids, y, np.array([]), np.array([]), args, args.seed, device, dim,
                              epochs=100, dropout=0.0, lr=1e-3)
    logit, _ = predict(model, bags, ids, device)
    auc = roc_auc_score(y, logit)
    acc = float(((logit > 0).astype(int) == y).mean())
    print(f"\nTraining-set AUROC {auc:.3f}, accuracy {acc:.2f} (expected: about 1.0 / 1.0).")
    print("PASS: model can memorise." if auc > 0.98 else
          "FAIL: could not memorise 20 slides. Likely a bug or a bad learning rate; copy the loss lines above.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target", default="MKI67")
    ap.add_argument("--features-dir", default="features")
    ap.add_argument("--splits", default=r"tcga_out\splits_frozen.csv")
    ap.add_argument("--targets-file", default=r"tcga_out\tcga_inventory_with_targets.csv")
    ap.add_argument("--out", default="results_abmil")
    ap.add_argument("--max-white", type=float, default=0.8)
    ap.add_argument("--min-lapvar", type=float, default=0.0)
    ap.add_argument("--hidden", type=int, default=128)
    ap.add_argument("--attn", type=int, default=64)
    ap.add_argument("--dropout", type=float, default=0.25)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--wd", type=float, default=1e-4)
    ap.add_argument("--epochs", type=int, default=50)
    ap.add_argument("--patience", type=int, default=10, help="early stopping on inner-validation loss")
    ap.add_argument("--bag-batch", type=int, default=8, help="bags per optimiser step (gradient accumulation)")
    ap.add_argument("--train-max-patches", type=int, default=2000, help="random patches per training bag per epoch")
    ap.add_argument("--val-frac", type=float, default=0.15, help="share of TRAINING cases used for early stopping")
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--bootstrap", type=int, default=1000)
    ap.add_argument("--control-repeats", type=int, default=0, help="shuffled-label CV repeats (each is a full CV)")
    ap.add_argument("--overfit", type=int, default=0, help="N>0: only run the memorise-N-cases sanity check")
    ap.add_argument("--save-attention", action="store_true")
    ap.add_argument("--max-cases", type=int, default=None, help="debug: use at most this many dev cases")
    ap.add_argument("--device", default="auto")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    col = ALIASES.get(args.target.upper(), args.target)
    sp, tg = pd.read_csv(args.splits), pd.read_csv(args.targets_file)
    if col not in tg.columns:
        raise SystemExit(f"Column {col} not found in {args.targets_file}.")
    if not tg["case_submitter_id"].is_unique:
        raise SystemExit("targets file has duplicate case ids; merging would duplicate cases. Fix it first.")
    df = sp.merge(tg[["case_submitter_id", col]], on="case_submitter_id", how="left")
    dev_all = df[df["split"] == "dev"]            # the test split is never loaded past this line
    del df

    bags = load_bags(args.features_dir, dev_all["case_submitter_id"], args.max_white, args.min_lapvar)
    dev = dev_all[dev_all["case_submitter_id"].isin(bags) & dev_all[col].notna()
                  & dev_all["usable_biomarker"].astype(bool)].copy()
    if args.max_cases:
        dev = dev.sample(n=min(args.max_cases, len(dev)), random_state=args.seed)
    bags = {c: bags[c] for c in dev["case_submitter_id"]}
    dim = next(iter(bags.values()))["X"].shape[1] if bags else 0
    gb = sum(b["X"].nbytes for b in bags.values()) / 1e9
    print(f"Target {args.target} ({col}). Dev cases with features and a label: {len(dev)} "
          f"(of {len(dev_all)} dev cases). Feature dim {dim}; bags in RAM about {gb:.1f} GB.")
    print(dev.groupby("project_id").size().rename("cases per cancer").to_string())
    if len(dev) < 30 or dev["fold"].nunique() < 2:
        raise SystemExit("Too few cases with features yet.")
    dev_slides = sum(len(b["slides"]) for b in bags.values())
    print(f"{dev_slides} slides in these bags. Cases whose other slides are not processed yet use only what exists; "
          "for final results wait until every slide is done.")

    device = torch.device("cuda" if (args.device == "auto" and torch.cuda.is_available())
                          else ("cpu" if args.device == "auto" else args.device))
    print(f"Device: {device}" + (f" ({torch.cuda.get_device_name(0)})" if device.type == "cuda" else ""))

    if args.overfit:
        overfit_check(bags, dev, col, args, device, dim)
        return

    out = Path(args.out)
    out.mkdir(exist_ok=True)
    seeds = list(range(args.seeds))
    trainer = make_trainer(bags, args, device, dim, out, args.target, seeds[0], args.save_attention)
    t0 = time.time()
    print(f"\n=== ABMIL, 5-fold CV on dev, {len(seeds)} seed(s) ===")
    oof = run_cv(dev, col, seeds, args, trainer)
    tab, fold_aucs = summarise(oof, args.bootstrap, args.seed)
    seed_aucs = [roc_auc_score(oof["y"], oof[f"p_seed{s}"]) for s in seeds]

    print("\n=== ABMIL result (probability = mean over seeds) ===")
    print(tab.round(3).to_string(index=False))
    if fold_aucs:
        print(f"Per-fold AUROC: mean {np.mean(fold_aucs):.3f} +- {np.std(fold_aucs):.3f} over {len(fold_aucs)} folds")
    print("Pooled AUROC per seed: " + ", ".join(f"{a:.3f}" for a in seed_aucs))
    real_auc = float(np.mean(seed_aucs))

    if args.control_repeats:
        print(f"\n=== Control: training labels shuffled within cancer, {args.control_repeats} full CV repeats ===")
        ctrl = []
        for r in range(args.control_repeats):
            c = run_cv(dev, col, [0], args, trainer, control=True, base_seed=r + 1)
            ctrl.append(roc_auc_score(c["y"], c["p"]))
            print(f"  control repeat {r + 1}: pooled AUROC {ctrl[-1]:.3f}", flush=True)
        ctrl = np.array(ctrl)
        pv = (1 + int((ctrl >= real_auc).sum())) / (len(ctrl) + 1)
        print(f"Shuffled runs: mean {ctrl.mean():.3f}, SD {ctrl.std():.3f}, range {ctrl.min():.3f} to {ctrl.max():.3f}")
        print(f"Real mean-over-seeds pooled AUROC {real_auc:.3f}; permutation p-value {pv:.3f} "
              f"(smallest possible {1 / (len(ctrl) + 1):.3f}; conservative: single-seed null)")
        print("Control OK: shuffled runs average about 0.5." if abs(ctrl.mean() - 0.5) <= 0.05 else
              "WARNING: shuffled runs do not average 0.5. Possible leakage. Do not trust the result yet.")

    oof.to_csv(out / f"abmil_oof_{args.target}.csv", index=False)
    tab.to_csv(out / f"abmil_{args.target}.csv", index=False)
    print(f"\nSaved to {out}\\ in {(time.time() - t0) / 60:.1f} min (test split was not used)")


if __name__ == "__main__":
    main()
