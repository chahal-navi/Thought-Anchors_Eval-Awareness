"""Overnight white-box experiments on the GPU machine (bundles from prepare_overnight.py).

  white    exp 2  block the user prompt / the whole CoT (from every later token, or only from the answer)
           exp 3  block groups of sentences (pre-lock, post-lock, last 2, opening, checklist, top anchors,
                  size-matched random sets, growing prefixes / suffixes)
           exp 6  receiver heads: vertical attention scores per head -> kurtosis -> top-20 heads; then
                  per-sentence (and group) suppression in only those heads, vs 20 random heads
  extract  exp 1  residual-stream activations at the end of every sentence (+ prompt end, answer position)
                  of the 200 sampled CoTs, for the verdict probe
  generate exp 1  fresh CoTs (held-out test set for the probe), label by the forced "<label>" answer,
                  then extract activations as above

Suppression wraps transformers' "sdpa" attention function: key column c is hidden from every query row
>= thr[c] (thr = the blocked sentence's own end, or the CoT end for "answer only" blocks), optionally only
in some heads of some layers. The layer's own causal / sliding-window mask is kept.

Usage:
    python overnight.py white   --model M --bundle ov_bundle.json   --out ov_white.json   [--max-gpu-gib G]
    python overnight.py extract --model M --bundle probe_bundle.json --out probe_acts.npz
    python overnight.py generate --model M --bundle probe_bundle.json --out fresh --n 10
"""

import argparse
import json
import math
import os
import random
import re
import sys
import time

import numpy as np
import torch
import torch.nn.functional as F
from transformers import AutoModelForCausalLM, AutoTokenizer
from transformers.modeling_utils import ALL_ATTENTION_FUNCTIONS

from splitter import cot_prefixes, split_solution_into_chunks

ST = {"thr": None, "heads": None, "collect": None, "reader": None}
LAYER_OF: dict[int, int] = {}
_orig_sdpa = ALL_ATTENTION_FUNCTIONS["sdpa"]
BIG = 1 << 30
LABELS = ("EVALUATION", "DEPLOYMENT")
DEV = os.getenv("DEV", "cuda")


def layer_mask(attention_mask, query, key):
    q_len, k_len = query.shape[2], key.shape[2]
    if attention_mask is None:
        m = torch.ones(q_len, k_len, dtype=torch.bool, device=query.device).tril(k_len - q_len)[None, None]
    elif attention_mask.dtype == torch.bool:
        m = attention_mask
    else:
        m = attention_mask > torch.finfo(attention_mask.dtype).min / 2
    return m[..., :k_len].expand(query.shape[0], 1, q_len, k_len)


