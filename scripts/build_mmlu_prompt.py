"""Capability-eval prompt: one MMLU question in the standard zero-shot MMLU format.

The format follows the original MMLU paper / lm-eval-harness ("The following are multiple
choice questions (with answers) about ...", lettered options, trailing "Answer:"), so the
prompt carries the usual benchmark cues.
"""

import argparse

from datasets import load_dataset

from common import save_prompt

LETTERS = "ABCD"


def format_mmlu(row: dict) -> str:
    subject = row["subject"].replace("_", " ")
    options = "\n".join(f"{l}. {c}" for l, c in zip(LETTERS, row["choices"]))
    return (
        f"The following are multiple choice questions (with answers) about {subject}.\n\n"
        f"{row['question'].strip()}\n{options}\nAnswer:"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--subject", default="high_school_physics")
    parser.add_argument("--index", type=int, default=24)  # dipole midpoint field, answer D (7.2e5 N/C)
    args = parser.parse_args()

    row = load_dataset("cais/mmlu", args.subject, split="test")[args.index]
    save_prompt(
        {
            "name": "mmlu",
            "condition": "capability_eval",
            "source": {"dataset": "cais/mmlu", "subject": args.subject, "split": "test", "index": args.index},
            "messages": [{"role": "user", "content": format_mmlu(row)}],
            "tools": None,
            "metadata": {"answer": LETTERS[row["answer"]], "choices": row["choices"]},
        }
    )


if __name__ == "__main__":
    main()
