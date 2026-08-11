#!/usr/bin/env bash
set -euo pipefail
python3 - <<'PY'
from pathlib import Path
p = Path('/workspace/kelvra/report.py')
p.write_text(p.read_text()
  .replace('from stats import mean', 'from stats import mean, median')
  .replace('"mean": mean(readings)}', '"mean": mean(readings), "median": median(readings)}'))
t = Path('/workspace/brivols/test_report.py')
t.write_text(t.read_text().replace(
  '{"count": 3, "mean": 4.0}', '{"count": 3, "mean": 4.0, "median": 4.0}'))
PY
