cd ../scripts
P=python
# name  prompt  eval_idx  depl_idx
SPECS="mt_a102:mt_alpaca_eval_102:9:14 mt_wb6a:mt_wildchat_natural_b6a54722:14:4 mt_m682:mt_mt_bench_68280443:1:16"
for s in ${=SPECS}; do IFS=: read n p e d <<< "$s"; $P judge.py --prompt $p --sample-idx $e $d > ../results/judge_$n.log 2>&1 & done; wait
grep -L "Saved" ../results/judge_mt_*.log && echo "JUDGE FAILED?"
echo JUDGE_DONE
RUNS=""
for s in ${=SPECS}; do IFS=: read n p e d <<< "$s"
  $P resample.py --prompt $p --sample-idx $e --run-name ${n}_eval -n 50 --workers 32
  $P resample.py --prompt $p --sample-idx $d --run-name ${n}_depl -n 50 --workers 32
  RUNS="$RUNS ${n}_eval ${n}_depl"
done
echo RESAMPLE_DONE
$P analyze.py --runs ${=RUNS} 2>&1 | grep -v Warning
echo PILOT_DONE
