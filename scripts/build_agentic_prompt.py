"""Agentic-eval prompt: a mid-trajectory transcript from GDM InterCode CTF, run with Inspect.

1. Runs the inspect_evals `gdm_intercode_ctf` task (Docker sandbox, bash + python tools,
   react agent, unmodified system prompt) on one sample with the subject model via OpenRouter.
2. Takes the ModelEvent at agent turn `--turn` and saves its exact input (system prompt,
   task, previous tool calls and tool outputs) plus tool schemas as the prompt. The subject
   model's next CoT is then generated from this context.

Earlier assistant reasoning is dropped from the prompt messages (Qwen3 / R1 chat templates
strip it from past turns anyway) but kept in the full transcript file.

Usage:
    python build_agentic_prompt.py                      # run the eval, then extract
    python build_agentic_prompt.py --log logs/x.eval    # re-extract from an existing log
"""

import argparse
import json

from inspect_ai import eval as inspect_eval
from inspect_ai.log import read_eval_log
from inspect_ai.model import ChatMessage, ContentReasoning, ContentText
from inspect_evals.gdm_intercode_ctf import gdm_intercode_ctf

from common import LOGS_DIR, PROMPTS_DIR, save_prompt


def text_of(msg: ChatMessage) -> str:
    if isinstance(msg.content, str):
        return msg.content
    return "".join(c.text for c in msg.content if isinstance(c, ContentText))


def reasoning_of(msg: ChatMessage) -> str | None:
    if isinstance(msg.content, str):
        return None
    parts = [c.reasoning for c in msg.content if isinstance(c, ContentReasoning)]
    return "\n".join(parts) or None


def to_openai(msg: ChatMessage, keep_reasoning: bool = False) -> dict:
    out = {"role": msg.role, "content": text_of(msg)}
    if msg.role == "assistant":
        if msg.tool_calls:
            out["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function, "arguments": json.dumps(tc.arguments)},
                }
                for tc in msg.tool_calls
            ]
        if keep_reasoning and (r := reasoning_of(msg)):
            out["reasoning"] = r
    if msg.role == "tool":
        out["tool_call_id"] = msg.tool_call_id
        if msg.error:
            out["content"] += f"\n[tool error: {msg.error.message}]"
    return out


def run_eval(model: str, sample_id: int) -> str:
    [log] = inspect_eval(
        gdm_intercode_ctf(sample_ids=[sample_id]),
        model=f"openrouter/{model}",
        log_dir=str(LOGS_DIR),
        max_retries=3,
    )
    if log.status != "success":
        raise RuntimeError(f"Eval did not succeed: {log.status} {log.error}")
    return log.location


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="qwen/qwen3-32b", help="OpenRouter model id (subject model)")
    parser.add_argument("--sample-id", type=int, default=32)  # "crack the password, 7 candidates"
    parser.add_argument("--turn", type=int, default=2, help="0-indexed agent turn to cut at (clamped)")
    parser.add_argument("--log", default=None, help="existing .eval log to extract from")
    args = parser.parse_args()

    log_path = args.log or run_eval(args.model, args.sample_id)
    log = read_eval_log(log_path, resolve_attachments=True)
    sample = log.samples[0]
    model_events = [e for e in sample.events if e.event == "model"]
    turn = min(args.turn, len(model_events) - 1)
    event = model_events[turn]

    # Full trajectory, with reasoning, for reference / choosing other cut points
    PROMPTS_DIR.mkdir(exist_ok=True)
    transcript_path = PROMPTS_DIR / "agentic_full_transcript.json"
    transcript_path.write_text(
        json.dumps([to_openai(m, keep_reasoning=True) for m in sample.messages], indent=2, ensure_ascii=False)
    )
    print(f"Saved {transcript_path} ({len(sample.messages)} messages, {len(model_events)} model calls)")

    save_prompt(
        {
            "name": "agentic",
            "condition": "agentic_eval",
            "source": {
                "benchmark": "inspect_evals/gdm_intercode_ctf",
                "sample_id": sample.id,
                "inspect_log": str(log_path),
                "rollout_model": log.eval.model,
                "turn": turn,
                "n_turns": len(model_events),
            },
            "messages": [to_openai(m) for m in event.input],
            "tools": [{"type": "function", "function": t.model_dump(exclude_none=True)} for t in event.tools],
            "metadata": {
                "target_flag": sample.target,
                "score": {k: v.value for k, v in (sample.scores or {}).items()},
                "original_next_message": to_openai(event.output.message, keep_reasoning=True),
            },
        }
    )


if __name__ == "__main__":
    main()
