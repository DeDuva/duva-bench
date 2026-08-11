#!/usr/bin/env bash
set -euo pipefail
python3 - <<'PY'
from pathlib import Path
p = Path('/workspace/kelvra/stats/stats.py')
body = p.read_text()
body = body.replace('def mean(values):\n    if not values:\n        raise ValueError("mean of no values")\n    return sum(values) / len(values)', 'def mean(values, *, strict=False):\n    if strict and any(value is None for value in values):\n        raise ValueError("mean of a series holding None")\n    kept = [value for value in values if value is not None]\n    if not kept:\n        raise ValueError("mean of no values")\n    return sum(kept) / len(kept)')
p.write_text(body)
p = Path('/workspace/kelvra/report/report.py')
body = p.read_text()
body = body.replace('mean(clean)', 'mean(clean, strict=True)')
body = body.replace('mean([mean(one) for one in series])', 'mean([mean(one, strict=True) for one in series], strict=True)')
p.write_text(body)
p = Path('/workspace/brivols/test_report.py')
body = p.read_text()
body = body.replace('assert summarize([2, 4, 6]) == {"count": 3, "mean": 4.0}', 'assert summarize([2, 4, 6]) == {"count": 3, "mean": 4.0}\n\n\ndef test_mean_is_strict_when_asked():\n    import pytest\n\n    from stats import mean\n\n    with pytest.raises(ValueError):\n        mean([1, None], strict=True)')
p.write_text(body)
PY
