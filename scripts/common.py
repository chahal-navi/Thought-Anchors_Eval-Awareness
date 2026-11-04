"""Shared helpers for building the pilot prompts.

Every prompt is saved as prompts/<name>.json with the same schema:
    {
      "name": str,                      # short id used by later experiments
      "condition": "capability_eval" | "agentic_eval" | "deployment",
      "source": {...},                  # dataset / sample ids needed to reproduce it
      "messages": [...],                # OpenAI-style chat messages, ready for a chat template
      "tools": [...] | null,            # OpenAI-style function schemas (agentic prompt only)
      "metadata": {...},                # ground truth, notes, etc.
    }
"""

import json
import os
from pathlib import Path

from openai import OpenAI

CAPSTONE_DIR = Path(__file__).resolve().parents[1]
PROMPTS_DIR = CAPSTONE_DIR / "prompts"
LOGS_DIR = CAPSTONE_DIR / "logs"
RESULTS_DIR = CAPSTONE_DIR / "results"
SHARED_PROMPTS_DIR = PROMPTS_DIR  # candidates.json, pilot prompts and transcripts shared by all subject models
CANDIDATES_PATH = SHARED_PROMPTS_DIR / "candidates.json"

openrouter_client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=os.getenv("OPENROUTER_API_KEY"))

# Subject model, chosen with the SUBJECT env var (default qwen = the original study, paths unchanged).
# Other subjects write to results/<subject>/ and prompts/<subject>/ so the Qwen results are never touched.
SUBJECTS = {
    "qwen": {
        "model": "qwen/qwen3-32b",
        "tokenizer": "Qwen/Qwen3-32B",
        "chat_providers": ["deepinfra/fp8"],
        "raw_providers": ["deepinfra/fp8"],  # the only provider that continues a raw prompt verbatim
        "template_kwargs": {},
        "think_open": "<think>\n",
        "think_close": "\n</think>\n\n",
        "forced_max_tokens": 200,
    },
    "gemma": {
        "model": "google/gemma-4-26b-a4b-it",
        "tokenizer": "google/gemma-4-26B-A4B-it",
        # CoreWeave continues raw prompts verbatim AND keeps special tokens, so <channel|> separates the
        # reasoning from the answer. NextBit/Parasail also continue verbatim (fallbacks; they strip <channel|>).
        "chat_providers": ["coreweave/bf16", "nextbit/bf16", "parasail/bf16"],
        "raw_providers": ["coreweave/bf16", "nextbit/bf16", "parasail/bf16"],
        "template_kwargs": {"enable_thinking": True},  # adds the <|think|> system turn
        "think_open": "<|channel>thought\n",
        "think_close": "\n<channel|>",
        "forced_max_tokens": 6,
        # Gemma explains at length before its label, so the forced answer prefills "<label>" right after
        # <channel|> and reads the next word. Checked against free-form forced answers (same verdicts, no junk).
        "forced_label_prefill": "<label>",
    },
}
SUBJECT = os.getenv("SUBJECT", "qwen")
CFG = SUBJECTS[SUBJECT]
SUBJECT_MODEL = CFG["model"]
if SUBJECT != "qwen":
    RESULTS_DIR = RESULTS_DIR / SUBJECT
    PROMPTS_DIR = PROMPTS_DIR / SUBJECT
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    PROMPTS_DIR.mkdir(parents=True, exist_ok=True)


def provider_body(raw: bool = False, only_first: bool = False) -> dict:
    order = CFG["raw_providers" if raw else "chat_providers"]
    return {"order": order[:1] if only_first else order, "allow_fallbacks": False}


_tokenizer = None


def chat_template(messages: list[dict]) -> str:
    """Subject model's chat template up to the start of the assistant turn (reasoning on)."""
    global _tokenizer
    if _tokenizer is None:
        from transformers import AutoTokenizer
        _tokenizer = AutoTokenizer.from_pretrained(CFG["tokenizer"])
    return _tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True, **CFG["template_kwargs"])


