"""Deployment prompt: the first user turn of a real WildChat conversation.

The conversation was chosen by hand from English, single-turn, non-toxic, non-redacted
conversations in the first WildChat-4.8M shard (first user message 200-900 chars).
"""

import argparse

from datasets import load_dataset

from common import save_prompt

DATA_FILE = "data/train-00000-of-00086.parquet"


def main():
    parser = argparse.ArgumentParser()
    # Chase travel card / authorized user question (gpt-4-0314, 2023)
    parser.add_argument("--conversation-hash", default="7f21c7ac986541eb5cff3eb249541ee4")
    args = parser.parse_args()

    ds = load_dataset("allenai/WildChat-4.8M", data_files=DATA_FILE, split="train")
    ds = ds.filter(lambda r: r["conversation_hash"] == args.conversation_hash)
    assert len(ds) == 1, f"Expected 1 match for {args.conversation_hash}, found {len(ds)}"
    row = ds[0]
    first_user = row["conversation"][0]
    assert first_user["role"] == "user"

    save_prompt(
        {
            "name": "wildchat",
            "condition": "deployment",
            "source": {
                "dataset": "allenai/WildChat-4.8M",
                "data_file": DATA_FILE,
                "conversation_hash": args.conversation_hash,
            },
            "messages": [{"role": "user", "content": first_user["content"]}],
            "tools": None,
            "metadata": {
                "original_model": row["model"],
                "timestamp": str(row["timestamp"]),
                "language": row["language"],
                "original_response": row["conversation"][1]["content"],
            },
        }
    )


if __name__ == "__main__":
    main()
