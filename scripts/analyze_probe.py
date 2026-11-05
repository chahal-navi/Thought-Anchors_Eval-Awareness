"""Exp 1: when is the final verdict linearly decodable from the residual stream?

Data: results/acts_<model>.npz from gpu/overnight.py extract: for each of the 200 sampled CoTs per model,
activations at the prompt end, at the end of every sentence, and at the answer position, at 8 layers.
Prompts are ~half EVAL / half DEPLOY, so the prompt alone cannot predict the label (the prompt-end
activation is identical for all 20 samples of a prompt -> AUC 0.5 by construction).

Probe: standardise + logistic regression, trained on all sentence positions pooled, label = final verdict.
Evaluation: leave-one-prompt-out (train on 9 prompts, test on the 10th), AUC by relative position in the CoT.
For the 20 base runs, the probe's P(EVAL) per sentence is compared with the resampled P(EVAL) curve and lock-in.
If results/fresh_<model>_acts.npz exists (fresh CoTs generated overnight), a probe trained on all 200 is
tested on them.

Usage:
    python analyze_probe.py
"""

import json

import numpy as np
from scipy.stats import spearmanr
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from common import CAPSTONE_DIR

RES = CAPSTONE_DIR / "results"
PATHS = {"qwen": RES, "gemma": RES / "gemma"}
BINS = np.linspace(0, 1, 11)


def load(path):
    z = np.load(path)
    meta = json.loads(str(z["meta"]))
    off = z["offsets"]
    return z["feats"], off, z["layers"], meta


def rows(feats, off, meta, layer_i):
    """X (sentence positions only), y, prompt group, sample id, relative position."""
    X, y, g, sid, rel = [], [], [], [], []
    for n, m in enumerate(meta):
        f = feats[off[n]:off[n + 1], layer_i].astype(np.float32)
        k = m["n_sent"]
        for j in range(k):
            X.append(f[1 + j]); y.append(m["label"] == "EVALUATION"); g.append(m["prompt"]); sid.append(n); rel.append((j + 1) / k)
    return np.array(X), np.array(y), np.array(g), np.array(sid), np.array(rel)


def probe():
    return make_pipeline(StandardScaler(), LogisticRegression(C=0.01, max_iter=2000))


def auc(y, p):
    return float(roc_auc_score(y, p)) if len(set(y)) == 2 else None


def within_auc(y, p, g):
    """Mean of per-prompt AUCs (controls for any between-prompt label-rate differences)."""
    v = [auc(y[g == pr], p[g == pr]) for pr in np.unique(g)]
    v = [x for x in v if x is not None]
    return float(np.mean(v)) if v else None


def text_baseline(d, key, meta, y, g, sid, rel, current_only=False):
    """Bag-of-words (TF-IDF 1-2 grams) on the CoT text written so far, same leave-one-prompt-out split."""
    bundle = json.loads((d / f"probe_bundle_{key}.json").read_text())["samples"]
    docs = []
    for n, m in enumerate(meta):
        b = bundle[n]
        assert b["prompt"] == m["prompt"] and b["sample_idx"] == m["sample_idx"]
        for j in range(m["n_sent"]):
            docs.append(b["text"][b["spans"][j][0] if current_only else b["cot_start"]: b["spans"][j][1]])
    docs = np.array(docs, dtype=object)
    p = np.zeros(len(y))
    for pr in np.unique(g):
        te = g == pr
        clf = make_pipeline(TfidfVectorizer(ngram_range=(1, 2), min_df=3, sublinear_tf=True), LogisticRegression(C=1.0, max_iter=2000))
        clf.fit(docs[~te], y[~te])
        p[te] = clf.predict_proba(docs[te])[:, 1]
    by_bin = [auc(y[(rel > BINS[b]) & (rel <= BINS[b + 1])], p[(rel > BINS[b]) & (rel <= BINS[b + 1])]) for b in range(10)]
    return {"auc_by_decile": by_bin, "auc_all": auc(y, p), "within_by_decile": [within_auc(y[(rel > BINS[b]) & (rel <= BINS[b + 1])], p[(rel > BINS[b]) & (rel <= BINS[b + 1])], g[(rel > BINS[b]) & (rel <= BINS[b + 1])]) for b in range(10)]}


