#!/usr/bin/env bash
set -euo pipefail
python3 - <<'PY'
from pathlib import Path
p = Path('/workspace/kelvra/stats/stats.py')
body = p.read_text()
body = body.replace('(max(values) - min(values)) // 2', '(max(values) - min(values)) / 2')
p.write_text(body)
PY
