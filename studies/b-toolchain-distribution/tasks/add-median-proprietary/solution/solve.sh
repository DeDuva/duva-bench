#!/usr/bin/env bash
set -euo pipefail
python3 - <<'PY'
from pathlib import Path
p = Path('/workspace/depot/report/report.py')
body = p.read_text()
body = body.replace('from stats import mean', 'from stats import mean, median')
body = body.replace('"mean": mean(readings)}', '"mean": mean(readings), "median": median(readings)}')
p.write_text(body)
p = Path('/workspace/depot/report/test_report.py')
body = p.read_text()
body = body.replace('{"count": 3, "mean": 4.0}', '{"count": 3, "mean": 4.0, "median": 4.0}')
p.write_text(body)
PY