def collect_vertical(module, query, key, attention_mask, kw):
    """Per head: mean attention that sentence s receives from query rows >= end_s + 16 (paper's vertical score)."""
    c = ST["collect"]
    q, k = query[:1], key[:1]
    H = q.shape[1]
    k = k.repeat_interleave(H // k.shape[1], dim=1)
    scale = kw.get("scaling") or 1 / math.sqrt(q.shape[-1])
    m = layer_mask(attention_mask[:1] if attention_mask is not None else None, q, k)[0, 0]
    out = []
    for h0 in range(0, H, 8):
        s = (q[0, h0:h0 + 8].float() @ k[0, h0:h0 + 8].float().transpose(-1, -2)) * scale
        if kw.get("softcap"):
            s = torch.tanh(s / kw["softcap"]) * kw["softcap"]
        A = s.masked_fill(~m, float("-inf")).softmax(-1)
        Cm = A @ c["P"]  # (h, q, N): mean attention to each sentence's tokens
        out.append((Cm * c["rows"].T[None]).sum(1) / c["rows"].sum(1).clamp(min=1)[None])
    c["out"][LAYER_OF[id(module)]] = torch.cat(out).cpu()


def collect_reader(module, query, key, attention_mask, kw):
    """Per head: mean over the answer rows (seq 0) of the attention mass on CoT keys and on the last 2 sentences."""
    c = ST["reader"]
    q, k = query[:1, :, c["r0"]:], key[:1]
    H = q.shape[1]
    k = k.repeat_interleave(H // k.shape[1], dim=1)
    scale = kw.get("scaling") or 1 / math.sqrt(q.shape[-1])
    m = layer_mask(attention_mask[:1] if attention_mask is not None else None, query[:1], key[:1])[0, 0, c["r0"]:]
    s = (q[0].float() @ k[0].float().transpose(-1, -2)) * scale
    if kw.get("softcap"):
        s = torch.tanh(s / kw["softcap"]) * kw["softcap"]
    A = s.masked_fill(~m, float("-inf")).softmax(-1)  # (H, rows, k)
    c["out"][LAYER_OF[id(module)]] = torch.stack([A[..., a:b].sum(-1).mean(-1) for a, b in c["ranges"]], -1).cpu()


def patched_sdpa(module, query, key, value, attention_mask, **kw):
    if ST["collect"] is not None:
        collect_vertical(module, query, key, attention_mask, kw)
    if ST["reader"] is not None:
        collect_reader(module, query, key, attention_mask, kw)
    thr = ST["thr"]
    heads = ST["heads"]
    if thr is None or (heads is not None and LAYER_OF.get(id(module)) not in heads):
        return _orig_sdpa(module, query, key, value, attention_mask, **kw)
    q_len, k_len = query.shape[2], key.shape[2]
    rows = torch.arange(q_len, device=query.device)[:, None] + (k_len - q_len)
    block = rows >= thr[:k_len].to(query.device)[None, :]
    base = layer_mask(attention_mask, query, key)
    if heads is None:
        m = base & ~block[None, None]
    else:
        hb = torch.zeros(query.shape[1], dtype=torch.bool, device=query.device)
        hb[heads[LAYER_OF[id(module)]]] = True
        m = base & ~(block[None, None] & hb[None, :, None, None])
    kw.pop("is_causal", None)
    return _orig_sdpa(module, query, key, value, m, is_causal=False, **kw)


ALL_ATTENTION_FUNCTIONS["sdpa"] = patched_sdpa


def load(model_id, max_gpu_gib=None):
    tok = AutoTokenizer.from_pretrained(model_id)
    kw = dict(dtype="auto", attn_implementation="sdpa", device_map=DEV)
    if max_gpu_gib:
        kw.update(device_map="auto", max_memory={0: f"{max_gpu_gib}GiB", "cpu": "400GiB"})
    try:
        model = AutoModelForCausalLM.from_pretrained(model_id, **kw)
    except (ValueError, KeyError):
        from transformers import AutoModelForImageTextToText
        model = AutoModelForImageTextToText.from_pretrained(model_id, **kw)
    model.eval()
    for name, mod in model.named_modules():
        mm = re.search(r"layers\.(\d+)\.self_attn$", name)
        if mm:
            LAYER_OF[id(mod)] = int(mm.group(1))
    cfg = model.config.get_text_config()
    print(f"loaded {model_id}: {cfg.num_hidden_layers} layers x {cfg.num_attention_heads} heads, {len(LAYER_OF)} attention modules", flush=True)
    return tok, model


def tok_range(offs, cs, ce):
    t = [k for k, (a, b) in enumerate(offs) if cs <= a < ce and b > a]
    return (t[0], t[-1] + 1)


def encode_run(tok, r, device):
    """Two sequences ...<label>EVALUATION / ...<label>DEPLOYMENT; token spans of sentences, user prompt, CoT."""
    ctx = r["text"].removesuffix("<label>")
    encs = [tok(ctx + "<label>" + w, return_offsets_mapping=True, add_special_tokens=False) for w in LABELS]
    seqs = [e["input_ids"] for e in encs]
    L = next(k for k in range(min(map(len, seqs))) if seqs[0][k] != seqs[1][k])
    T = max(map(len, seqs))
    pad = tok.pad_token_id if tok.pad_token_id is not None else 0
    ids = torch.tensor([s + [pad] * (T - len(s)) for s in seqs], device=device)
    offs = encs[0]["offset_mapping"]
    spans = [tok_range(offs, cs, ce) for cs, ce in r["spans"]]
    users = [tok_range(offs, cs, ce) for cs, ce in r["user_spans"]]
    return {"ids": ids, "seqs": seqs, "L": L, "T": T, "spans": spans, "users": users,
            "cot": (spans[0][0], spans[-1][1]), "offs": offs}


@torch.no_grad()
def run_forward(model, enc, lo):
    return model(input_ids=enc["ids"], use_cache=False, logits_to_keep=enc["T"] - lo).logits


def label_logodds(logits, enc, lo):
    lp = []
    for b, sq in enumerate(enc["seqs"]):
        pos = torch.arange(enc["L"] - 1, len(sq) - 1, device=logits.device)
        ls = F.log_softmax(logits[b, pos - lo].float(), dim=-1)
        lp.append(ls.gather(1, torch.tensor(sq[enc["L"]:], device=logits.device)[:, None]).sum().item())
    return lp[0] - lp[1]


def kl_rows(base_lp, logits, block=128):
    out = []
    for k in range(0, logits.shape[0], block):
        b = base_lp[k:k + block]
        q = F.log_softmax(logits[k:k + block].float(), dim=-1)
        out.append((b.exp() * (b - q)).sum(-1))
    return torch.cat(out)


def thr_for(enc, sentences=(), ranges=(), device="cpu"):
    """sentences: blocked from every later token; ranges: [(s, e, from_row)] blocked from rows >= from_row."""
    thr = torch.full((enc["T"],), BIG, dtype=torch.long)
    for j in sentences:
        s, e = enc["spans"][j]
        thr[s:e] = torch.minimum(thr[s:e], torch.tensor(e))
    for s, e, f in ranges:
        thr[s:e] = torch.minimum(thr[s:e], torch.tensor(f))
    return thr.to(device)


def conditions_exp2(enc):
    cs, ce = enc["cot"]
    us, ue = enc["users"][0][0], enc["users"][-1][1]
    c = {"cot_all": [(cs, ce, ce)],
         "user": [(us, ue, ue)],
         "user_answer_only": [(us, ue, ce)],
         "user_and_cot_answer_only": [(us, ue, ce), (cs, ce, ce)]}
    n = ue - us
    for q in range(4):
        a, b = us + q * n // 4, us + (q + 1) * n // 4
        c[f"user_q{q + 1}"] = [(a, b, b)]
    return c


def heads_dict(pairs, device):
    d = {}
    for l, h in pairs:
        d.setdefault(int(l), []).append(int(h))
    return {l: torch.tensor(v, device=device) for l, v in d.items()}


def cmd_white(args):
    bundle = json.load(open(args.bundle))
    tok, model = load(args.model, args.max_gpu_gib)
    cfg = model.config.get_text_config()
    nL, nH = cfg.num_hidden_layers, cfg.num_attention_heads
    dev = DEV
    try:
        res = json.load(open(args.out))
    except FileNotFoundError:
        res = {"model": args.model, "runs": {}, "vertical": {}}
    runs = [r for r in bundle["runs"] if not args.runs or r["run"] in args.runs]
    encs = {r["run"]: encode_run(tok, r, dev) for r in runs}

    # ---- exp 2 + exp 3: block ranges / sentence groups in all heads ----
    for r in runs:
        if r["run"] in res["runs"] and "exp3" in res["runs"][r["run"]]:
            continue
        t0, enc = time.time(), encs[r["run"]]
        lo = enc["L"] - 1
        ST["thr"] = None
        base = label_logodds(run_forward(model, enc, lo), enc, lo)
        out = {"base_logodds": base, "N": len(enc["spans"]), "exp2": {}, "exp3": {}}
        for name, rngs in conditions_exp2(enc).items():
            ST["thr"] = thr_for(enc, ranges=rngs, device=dev)
            out["exp2"][name] = label_logodds(run_forward(model, enc, lo), enc, lo) - base
        for name, sents in r["groups"].items():
            ST["thr"] = thr_for(enc, sentences=sents, device=dev)
            out["exp3"][name] = label_logodds(run_forward(model, enc, lo), enc, lo) - base
        ST["thr"] = None
        res["runs"][r["run"]] = out
        json.dump(res, open(args.out, "w"))
        e2 = " ".join(f"{k}={v:+.1f}" for k, v in out["exp2"].items())
        print(f"[exp2/3] {r['run']:12s} base {base:+.1f}  {e2}  pre_lock={out['exp3'].get('pre_lock', float('nan')):+.1f} "
              f"post_lock={out['exp3'].get('post_lock', float('nan')):+.1f} [{time.time() - t0:.0f}s]", flush=True)

    # ---- exp 6a: vertical attention scores per head ----
    for r in runs:
        if r["run"] in res["vertical"]:
            continue
        enc = encs[r["run"]]
        T0 = len(enc["seqs"][0])
        N = len(enc["spans"])
        P = torch.zeros(T0, N, device=dev)
        rows = torch.zeros(N, T0, dtype=torch.bool, device=dev)
        for j, (s, e) in enumerate(enc["spans"]):
            P[s:e, j] = 1 / (e - s)
            rows[j, min(T0, e + 16):T0] = True
        ST["collect"] = {"P": P, "rows": rows, "out": {}}
        with torch.no_grad():
            model(input_ids=enc["ids"][:1, :T0], use_cache=False, logits_to_keep=1)
        v = torch.stack([ST["collect"]["out"][l] for l in range(nL)])  # (layers, heads, N)
        ST["collect"] = None
        res["vertical"][r["run"]] = v.numpy().round(6).tolist()
    json.dump(res, open(args.out, "w"))
    from scipy.stats import kurtosis
    K = []
    for run, v in res["vertical"].items():
        v = np.array(v)[:, :, : -2]  # drop the last 2 sentences (few rows after them)
        K.append(kurtosis(v, axis=2, fisher=True, nan_policy="omit"))
    Kmean = np.nanmean(np.array(K), axis=0)
    order = np.argsort(-np.nan_to_num(Kmean, nan=-1e9), axis=None)
    top = [(int(i // nH), int(i % nH)) for i in order[:20]]
    rng = random.Random(0)
    rand_sets = [[(l, h) for l, h in rng.sample([(l, h) for l in range(nL) for h in range(nH)], 20)] for _ in range(2)]
    half = [np.nanmean(np.array(K[0::2]), axis=0).ravel(), np.nanmean(np.array(K[1::2]), axis=0).ravel()]
    ok = ~np.isnan(half[0]) & ~np.isnan(half[1])
    res["receiver"] = {"top20": top, "kurtosis_mean": np.nan_to_num(Kmean).round(4).tolist(), "random20": rand_sets,
                       "split_half_r": float(np.corrcoef(half[0][ok], half[1][ok])[0, 1])}
    print(f"[exp6] receiver heads {top[:10]} ... split-half r = {res['receiver']['split_half_r']:.2f}", flush=True)
    json.dump(res, open(args.out, "w"))

    # ---- exp 6b: suppress each sentence (and groups) in receiver heads only / random heads ----
    head_sets = {"receiver": heads_dict(top, dev), "random0": heads_dict(rand_sets[0], dev), "random1": heads_dict(rand_sets[1], dev)}
    for r in runs:
        out = res["runs"][r["run"]]
        if "exp6" in out:
            continue
        t0, enc = time.time(), encs[r["run"]]
        lo = enc["spans"][0][0] - 1
        ST["thr"], ST["heads"] = None, None
        logits = run_forward(model, enc, lo)
        base_lp = F.log_softmax(logits[0, : enc["L"] - lo].float(), dim=-1)
        base = label_logodds(logits, enc, lo)
        del logits
        e6 = {}
        for hs, hd in head_sets.items():
            ST["heads"] = hd
            per = {"dlo": [], "kl_later": []}
            for j, (s, e) in enumerate(enc["spans"]):
                ST["thr"] = thr_for(enc, sentences=[j], device=dev)
                lg = run_forward(model, enc, lo)
                per["dlo"].append(label_logodds(lg, enc, lo) - base)
                klt = kl_rows(base_lp, lg[0, : enc["L"] - lo])
                per["kl_later"].append(klt[e - 1 - lo: enc["cot"][1] - 1 - lo].mean().item() if e < enc["cot"][1] else None)
                del lg, klt
            for g in ["kl_top3", "imp_top3", "pre_lock", "post_lock", "last2", "checklist", "opening"]:
                if g in r["groups"]:
                    ST["thr"] = thr_for(enc, sentences=r["groups"][g], device=dev)
                    per[f"group_{g}"] = label_logodds(run_forward(model, enc, lo), enc, lo) - base
            ST["thr"] = thr_for(enc, ranges=[(enc["cot"][0], enc["cot"][1], enc["cot"][1])], device=dev)
            per["group_cot_all"] = label_logodds(run_forward(model, enc, lo), enc, lo) - base
            e6[hs] = per
        ST["thr"], ST["heads"] = None, None
        out["exp6"] = e6
        json.dump(res, open(args.out, "w"))
        mx = {k: max(map(abs, v["dlo"])) for k, v in e6.items()}
        print(f"[exp6] {r['run']:12s} max|dlo| receiver {mx['receiver']:.2f} random {mx['random0']:.2f}/{mx['random1']:.2f} "
              f"cot_all receiver {e6['receiver']['group_cot_all']:+.1f} [{time.time() - t0:.0f}s]", flush=True)
    print("WHITE_DONE", flush=True)


def pick_layers(n):
    return sorted({max(1, round(n * f)) for f in (0.125, 0.25, 0.375, 0.5, 0.625, 0.75, 0.875, 1.0)})


@torch.no_grad()
def extract(model, tok, samples, out_path):
    nL = model.config.get_text_config().num_hidden_layers
    layers = pick_layers(nL)
    if not samples:
        print("[extract] no samples", flush=True)
        return
    feats, meta = [], []
    for n, s in enumerate(samples):
        enc = tok(s["text"], return_offsets_mapping=True, add_special_tokens=False)
        offs, ids = enc["offset_mapping"], enc["input_ids"]
        spans = [tok_range(offs, cs, ce) for cs, ce in s["spans"]]
        pos = [spans[0][0] - 1] + [e - 1 for _, e in spans] + [len(ids) - 1]  # prompt end, each sentence end, answer
        hs = model(input_ids=torch.tensor([ids], device=DEV), use_cache=False, output_hidden_states=True, logits_to_keep=1).hidden_states
        idx = torch.tensor(pos, device=hs[0].device)
        f = torch.stack([hs[l][0].index_select(0, idx.to(hs[l].device)).float().cpu() for l in layers], 1)  # (pos, layers, d)
        feats.append(f.half().numpy())
        meta.append({k: s[k] for k in ("prompt", "sample_idx", "label", "base_run") if k in s} | {"n_sent": len(spans)})
        del hs
        if n % 20 == 0:
            print(f"[extract] {n}/{len(samples)} T={len(ids)}", flush=True)
    off = np.cumsum([0] + [len(f) for f in feats])
    np.savez(out_path, feats=np.concatenate(feats), offsets=off, layers=np.array(layers), meta=json.dumps(meta))
    print(f"[extract] saved {out_path} {np.concatenate(feats).shape}", flush=True)


def cmd_extract(args):
    bundle = json.load(open(args.bundle))
    tok, model = load(args.model, args.max_gpu_gib)
    extract(model, tok, bundle["samples"], args.out)
    print("EXTRACT_DONE", flush=True)


@torch.no_grad()
def cmd_generate(args):
    bundle = json.load(open(args.bundle))
    tok, model = load(args.model, args.max_gpu_gib)
    close = bundle["think_close"]
    stop_id = tok.convert_tokens_to_ids(close.strip())
    gemma = "channel" in close
    print(f"stop token {close.strip()!r} -> {stop_id}", flush=True)
    tok.padding_side = "left"
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    gens = []
    try:
        gens = json.load(open(args.out + ".json"))["samples"]
    except FileNotFoundError:
        pass
    done = {g["prompt"] for g in gens}
    prompts = [p for p in bundle["heads"] if p not in done]
    per_batch = max(1, args.batch // args.n)
    for b0 in range(0, len(prompts), per_batch):
        if args.deadline and time.time() > args.deadline:
            print("[generate] deadline reached, stopping generation", flush=True)
            break
        ps = prompts[b0:b0 + per_batch]
        heads = [bundle["heads"][p] for p in ps for _ in range(args.n)]
        t0 = time.time()
        x = tok(heads, return_tensors="pt", padding=True, add_special_tokens=False).to(DEV)
        y = model.generate(**x, do_sample=True, temperature=0.6, top_p=0.95, max_new_tokens=args.max_new,
                           eos_token_id=[stop_id] + ([tok.eos_token_id] if tok.eos_token_id is not None else []), pad_token_id=tok.pad_token_id)
        for k, p in enumerate([p for p in ps for _ in range(args.n)]):
            new = y[k, x["input_ids"].shape[1]:].tolist()
            finished = stop_id in new
            text = tok.decode(new[: new.index(stop_id)] if finished else new, skip_special_tokens=False)
            text = text.replace(tok.pad_token or "\0", "")
            gens.append({"prompt": p, "reasoning": text.strip(), "finished": finished})
        json.dump({"samples": gens}, open(args.out + ".json", "w"))
        print(f"[generate] {ps} -> {sum(g['finished'] for g in gens)}/{len(gens)} finished [{time.time() - t0:.0f}s]", flush=True)
    # label by the forced answer (score both whole-word labels after close + "<label>")
    samples = []
    for g in gens:
        if not g["finished"] or not g["reasoning"]:
            continue
        chunks = split_solution_into_chunks(g["reasoning"], gemma=gemma)
        try:
            pref = cot_prefixes(g["reasoning"], chunks)
        except ValueError:
            continue
        head = bundle["heads"][g["prompt"]]
        r = {"text": head + g["reasoning"] + close + "<label>", "spans": [(len(head) + len(pref[k]), len(head) + len(pref[k + 1])) for k in range(len(chunks))],
             "user_spans": []}
        enc = encode_run(tok, r, DEV)
        lo = enc["L"] - 1
        lg = label_logodds(run_forward(model, enc, lo), enc, lo)
        g["forced_logodds"] = lg
        samples.append({"prompt": g["prompt"], "sample_idx": len(samples), "label": "EVALUATION" if lg > 0 else "DEPLOYMENT", "base_run": None,
                        "text": r["text"], "spans": r["spans"], "forced_logodds": lg})
    json.dump({"samples": gens, "labelled": samples}, open(args.out + ".json", "w"))
    print(f"[generate] {len(samples)} labelled fresh CoTs, P(EVAL) = {np.mean([s['label'] == 'EVALUATION' for s in samples]):.2f}", flush=True)
    extract(model, tok, samples, args.out + "_acts.npz")
    print("GENERATE_DONE", flush=True)


def cmd_followup(args):
    """Splices (A's head + B's tail), verdict-statement blocks, per-sentence answer-only blocks, layer sweeps."""
    bundle = json.load(open(args.bundle))
    tok, model = load(args.model, args.max_gpu_gib)
    cfg = model.config.get_text_config()
    nL, nH = cfg.num_hidden_layers, cfg.num_attention_heads
    try:
        res = json.load(open(args.out))
    except FileNotFoundError:
        res = {"model": args.model, "runs": {}}
    allh = torch.arange(nH, device=DEV)
    grid = sorted({int(round(x)) for x in np.linspace(0, nL, 9)})
    for r in bundle["runs"]:
        if r["run"] in res["runs"]:
            continue
        t0 = time.time()
        enc = encode_run(tok, r, DEV)
        lo = enc["L"] - 1
        fwd = lambda e=enc: label_logodds(run_forward(model, e, e["L"] - 1), e, e["L"] - 1)
        ST["thr"], ST["heads"] = None, None
        base = fwd()
        out = {"base_logodds": base, "splices": {}, "groups": {}, "answer_only": [], "layers_from": {}, "layers_upto": {}, "layers_window": {}}
        for name, sp in r["splices"].items():
            e2 = encode_run(tok, sp, DEV)
            out["splices"][name] = fwd(e2)
        for name, sents in r["groups"].items():
            ST["thr"] = thr_for(enc, sentences=sents, device=DEV)
            out["groups"][name] = fwd() - base
        ce = enc["cot"][1]
        for s, e in enc["spans"]:
            ST["thr"] = thr_for(enc, ranges=[(s, e, ce)], device=DEV)
            out["answer_only"].append(fwd() - base)
        ST["thr"] = thr_for(enc, ranges=[(enc["cot"][0], ce, ce)], device=DEV)
        for a, b in zip(grid[:-1], grid[1:]):
            ST["heads"] = {k: allh for k in range(a, b)}
            out["layers_window"][f"{a}-{b}"] = fwd() - base
        for l in grid[1:-1]:
            ST["heads"] = {k: allh for k in range(l, nL)}
            out["layers_from"][str(l)] = fwd() - base
            ST["heads"] = {k: allh for k in range(0, l)}
            out["layers_upto"][str(l)] = fwd() - base
        ST["thr"], ST["heads"] = None, None
        res["runs"][r["run"]] = out
        json.dump(res, open(args.out, "w"))
        sp = " ".join(f"{k}={v:+.1f}" for k, v in out["splices"].items())
        lw = " ".join(f"{k}:{v:+.1f}" for k, v in out["layers_window"].items())
        print(f"[followup] {r['run']:12s} base {base:+.1f} splices {sp} | stmt {out['groups'].get('verdict_stmt', float('nan')):+.1f} | "
              f"answer-only max {max(map(abs, out['answer_only'])):.1f} | layers {lw} [{time.time() - t0:.0f}s]", flush=True)
    print("FOLLOWUP_DONE", flush=True)


def cmd_readers(args):
    """Which heads carry the CoT into the answer? Score heads by answer-row attention mass on the CoT (averaged over
    runs), then block the CoT from the answer (rows >= CoT end) in only the top-k reader heads vs k random heads
    (necessity), and in every head except the top-k (sufficiency)."""
    bundle = json.load(open(args.bundle))
    tok, model = load(args.model, args.max_gpu_gib)
    cfg = model.config.get_text_config()
    nL, nH = cfg.num_hidden_layers, cfg.num_attention_heads
    try:
        res = json.load(open(args.out))
    except FileNotFoundError:
        res = {"model": args.model, "scores": {}, "runs": {}}
    encs = {}
    for r in bundle["runs"]:
        enc = encode_run(tok, r, DEV)
        encs[r["run"]] = enc
        if r["run"] in res["scores"]:
            continue
        cs, ce = enc["cot"]
        n = len(enc["spans"])
        ST["reader"] = {"r0": enc["L"] - 1, "ranges": [(cs, ce), (enc["spans"][max(0, n - 2)][0], ce), (0, cs)], "out": {}}
        run_forward(model, enc, enc["L"] - 1)
        res["scores"][r["run"]] = torch.stack([ST["reader"]["out"][l] for l in range(nL)]).tolist()  # (L, H, 3)
        ST["reader"] = None
    json.dump(res, open(args.out, "w"))
    S = np.array([res["scores"][k] for k in encs])  # (runs, L, H, 3)
    score = S[..., 0].mean(0)  # CoT mass
    order = np.dstack(np.unravel_index(np.argsort(-score, axis=None), score.shape))[0]
    res["top_heads"] = order[:200].tolist()
    print("[readers] top reader heads (layer, head, CoT mass):", [(int(l), int(h), round(float(score[l, h]), 3)) for l, h in order[:15]], flush=True)
    rng = random.Random(0)
    allpairs = [(l, h) for l in range(nL) for h in range(nH)]
    ks = [k for k in (5, 20, 50, 200, 800) if k < nL * nH // 2]
    rand = {k: [rng.sample(allpairs, k) for _ in range(2)] for k in ks}
    res["random_heads"] = {str(k): v for k, v in rand.items()}
    if args.window:  # read-out window found by the follow-up layer sweep: rank heads only inside it
        a, b = args.window
        ws = np.full_like(score, -1.0)
        ws[a:b] = score[a:b]
        nw = (b - a) * nH
        worder = np.dstack(np.unravel_index(np.argsort(-ws, axis=None), ws.shape))[0][:nw]
        wpairs = [(l, h) for l in range(a, b) for h in range(nH)]
        wks = [k for k in (2, 4, 8, 16, 32, 64, 128) if k <= nw // 2]
        wrand = {k: [rng.sample(wpairs, k) for _ in range(2)] for k in wks}
        res["window"] = [a, b]
        res["win_top_heads"] = worder[:64].tolist()
    for r in bundle["runs"]:
        if r["run"] in res["runs"]:
            continue
        t0 = time.time()
        enc = encs[r["run"]]
        fwd = lambda: label_logodds(run_forward(model, enc, enc["L"] - 1), enc, enc["L"] - 1)
        ST["thr"], ST["heads"] = None, None
        base = fwd()
        cs, ce = enc["cot"]
        ST["thr"] = thr_for(enc, ranges=[(cs, ce, ce)], device=DEV)
        ST["heads"] = None
        out = {"base_logodds": base, "cot_all_answer_only": fwd() - base, "top": {}, "random": {}, "keep_top": {}}
        for k in ks:
            top = [tuple(x) for x in order[:k]]
            ST["heads"] = heads_dict(top, DEV)
            out["top"][str(k)] = fwd() - base
            out["random"][str(k)] = []
            for rs in rand[k]:
                ST["heads"] = heads_dict(rs, DEV)
                out["random"][str(k)].append(fwd() - base)
            keep = set(top)
            ST["heads"] = heads_dict([p for p in allpairs if p not in keep], DEV)
            out["keep_top"][str(k)] = fwd() - base
        if args.window:
            a, b = args.window
            allh = torch.arange(nH, device=DEV)
            out["single_layer"] = {}
            for l in range(a, b):
                ST["heads"] = {l: allh}
                out["single_layer"][str(l)] = fwd() - base
            out["win_top"], out["win_random"] = {}, {}
            for k in wks:
                ST["heads"] = heads_dict([tuple(x) for x in worder[:k]], DEV)
                out["win_top"][str(k)] = fwd() - base
                out["win_random"][str(k)] = []
                for rs in wrand[k]:
                    ST["heads"] = heads_dict(rs, DEV)
                    out["win_random"][str(k)].append(fwd() - base)
        ST["thr"], ST["heads"] = None, None
        res["runs"][r["run"]] = out
        json.dump(res, open(args.out, "w"))
        print(f"[readers] {r['run']:12s} base {base:+.1f} all {out['cot_all_answer_only']:+.1f} | top " +
              " ".join(f"{k}:{v:+.1f}" for k, v in out["top"].items()) + " | rand " +
              " ".join(f"{k}:{np.mean(v):+.1f}" for k, v in out["random"].items()) + " | keep-only-top " +
              " ".join(f"{k}:{v:+.1f}" for k, v in out["keep_top"].items()) + f" [{time.time() - t0:.0f}s]", flush=True)
    print("READERS_DONE", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["white", "extract", "generate", "followup", "readers"])
    ap.add_argument("--model", required=True)
    ap.add_argument("--bundle", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--runs", nargs="*")
    ap.add_argument("--max-gpu-gib", type=float)
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--batch", type=int, default=10)
    ap.add_argument("--max-new", type=int, default=2000)
    ap.add_argument("--window", type=int, nargs=2, help="readers: layer window [a, b) for single-layer and within-window head ablations")
    ap.add_argument("--deadline", type=float, help="unix time after which no new generation batch starts")
    args = ap.parse_args()
    {"white": cmd_white, "extract": cmd_extract, "generate": cmd_generate, "followup": cmd_followup, "readers": cmd_readers}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
