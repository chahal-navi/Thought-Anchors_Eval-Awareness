#!/usr/bin/env zsh
# Gemma 4 26B-A4B: the full single-turn study after screening + judging (screen_subject.py, judge.py).
# Every stage is gated on the remaining budget (budget.py, $8 cap); a stage that does not fit is skipped and
# logged. Order: cheap must-haves first, then the adaptive top-up of the resampling with whatever is left.
# Resumable: resample/behavior/register skip finished work.
cd "$(dirname "$0")"
export SUBJECT=gemma
P=${PYTHON:-python}
R=../results/gemma
N1=${N1:-20}; N2=${N2:-40}; N_FORCED=${N_FORCED:-10}; N_INS=${N_INS:-20}; N_BEH=${N_BEH:-16}
COST_ROLL=0.0002   # $ per rollout (measured 0.00014 on the shortest run, padded)
MARGIN=0.25

gate() { $P budget.py $($P -c "print(round($1 + $MARGIN, 3))") || { echo "SKIP $2 (budget)"; return 1; } }

SPECS=($($P -c "
import json
for s in json.load(open('$R/selected.json')):
    short = s['prompt'].removeprefix('probe_').replace('alpaca_eval_','a').replace('wildchat_natural_','w').replace('mt_bench_','m').replace('wildchat_test_','t')[:5]
    print(f\"{s['prompt']}:{s['eval_idx']}:{s['depl_idx']}:{short}:{s['eval_chunks']}:{s['depl_chunks']}\")"))
echo "SPECS: $SPECS"
RUNS=(); EVALRUNS=()
for s in $SPECS; do IFS=: read p e d n ce cd <<< "$s"; RUNS+=(${n}_eval ${n}_depl); EVALRUNS+=(${n}_eval); done

resample_all() {  # $1 = rollouts per position, $2 = extra flags
  for s in $SPECS; do IFS=: read p e d n ce cd <<< "$s"
    for lab idx nch in eval $e $ce depl $d $cd; do
      gate $($P -c "print(round(($nch + 1) * $1 * $COST_ROLL * ${3:-1}, 3))") "resample ${n}_$lab n=$1" && \
        $P resample.py --prompt $p --sample-idx $idx --run-name ${n}_$lab -n $1 --workers 24 $2 2>&1 | grep -v "it/s\]\|s/it\]" | tail -2
    done
  done
}

echo "=== 1. resampling, $N1 rollouts at every position"
resample_all $N1 ""
$P analyze.py --runs $RUNS 2>&1 | grep -v Warning

echo "=== 2. forced answer (label prefill)"
gate 0.5 forced && $P -u forced.py --runs $RUNS -k $N_FORCED --workers 24

echo "=== 3. register ablation"
gate 0.4 register && $P -u register_ablation.py -n 20 --workers 24 2>&1 | grep -v "it/s\]\|s/it\]"

echo "=== 4. sentence insertion on the EVAL CoTs"
gate $($P -c "print(round(${#EVALRUNS} * 12 * $N_INS * $COST_ROLL * 1.3, 2))") insertion && \
  $P -u insertion.py --runs $EVALRUNS -n $N_INS --workers 24 2>&1 | grep -v "it/s\]\|s/it\]"

echo "=== 5. refusal experiment"
gate 0.6 behavior-screen && $P -u behavior.py screen --n-xstest 40 --n-orbench 60 --n1 5 --workers 24 2>&1 | grep -v "it/s\]\|s/it\]" | tail -25
gate 1.5 behavior-run && $P -u behavior.py run -n $N_BEH --max-prompts 12 --n-probe 10 --workers 24 2>&1 | grep -v "it/s\]\|s/it\]"

echo "=== 6. round-1 hand-made cue ablations on the pilot transcripts"
gate 0.2 cue-ablation && $P -u cue_ablation.py -n 20 --workers 24 2>&1 | grep -v "it/s\]\|s/it\]" | tail -30

echo "=== 7. adaptive top-up to $N2 rollouts at unsaturated positions"
resample_all $N2 --adaptive 0.5

$P analyze.py --runs $RUNS 2>&1 | grep -v Warning
$P build_report_data.py
$P dump_readable.py
$P budget.py
echo GEMMA_DONE
