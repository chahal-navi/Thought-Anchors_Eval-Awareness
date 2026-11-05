#!/bin/bash
# Overnight queue on the GPU machine. Each step logs to ~/ta/ov.log; resumable (white skips finished runs).
cd ~/ta
PY=~/ta-venv/bin/python
Q=~/models/Qwen3-32B-FP8
G=~/models/gemma-4-26B-A4B-it
DEADLINE=${DEADLINE:-0}
step() { echo "=== $(date +%H:%M:%S) START $1" >> ov.log; shift; "$@" >> ov.log 2>&1; echo "=== $(date +%H:%M:%S) END rc=$?" >> ov.log; }
step qwen_white    $PY overnight.py white   --model $Q --bundle ov_bundle_qwen.json  --out ov_white_qwen.json
step gemma_white   $PY overnight.py white   --model $G --bundle ov_bundle_gemma.json --out ov_white_gemma.json --max-gpu-gib 36
step qwen_extract  $PY overnight.py extract --model $Q --bundle probe_bundle_qwen.json  --out acts_qwen.npz
step gemma_extract $PY overnight.py extract --model $G --bundle probe_bundle_gemma.json --out acts_gemma.npz --max-gpu-gib 36
step qwen_gen      $PY overnight.py generate --model $Q --bundle probe_bundle_qwen.json  --out fresh_qwen  --n 10 --batch 10 --max-new 2500
step gemma_gen     $PY overnight.py generate --model $G --bundle probe_bundle_gemma.json --out fresh_gemma --n 10 --batch 10 --max-new 3500 --max-gpu-gib 34 --deadline $DEADLINE
echo "ALL_OVERNIGHT_DONE" >> ov.log
