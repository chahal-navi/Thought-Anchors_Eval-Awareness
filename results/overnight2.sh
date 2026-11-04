set -x
cd ../scripts
P=python
$P resample.py --prompt probe_alpaca_eval_366 --sample-idx 4 --run-name a366_eval -n 50 --workers 32
$P resample.py --prompt probe_alpaca_eval_802 --sample-idx 12 --run-name a802_eval -n 50 --workers 32
$P resample.py --prompt probe_wildchat_natural_68b28efc --sample-idx 8 --run-name w68_eval -n 50 --workers 32
$P resample.py --prompt probe_wildchat --sample-idx 0 --run-name probe_wildchat_s0 -n 50 --workers 32
$P resample.py --prompt probe_alpaca_eval_366 --sample-idx 3 --run-name a366_depl -n 50 --workers 32
$P resample.py --prompt probe_alpaca_eval_802 --sample-idx 18 --run-name a802_depl -n 50 --workers 32
$P resample.py --prompt probe_wildchat_natural_68b28efc --sample-idx 4 --run-name w68_depl -n 50 --workers 32
echo RESAMPLE_DONE
