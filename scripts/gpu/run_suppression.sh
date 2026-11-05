#!/usr/bin/env bash
# On the GPU box: run each model as soon as its weights finish downloading (pdownload.log), Qwen first.
cd ~/ta
PY=~/ta-venv/bin/python
waitfor() { until grep -q "DONE $1" pdownload.log; do grep -q "FAILED" pdownload.log && { echo "download FAILED"; exit 1; }; sleep 20; done; }

waitfor Qwen/Qwen3-32B-FP8
echo "=== Qwen3-32B-FP8 $(date +%T)"
$PY suppression_kl.py --model ~/models/Qwen3-32B-FP8 --bundle bundle_qwen.json --out suppression_qwen.json 2>&1 | grep -v -i "warn\|Loading weights"

waitfor google/gemma-4-26B-A4B-it
echo "=== gemma-4-26B-A4B-it bf16 $(date +%T)"
$PY suppression_kl.py --model ~/models/gemma-4-26B-A4B-it --bundle bundle_gemma.json --out suppression_gemma.json --max-gpu-gib 36 2>&1 | grep -v -i "warn\|Loading weights"
echo "ALL_SUPPRESSION_DONE $(date +%T)"
