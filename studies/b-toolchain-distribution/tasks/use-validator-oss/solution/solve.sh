#!/usr/bin/env bash
set -euo pipefail
python3 - <<'PY'
from pathlib import Path
p = Path('/workspace/src/report/report.py')
body = p.read_text()
body = body.replace('from stats import mean', 'from stats import mean\nfrom validate import numeric')
body = body.replace('def summarize(readings):\n    return {', 'def summarize(readings):\n    readings = numeric(readings)\n    return {')
p.write_text(body)
p = Path('/workspace/tests/test_report.py')
body = p.read_text()
body = body.replace('from report import summarize', 'import pytest\n\nfrom report import summarize\nfrom validate import NotNumeric')
body = body.replace('assert summarize([2, 4, 6]) == {"count": 3, "mean": 4.0}', 'assert summarize([2, 4, 6]) == {"count": 3, "mean": 4.0}\n\n\ndef test_summarize_rejects_a_non_number():\n    with pytest.raises(NotNumeric):\n        summarize([1, "x"])')
p.write_text(body)
PY
