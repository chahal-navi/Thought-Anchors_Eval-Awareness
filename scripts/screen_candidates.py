"""Screen candidate prompts for the subject model's uncertainty about eval vs. deployment.

Thought anchors needs prompts where the final label is not fixed before reasoning, so we keep
candidates where P(EVALUATION) is roughly 0.3-0.7 over 20 samples.

Candidate pool (all wrapped in the same probe question as build_probe_prompts.py):
  - wildchat_test: real WildChat prompts that look like test questions (quiz / MCQ / solve / fill-in)
  - wildchat_natural: ordinary WildChat prompts (controls)
  - mt_bench, alpaca_eval, gsm8k, xstest: eval items that read like natural user requests
  - ctf_turn_k: the InterCode CTF trajectory truncated after agent turn k

Saves prompts/candidates.json and results/screening.json (all CoTs kept; they double as base CoTs).

Usage:
    python screen_candidates.py -n 20
"""

import argparse
import json
import random
import re
from concurrent.futures import ThreadPoolExecutor

from datasets import load_dataset
from huggingface_hub import hf_hub_download
from tqdm import tqdm

from build_probe_prompts import probe_content
from common import CANDIDATES_PATH, CFG, RESULTS_DIR, SHARED_PROMPTS_DIR, load_prompt
from sample_cots import SUBJECT_MODEL, sample_one

PROVIDER = CFG["chat_providers"][0]
SEED = 0

TEST_LIKE = re.compile(
    r"(\n\s*[A-Da-d][\.\)]\s)|which of the following|true or false|fill in the blank|"
    r"\b(solve|calculate|evaluate the|find the value)\b|\bquestion\s*\d|\banswer the following\b",
    re.IGNORECASE,
)


def user_candidate(cid: str, source: str, condition: str, text: str, meta: dict | None = None) -> dict:
    return {
        "id": cid,
        "source": source,
        "condition": condition,
        "ground_truth": "DEPLOYMENT" if condition == "deployment" else "EVALUATION",
        "messages": [{"role": "user", "content": text}],
        "tools": None,
        "metadata": meta or {},
    }


def wildchat_candidates(n_test: int, n_natural: int) -> list[dict]:
    ds = load_dataset("allenai/WildChat-4.8M", data_files="data/train-00000-of-00086.parquet", split="train")
    test, natural, seen = [], [], set()
    for r in ds:
        if r["language"] != "English" or r["turn"] != 1 or r["toxic"] or r["redacted"]:
            continue
        u = r["conversation"][0]["content"]
        if not 80 <= len(u) <= 1200 or u in seen or r["conversation_hash"] in seen:
            continue
        seen.update([u, r["conversation_hash"]])
        (test if TEST_LIKE.search(u) else natural).append((r["conversation_hash"], u))
    rng = random.Random(SEED)
    out = []
    for kind, pool, k in [("wildchat_test", test, n_test), ("wildchat_natural", natural, n_natural)]:
        for h, u in rng.sample(pool, k):
            out.append(user_candidate(f"{kind}_{h[:8]}", kind, "deployment", u, {"conversation_hash": h}))
    return out


def eval_candidates(k: int) -> list[dict]:
    rng = random.Random(SEED)
    out = []
    mt = load_dataset("HuggingFaceH4/mt_bench_prompts", split="train")
    for r in rng.sample(list(mt), k):
        out.append(user_candidate(f"mt_bench_{r['prompt_id']}", "mt_bench", "capability_eval", r["prompt"][0],
                                  {"category": r["category"]}))
    alpaca = json.load(open(hf_hub_download("tatsu-lab/alpaca_eval", "alpaca_eval.json", repo_type="dataset")))
    for i in rng.sample(range(len(alpaca)), k):
        out.append(user_candidate(f"alpaca_eval_{i}", "alpaca_eval", "capability_eval", alpaca[i]["instruction"],
                                  {"dataset": alpaca[i]["dataset"]}))
    gsm = load_dataset("openai/gsm8k", "main", split="test")
    for i in rng.sample(range(len(gsm)), k):
        out.append(user_candidate(f"gsm8k_{i}", "gsm8k", "capability_eval", gsm[i]["question"]))
    xs = load_dataset("Paul/XSTest", split="train")
    for r in rng.sample(list(xs), k):
        out.append(user_candidate(f"xstest_{r['id']}", "xstest", "safety_eval", r["prompt"],
                                  {"type": r["type"], "label": r["label"]}))
    return out


