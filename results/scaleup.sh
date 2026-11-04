cd ../scripts
P=python
# name  prompt  eval_idx  depl_idx
SPECS="a102:probe_alpaca_eval_102:10:15 wb6a:probe_wildchat_natural_b6a54722:16:6 a435:probe_alpaca_eval_435:7:8 m682:probe_mt_bench_68280443:14:9 w94b:probe_wildchat_natural_94b8e051:5:16 wacd:probe_wildchat_natural_acd01895:8:4 a451:probe_alpaca_eval_451:11:16"
for s in ${=SPECS}; do IFS=: read n p e d <<< "$s"; $P judge.py --prompt $p --sample-idx $e $d > ../results/judge_$n.log 2>&1 & done; wait
echo JUDGE_DONE
RUNS=""; EVALRUNS=""
for s in ${=SPECS}; do IFS=: read n p e d <<< "$s"
  $P resample.py --prompt $p --sample-idx $e --run-name ${n}_eval -n 50 --workers 32
  $P resample.py --prompt $p --sample-idx $d --run-name ${n}_depl -n 50 --workers 32
  RUNS="$RUNS ${n}_eval ${n}_depl"; EVALRUNS="$EVALRUNS ${n}_eval"
done
echo RESAMPLE_DONE
$P -u forced.py --runs ${=RUNS} -k 20 --workers 16
$P -u insertion.py --runs ${=EVALRUNS} -n 30 --workers 24
while pgrep -f "register_ablation.py" >/dev/null; do sleep 20; done
$P analyze.py 2>&1 | grep -v Warning
$P build_report_data.py
$P dump_readable.py
echo SCALEUP_DONE
