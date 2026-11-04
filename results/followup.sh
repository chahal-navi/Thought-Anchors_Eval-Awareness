cd ../scripts
P=python
while ! grep -q RESAMPLE_DONE ../results/resample2.log; do sleep 20; done
while pgrep -f "cue_ablation.py|forced.py --runs probe_mmlu" >/dev/null; do sleep 20; done
$P analyze.py 2>&1 | grep -v Warning
$P forced.py --runs a366_eval a802_eval w68_eval probe_wildchat_s0 a366_depl a802_depl w68_depl -k 20 --workers 16
$P insertion.py --runs a366_eval a802_eval w68_eval probe_wildchat -n 30 --workers 24
$P build_report_data.py
echo FOLLOWUP_DONE
