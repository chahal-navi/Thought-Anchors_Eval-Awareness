"""Sentence x sentence attention-suppression KL matrix (Thought Anchors, Fig. 6), plus the effect on the verdict.

Runs on a GPU machine with the bundle from prepare_suppression.py. For each base CoT with N chunks:
  1. baseline forward pass over  prompt + CoT + think_close + "<label>"
  2. for each chunk j: block attention TO chunk j's tokens from every later query position, in every head of
     every layer, and run the forward pass again
  3. KL(baseline || suppressed) of the next-token distribution at every position, averaged over the token
     predictions inside chunk i  ->  matrix[i, j]  (only i > j is meaningful)
  4. "verdict row": KL at the final position (the token after "<label>"), and the change in
     P(EVALUATION) = p(EVAL first token) / (p(EVAL first token) + p(DEPLOY first token))

Suppression is done by wrapping transformers' "sdpa" attention function, so it works for any architecture that
goes through the attention interface (Qwen3, Gemma 4 with its sliding/global layers, QK-norm and RoPE untouched):
the layer's own mask (causal or sliding-window) is materialised and the suppressed key columns are set to False.

Usage (on the GPU machine):
    python suppression_kl.py --model Qwen/Qwen3-32B-FP8 --bundle suppression_bundle.json --out suppression_qwen.json
"""

import argparse
import json
import math
import time

import torch
import torch.nn.functional as F
from transformers import AutoModelForCausalLM, AutoTokenizer
from transformers.modeling_utils import ALL_ATTENTION_FUNCTIONS

SUPPRESS: dict = {"range": None}
_orig_sdpa = ALL_ATTENTION_FUNCTIONS["sdpa"]


def suppressing_sdpa(module, query, key, value, attention_mask, **kwargs):
    rng = SUPPRESS["range"]
    if rng is None:
        return _orig_sdpa(module, query, key, value, attention_mask, **kwargs)
    s, e = rng
    q_len, k_len = query.shape[2], key.shape[2]
    if attention_mask is None:  # transformers skipped the mask (pure causal): build it
        mask = torch.ones(q_len, k_len, dtype=torch.bool, device=query.device).tril(k_len - q_len)[None, None]
    elif attention_mask.dtype == torch.bool:
        mask = attention_mask.clone()
    else:  # additive float mask
        mask = attention_mask > torch.finfo(attention_mask.dtype).min / 2
    mask = mask.expand(query.shape[0], 1, q_len, k_len).clone()
    rows = torch.arange(q_len, device=query.device)[:, None] + (k_len - q_len)
    cols = torch.arange(k_len, device=query.device)[None, :]
    block = (cols >= s) & (cols < e) & (rows >= e)  # later positions may not look at chunk j
    mask[:, :, block] = False
    kwargs.pop("is_causal", None)
    return _orig_sdpa(module, query, key, value, mask, is_causal=False, **kwargs)


ALL_ATTENTION_FUNCTIONS["sdpa"] = suppressing_sdpa


def load(model_id, device="cuda", max_gpu_gib=None):
    """max_gpu_gib: cap GPU memory for weights; the rest is offloaded to CPU RAM (accelerate moves it in per forward)."""
    tok = AutoTokenizer.from_pretrained(model_id)
    kw = dict(dtype="auto", attn_implementation="sdpa", device_map=device)
    if max_gpu_gib:
        kw.update(device_map="auto", max_memory={0: f"{max_gpu_gib}GiB", "cpu": "400GiB"})
    try:
        model = AutoModelForCausalLM.from_pretrained(model_id, **kw)
    except (ValueError, KeyError) as err:  # Gemma 4 checkpoints are image-text-to-text
        print("AutoModelForCausalLM failed, trying AutoModelForImageTextToText:", str(err)[:200])
        from transformers import AutoModelForImageTextToText
        model = AutoModelForImageTextToText.from_pretrained(model_id, **kw)
    model.eval()
    return tok, model


LABELS = ("EVALUATION", "DEPLOYMENT")


def kl_rows(base_lp, logits, block=128):
    """KL(base || suppressed) per position, in blocks of positions to keep float32 vocab temporaries small."""
    out = []
    for k in range(0, logits.shape[0], block):
        b = base_lp[k:k + block]
        q = F.log_softmax(logits[k:k + block].float(), dim=-1)
        out.append((b.exp() * (b - q)).sum(-1))
    return torch.cat(out)