def raw_cot_prompt(messages: list[dict], prefix: str, exact: bool = False) -> str:
    """Raw prompt that makes the model continue its reasoning after `prefix`.

    Qwen (original study): prefix = chunks joined with spaces, plus a trailing space.
    exact=True: prefix is a verbatim slice of the original CoT (keeps line breaks), appended as is."""
    if exact:
        return chat_template(messages) + CFG["think_open"] + prefix
    return chat_template(messages) + CFG["think_open"] + (prefix + " " if prefix else "")


def cot_prefixes(reasoning: str, chunks: list[str]) -> list[str]:
    """Verbatim prefixes of `reasoning` ending right before chunk i (i = 0..N; the last is the whole CoT).

    The splitter turns newlines into spaces (a 1:1 character swap), so chunk i is located in the
    newline-free copy and the same offsets are used on the original text. Used for Gemma, whose CoTs are
    markdown outlines that a space-joined prefix would flatten."""
    import re

    starts, pos = [], 0
    for c in chunks:
        # whitespace-insensitive match (merged header chunks and newline->space swaps change whitespace)
        pattern = r"\s*".join(re.escape(ch) for ch in c[:80] if not ch.isspace())
        m = re.compile(pattern).search(reasoning, pos)
        if m is None:
            raise ValueError(f"chunk not found in CoT: {c[:60]!r}")
        starts.append(m.start())
        pos = m.start() + 1
    return [reasoning[:s] for s in starts] + [reasoning.strip()]


def use_exact_prefixes() -> bool:
    return SUBJECT != "qwen"


def forced_prompt(messages: list[dict], prefix: str) -> str:
    """Raw prompt with the reasoning closed right after `prefix`, so the model must answer now."""
    return chat_template(messages) + CFG["think_open"] + prefix + CFG["think_close"]


def split_raw_output(text: str, reasoning: str = "") -> tuple[str, str, bool]:
    """(reasoning continuation, visible answer, split_found) from a raw completion."""
    marker = CFG["think_close"].strip()
    if marker in text:
        r, a = text.split(marker, 1)
        return reasoning + r, a.replace("<turn|>", "").strip(), True
    if reasoning:  # provider already separated them
        return reasoning, text.strip(), True
    return text, text, False  # no separator returned (provider stripped special tokens)


def save_prompt(record: dict) -> Path:
    PROMPTS_DIR.mkdir(exist_ok=True)
    path = PROMPTS_DIR / f"{record['name']}.json"
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False))
    print(f"Saved {path}")
    return path


def load_prompt(name: str) -> dict:
    path = PROMPTS_DIR / f"{name}.json"
    if not path.exists():
        path = SHARED_PROMPTS_DIR / f"{name}.json"
    return json.loads(path.read_text())


def render_transcript(messages: list[dict], tools: list[dict] | None = None) -> str:
    """Render OpenAI-style messages (+ tool schemas) as plain text. Assistant reasoning is not shown."""
    parts = []
    if tools:
        names = ", ".join(t["function"]["name"] for t in tools)
        parts.append(f"[AVAILABLE TOOLS]\n{names}")
    for m in messages:
        text = m["content"].strip()
        for tc in m.get("tool_calls", []):
            text += f"\n<tool_call name={tc['function']['name']}>{tc['function']['arguments']}</tool_call>"
        parts.append(f"[{m['role'].upper()}]\n{text}")
    return "\n\n".join(parts)


KEY_USAGE_BEFORE_GEMMA = 9.57976979  # OpenRouter key usage (USD) when the Gemma runs started, 3 Nov 2026
GEMMA_BUDGET = 8.0


def key_usage() -> float:
    """Total USD spent on this OpenRouter key so far."""
    import urllib.request

    req = urllib.request.Request("https://openrouter.ai/api/v1/key",
                                 headers={"Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY')}"})
    return float(json.loads(urllib.request.urlopen(req, timeout=30).read())["data"]["usage"])
