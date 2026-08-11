#!/usr/bin/env bash
set -euo pipefail
python3 - <<'ORACLE'
from pathlib import Path
p = Path('/workspace/src/window/window.py')
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text('"""Sliding windows over a series."""\n\n\ndef windows(values, size, step):\n    """Consecutive runs of `size` values, advancing by `step`."""\n    if size < 1 or step < 1:\n        raise ValueError("size and step must both be at least 1")\n    values = list(values)\n    return [\n        values[start : start + size]\n        for start in range(0, len(values) - size + 1, step)\n    ]\n')
p = Path('/workspace/src/report/report.py')
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text('"""Rolling summaries."""\n\nfrom stats import mean\nfrom window import windows\n\n\ndef rolling_mean(values, size, step):\n    """The mean of each complete window."""\n    return [mean(one) for one in windows(values, size, step)]\n')
p = Path('/workspace/tests/test_report.py')
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text('import pytest\n\nfrom report import rolling_mean\nfrom window import windows\n\n\ndef test_rolling_mean_over_adjacent_windows():\n    assert rolling_mean([1, 2, 3, 4], 2, 2) == [1.5, 3.5]\n\n\ndef test_a_trailing_partial_window_is_dropped():\n    assert windows([1, 2, 3, 4, 5], 2, 2) == [[1, 2], [3, 4]]\n\n\ndef test_a_bad_size_is_refused():\n    with pytest.raises(ValueError):\n        windows([1, 2, 3], 0, 1)\n')
ORACLE
