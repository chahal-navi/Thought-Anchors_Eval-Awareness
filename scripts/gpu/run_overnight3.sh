#!/bin/bash
# Third queue (designed after exp 6 came back null): reader heads. Waits for run_overnight2.sh to finish.
cd ~/ta
PY=~/ta-venv/bin/python
Q=~/models/Qwen3-32B-FP8
G=~/models/gemma-4-26B-A4B-it
step() { echo "=== $(date +%H:%M:%S) START $1" >> ov.log; shift; "$@" >> ov.log 2>&1; echo "=== $(date +%H:%M:%S) END rc=$?" >> ov.log; }
until grep -q ALL_OVERNIGHT_DONE ov.log; do sleep 30; done
step qwen_readers  $PY overnight.py readers --model $Q --bundle ov_bundle_qwen.json  --out readers_qwen.json --window 40 56
step gemma_readers $PY overnight.py readers --model $G --bundle ov_bundle_gemma.json --out readers_gemma.json --max-gpu-gib 36 --window 11 22
echo "READERS_QUEUE_DONE" >> ov.log