@torch.no_grad()
def forward(model, ids, lo):
    """Logits at positions lo..T-1 for a batch of sequences (bf16, on GPU)."""
    return model(input_ids=ids, use_cache=False, logits_to_keep=ids.shape[1] - lo).logits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--bundle", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--runs", nargs="*")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--max-gpu-gib", type=float, help="offload weights beyond this to CPU RAM")
    args = ap.parse_args()

    bundle = json.load(open(args.bundle))
    tok, model = load(args.model, args.device, args.max_gpu_gib)
    if hasattr(model, "hf_device_map"):
        where = list(model.hf_device_map.values())
        print(f"device map: {sum(d == 0 or d == 'cuda' or d == 'cuda:0' for d in where)} modules on GPU, {where.count('cpu')} on CPU", flush=True)
    try:
        results = json.load(open(args.out))
    except FileNotFoundError:
        results = {"model": args.model, "runs": {}}

    for r in bundle["runs"]:
        if args.runs and r["run"] not in args.runs or r["run"] in results["runs"]:
            continue
        t0 = time.time()
        ctx = r["text"].removesuffix("<label>")
        # two sequences that share everything up to the answer: ...<label>EVALUATION vs ...<label>DEPLOYMENT.
        # Scoring whole words avoids tokenizer merges (Qwen: "<label" ">E" "VAL" vs "<label" ">" "DE").
        encs = [tok(ctx + "<label>" + w, return_offsets_mapping=True, add_special_tokens=False) for w in LABELS]
        seqs = [e["input_ids"] for e in encs]
        L = next(k for k in range(min(map(len, seqs))) if seqs[0][k] != seqs[1][k])  # first diverging token
        assert seqs[0][:L] == seqs[1][:L] and encs[0]["offset_mapping"][L - 1][1] <= len(ctx) + len("<label>")
        T = max(map(len, seqs))
        pad = tok.pad_token_id if tok.pad_token_id is not None else 0
        ids = torch.tensor([sq + [pad] * (T - len(sq)) for sq in seqs], device=args.device)  # right pad: causal, harmless
        offs = encs[0]["offset_mapping"]
        tspans = []
        for cs, ce in r["spans"]:  # tokens whose start offset lies inside the chunk's char span
            toks = [k for k, (a, b) in enumerate(offs) if cs <= a < ce and b > a]
            tspans.append((toks[0], toks[-1] + 1))
        assert tspans[-1][1] <= L
        lo = tspans[0][0] - 1  # first prediction that produces a CoT token

        def label_logprob(logits):
            """log P(whole label word | context) for each sequence -> P(EVALUATION) = sigmoid(lpE - lpD)."""
            lp = []
            for b, sq in enumerate(seqs):
                pos = torch.arange(L - 1, len(sq) - 1, device=logits.device)  # predictions of tokens L..end
                ls = F.log_softmax(logits[b, pos - lo].float(), dim=-1)
                lp.append(ls.gather(1, torch.tensor(sq[L:], device=logits.device)[:, None]).sum().item())
            return lp

        def p_eval(lp):
            return 1 / (1 + math.exp(lp[1] - lp[0]))

        SUPPRESS["range"] = None
        out = forward(model, ids, lo)
        base = F.log_softmax(out[0, : L - lo].float(), dim=-1)  # seq 0 up to and incl. the answer position
        base_lp = label_logprob(out)
        base_p = p_eval(base_lp)
        del out
        N = len(tspans)
        matrix = [[None] * N for _ in range(N)]
        answer_kl, answer_p, answer_lo = [], [], []
        for j, (s, e) in enumerate(tspans):
            SUPPRESS["range"] = (s, e)
            out = forward(model, ids, lo)
            kl_tok = kl_rows(base, out[0, : L - lo])  # per position, nats
            for i in range(j + 1, N):
                a, b = tspans[i]
                # logits at position t predict token t+1, so chunk i's tokens are predicted at a-1 .. b-2
                matrix[i][j] = kl_tok[a - 1 - lo: b - 1 - lo].mean().item()
            answer_kl.append(kl_tok[L - 1 - lo].item())  # next-token distribution where the answer starts
            lp = label_logprob(out)
            answer_p.append(p_eval(lp))
            answer_lo.append(lp[0] - lp[1])
            del out, kl_tok
        SUPPRESS["range"] = None
        results["runs"][r["run"]] = {
            "n_tokens": T, "answer_pos": L - 1, "token_spans": tspans, "matrix": matrix,
            "base_p_eval": base_p, "base_label_logprob": base_lp,
            "answer_kl": answer_kl, "answer_p_eval": answer_p,
            "answer_delta_p": [p - base_p for p in answer_p],
            # log-odds EVAL vs DEPLOY (does not saturate like P)
            "base_logodds": base_lp[0] - base_lp[1], "answer_logodds": answer_lo,
            "answer_delta_logodds": [x - (base_lp[0] - base_lp[1]) for x in answer_lo],
        }
        json.dump(results, open(args.out, "w"))
        top = max(range(N), key=lambda j: abs(answer_lo[j] - (base_lp[0] - base_lp[1])))
        print(f"{r['run']:12s} T={T:5d} N={N:3d} base P(EVAL)={base_p:.3f} (label logprobs {base_lp[0]:.1f}/{base_lp[1]:.1f}) "
              f"biggest d-logodds: chunk {top} ({answer_lo[top] - (base_lp[0] - base_lp[1]):+.2f}, dP {answer_p[top] - base_p:+.3f}) [{time.time() - t0:.0f}s]", flush=True)
    print("SUPPRESSION_DONE", flush=True)


if __name__ == "__main__":
    main()