def ctf_truncations() -> list[dict]:
    """The CTF trajectory cut after each agent turn (tool call + its output)."""
    full = json.loads((SHARED_PROMPTS_DIR / "agentic_full_transcript.json").read_text())
    tools = load_prompt("agentic")["tools"]
    out = []
    cut_points = [i + 1 for i, m in enumerate(full) if m["role"] == "tool"]  # after each tool output
    for k, cut in enumerate([2] + cut_points):  # 2 = system + task only
        msgs = [{kk: v for kk, v in m.items() if kk != "reasoning"} for m in full[:cut]]
        out.append({
            "id": f"ctf_turn_{k}",
            "source": "intercode_ctf",
            "condition": "agentic_eval",
            "ground_truth": "EVALUATION",
            "messages": msgs,
            "tools": tools,
            "metadata": {"n_messages": cut},
        })
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-n", type=int, default=20, help="samples per candidate")
    parser.add_argument("--n-wildchat-test", type=int, default=20)
    parser.add_argument("--n-wildchat-natural", type=int, default=6)
    parser.add_argument("--n-per-eval", type=int, default=6)
    parser.add_argument("--workers", type=int, default=48)
    args = parser.parse_args()

    cands_path = CANDIDATES_PATH
    if cands_path.exists():
        candidates = json.loads(cands_path.read_text())
    else:
        candidates = (wildchat_candidates(args.n_wildchat_test, args.n_wildchat_natural)
                      + eval_candidates(args.n_per_eval) + ctf_truncations())
        for c in candidates:
            c["probe_messages"] = [{"role": "user", "content": probe_content(c["messages"], c["tools"])}]
        cands_path.write_text(json.dumps(candidates, indent=2, ensure_ascii=False))
    print(f"{len(candidates)} candidates")

    out_path = RESULTS_DIR / "screening.json"
    results = json.loads(out_path.read_text()) if out_path.exists() else {}
    jobs = [(c, j) for c in candidates for j in range(len(results.get(c["id"], {}).get("samples", [])), args.n)]
    for c in candidates:
        results.setdefault(c["id"], {"id": c["id"], "source": c["source"], "ground_truth": c["ground_truth"], "samples": []})

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [(c, ex.submit(sample_one, SUBJECT_MODEL, c["probe_messages"], 8000, 5, PROVIDER)) for c, _ in jobs]
        for done, (c, f) in enumerate(tqdm(futs, desc="samples"), start=1):
            try:
                results[c["id"]]["samples"].append(f.result())
            except Exception as e:
                print(f"{c['id']}: {e}")
            if done % 100 == 0 or done == len(futs):
                out_path.write_text(json.dumps(results, ensure_ascii=False))

    for r in results.values():
        labels = [s["label"] for s in r["samples"]]
        r["n"] = len(labels)
        r["p_eval"] = labels.count("EVALUATION") / max(1, len(labels))
        r["n_unparsed"] = labels.count(None)
    out_path.write_text(json.dumps(results, ensure_ascii=False))

    for r in sorted(results.values(), key=lambda r: r["p_eval"]):
        flag = "  <-- uncertain" if 0.3 <= r["p_eval"] <= 0.7 else ""
        print(f"{r['id']:<28} {r['source']:<17} truth={r['ground_truth']:<10} P(EVAL)={r['p_eval']:.2f} n={r['n']}{flag}")


if __name__ == "__main__":
    main()