def analyse(key):
    d = PATHS[key]
    path = d / f"acts_{key}.npz"
    if not path.exists():
        return None
    feats, off, layers, meta = load(path)
    out = {"layers": layers.tolist(), "n_samples": len(meta), "by_layer": {}}
    best = None
    for li, layer in enumerate(layers):
        X, y, g, sid, rel = rows(feats, off, meta, li)
        p = np.zeros(len(y))
        ans_p = np.zeros(len(meta))
        for pr in np.unique(g):
            te = g == pr
            clf = probe().fit(X[~te], y[~te])
            p[te] = clf.predict_proba(X[te])[:, 1]
            for n, m in enumerate(meta):
                if m["prompt"] == pr:
                    ans_p[n] = clf.predict_proba(feats[off[n + 1] - 1, li].astype(np.float32)[None])[0, 1]
        by_bin = []
        for b in range(10):
            sel = (rel > BINS[b]) & (rel <= BINS[b + 1])
            by_bin.append(auc(y[sel], p[sel]))
        ya = np.array([m["label"] == "EVALUATION" for m in meta])
        # first sentence of the first 25% / 50% of the CoT, per sample
        within = [within_auc(y[(rel > BINS[b]) & (rel <= BINS[b + 1])], p[(rel > BINS[b]) & (rel <= BINS[b + 1])], g[(rel > BINS[b]) & (rel <= BINS[b + 1])]) for b in range(10)]
        res = {"auc_by_decile": by_bin, "within_by_decile": within, "auc_answer": auc(ya, ans_p), "auc_all": auc(y, p),
               "auc_first_sentence": auc(y[[np.where(sid == n)[0][0] for n in range(len(meta))]], p[[np.where(sid == n)[0][0] for n in range(len(meta))]])}
        out["by_layer"][int(layer)] = res
        print(f"{key} layer {layer:2d}: AUC all {res['auc_all']:.2f}  1st sentence {res['auc_first_sentence']:.2f}  answer {res['auc_answer']:.2f}  deciles " +
              " ".join(f"{x:.2f}" for x in by_bin), flush=True)
        score = np.mean(by_bin[:5])  # pick the layer that decodes best early (pre-registered here: mean AUC over the first half)
        if best is None or score > best[0]:
            best = (score, li, p, sid)
    _, li, p, sid = best
    X, y, g, sid_, rel = rows(feats, off, meta, li)
    out["text_baseline"] = text_baseline(d, key, meta, y, g, sid_, rel)
    out["text_current"] = text_baseline(d, key, meta, y, g, sid_, rel, current_only=True)
    print(f"{key} text (current sentence only): AUC all {out['text_current']['auc_all']:.2f} deciles " + " ".join(f"{x:.2f}" for x in out["text_current"]["auc_by_decile"]), flush=True)
    print(f"{key} text baseline: AUC all {out['text_baseline']['auc_all']:.2f} deciles " + " ".join(f"{x:.2f}" for x in out["text_baseline"]["auc_by_decile"]), flush=True)
    print(f"{key} best-layer probe within-prompt deciles " + " ".join(f"{x:.2f}" for x in out["by_layer"][int(layers[li])]["within_by_decile"]), flush=True)
    out["best_layer"] = int(layers[li])
    # base runs: probe curve vs resampling curve
    rep = {r["run"]: r for r in json.loads((d / "report_data.json").read_text())["runs"]}
    sup = {r["run"]: r for r in json.loads((d / "suppression_bundle.json").read_text())["runs"]}
    base = []
    for n, m in enumerate(meta):
        if not m.get("base_run"):
            continue
        run = m["base_run"]
        pp = p[sid == n].tolist()
        pres = rep[run]["p_filtered"]
        L = sup[run]["lock"]
        fin = m["label"] == "EVALUATION"
        side = [(x > 0.5) == fin for x in pp]
        probe_lock = next((j for j in range(len(side)) if all(side[j:])), len(side))
        k = min(len(pp), len(pres) - 1)
        base.append({"run": run, "label": m["label"], "probe": pp, "resampled": pres, "lock": L, "probe_lock": probe_lock,
                     "rho": float(spearmanr(pp[:k], pres[1:k + 1]).correlation) if k > 3 else None})
    out["base_runs"] = base
    # fresh CoTs: train on all 200, test on new samples
    fp = d / f"fresh_{key}_acts.npz"
    if fp.exists():
        ff, fo, fl, fm = load(fp)
        X, y, g, sid_, rel = rows(feats, off, meta, li)
        clf = probe().fit(X, y)
        Xf, yf, gf, sf, rf = rows(ff, fo, fm, li)
        pf = clf.predict_proba(Xf)[:, 1]
        out["fresh"] = {"n": len(fm), "p_eval": float(np.mean([m["label"] == "EVALUATION" for m in fm])),
                        "auc_by_decile": [auc(yf[(rf > BINS[b]) & (rf <= BINS[b + 1])], pf[(rf > BINS[b]) & (rf <= BINS[b + 1])]) for b in range(10)],
                        "auc_all": auc(yf, pf)}
        fj = d / f"fresh_{key}.json"
        if fj.exists():
            bundle = json.loads((d / f"probe_bundle_{key}.json").read_text())["samples"]
            fresh = json.loads(fj.read_text())["labelled"]
            docs = lambda bs, ms: np.array([b["text"][b["spans"][0][0]: b["spans"][j][1]] for b, m in zip(bs, ms) for j in range(m["n_sent"])], dtype=object)
            assert all(b["prompt"] == m["prompt"] for b, m in zip(fresh, fm))
            clf = make_pipeline(TfidfVectorizer(ngram_range=(1, 2), min_df=3, sublinear_tf=True), LogisticRegression(C=1.0, max_iter=2000))
            clf.fit(docs(bundle, meta), y)
            pt = clf.predict_proba(docs(fresh, fm))[:, 1]
            out["fresh"]["text_by_decile"] = [auc(yf[(rf > BINS[b]) & (rf <= BINS[b + 1])], pt[(rf > BINS[b]) & (rf <= BINS[b + 1])]) for b in range(10)]
            out["fresh"]["text_all"] = auc(yf, pt)
        print(f"{key} fresh ({len(fm)} CoTs): AUC all {out['fresh']['auc_all']}, deciles {out['fresh']['auc_by_decile']}")
    return out


def main():
    out = {k: a for k in PATHS if (a := analyse(k))}
    (RES / "probe_analysis.json").write_text(json.dumps(out, indent=1))
    for k, a in out.items():
        b = a["base_runs"]
        print(f"== {k}: best layer {a['best_layer']}; base runs: probe lock (median) {np.median([x['probe_lock'] for x in b])} vs resampling lock {np.median([x['lock'] for x in b])}, "
              f"rho probe vs resampled median {np.nanmedian([x['rho'] for x in b if x['rho'] is not None]):+.2f}")


if __name__ == "__main__":
    main()
