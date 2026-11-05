"""Standalone copy of the sentence splitter (judge.split_solution_into_chunks + merge_markdown_headers) and
common.cot_prefixes, so the GPU machine needs no API dependencies."""
import re


def split_solution_into_chunks(text: str, gemma: bool = False) -> list[str]:
    if "<think>" in text:
        text = text.split("<think>")[1]
    if "</think>" in text:
        text = text.split("</think>")[0]
    text = text.strip()
    text = re.sub(r"(\d)\.(\d)", r"\1<DECIMAL>\2", text)
    text = re.sub(r"\n(\d)\.(\s)", r"\n\1<DECIMAL>\2", text)
    sentences = re.split(r"([!?:\n]|(?<!\n\d)\.(?=\s|$))", text)
    chunks = []
    for i in range(0, len(sentences) - 1, 2):
        chunks.append((sentences[i] + sentences[i + 1]).replace("\n", " "))
    if len(sentences) % 2 == 1 and sentences[-1].strip():
        chunks.append(sentences[-1])
    chunks = [re.sub(r"<DECIMAL>", ".", c) for c in chunks]
    if not chunks:
        return []
    merged = [chunks[0]]
    for c in chunks[1:]:
        if len(merged[-1]) < 10:
            merged[-1] += c
        else:
            merged.append(c)
    merged = [c.strip() for c in merged if c.strip()]
    return merge_markdown_headers(merged) if gemma else merged


def merge_markdown_headers(chunks: list[str]) -> list[str]:
    out, carry = [], ""
    for c in chunks:
        c = (carry + " " + c).strip() if carry else c
        bare = re.sub(r"[\s*_#`>\-]+", " ", c).strip()
        if (bare.endswith(":") and len(bare) < 40) or not re.search(r"[A-Za-z0-9]", bare):
            carry = c
            continue
        out.append(c)
        carry = ""
    if carry:
        out.append(carry)
    return out


def cot_prefixes(reasoning: str, chunks: list[str]) -> list[str]:
    starts, pos = [], 0
    for c in chunks:
        pattern = r"\s*".join(re.escape(ch) for ch in c[:80] if not ch.isspace())
        m = re.compile(pattern).search(reasoning, pos)
        if m is None:
            raise ValueError(f"chunk not found in CoT: {c[:60]!r}")
        starts.append(m.start())
        pos = m.start() + 1
    return [reasoning[:s] for s in starts] + [reasoning.strip()]
