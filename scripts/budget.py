"""Budget gate for the Gemma runs: exit 0 if `spent + need <= budget`, else exit 1.

Usage:
    python budget.py            # print spend so far
    python budget.py 1.5        # can we afford a stage that costs ~$1.5?
"""

import sys

from common import GEMMA_BUDGET, KEY_USAGE_BEFORE_GEMMA, key_usage

spent = key_usage() - KEY_USAGE_BEFORE_GEMMA
need = float(sys.argv[1]) if len(sys.argv) > 1 else 0.0
ok = spent + need <= GEMMA_BUDGET
print(f"gemma spend ${spent:.2f} of ${GEMMA_BUDGET:.2f}; need ${need:.2f} -> {'OK' if ok else 'OVER BUDGET'}")
sys.exit(0 if ok else 1)
