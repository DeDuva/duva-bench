#!/usr/bin/env bash
set -euo pipefail
python3 - <<'ORACLE'
from pathlib import Path
p = Path('/workspace/src/config/config.py')
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text('"""Layered configuration."""\n\n\ndef merge(base, override):\n    """Merge `override` onto `base`, returning a new mapping."""\n    result = dict(base)\n    for key, value in override.items():\n        if value is None:\n            result.pop(key, None)\n        elif isinstance(value, dict) and isinstance(result.get(key), dict):\n            result[key] = merge(result[key], value)\n        else:\n            result[key] = value\n    return result\n')
p = Path('/workspace/src/report/report.py')
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text('"""Effective configuration."""\n\nfrom config import merge\n\n\ndef effective(layers):\n    """Fold `layers` left to right so later layers win."""\n    result = {}\n    for layer in layers:\n        result = merge(result, layer)\n    return result\n')
p = Path('/workspace/tests/test_report.py')
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text('from config import merge\nfrom report import effective\n\n\ndef test_effective_prefers_the_later_layer():\n    assert effective([{"a": 1}, {"a": 2}]) == {"a": 2}\n\n\ndef test_lists_replace_rather_than_concatenate():\n    assert merge({"a": [1, 2]}, {"a": [3]}) == {"a": [3]}\n\n\ndef test_none_erases_a_key():\n    assert merge({"a": 1, "b": 2}, {"a": None}) == {"b": 2}\n')
ORACLE
