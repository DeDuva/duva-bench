#!/usr/bin/env bash
# Harbor's verifier: did the environment end up in the state the task asked for.
# Deliberately separate from duva-bench's grader, which answers "how well" under
# a different ADP identity.
set -uo pipefail

test -f /app/merge.py || { echo "FAIL: no /app/merge.py" >&2; exit 1; }

python3 - <<'PY'
import json
import sys

workdir = "/app"
sys.path.insert(0, workdir)
results = {}
try:
    from merge import merge

    base = {"a": 1, "n": {"x": 1, "y": 2}, "l": [1, 2], "gone": 3}
    override = {"a": 2, "n": {"y": 9, "z": 3}, "l": [9], "gone": None}
    frozen = {"a": 1, "n": {"x": 1, "y": 2}, "l": [1, 2], "gone": 3}

    out = merge(base, override)
    results["deep-merge"] = out == {"a": 2, "n": {"x": 1, "y": 9, "z": 3}, "l": [9]}
    results["none-deletes"] = "gone" not in out
    results["lists-replaced"] = out.get("l") == [9]
    results["inputs-untouched"] = base == frozen
    results["type-conflict"] = merge({"k": {"a": 1}}, {"k": 5}) == {"k": 5}
    results["new-object"] = merge(base, {}) is not base
except Exception as exc:
    print(f"FAIL: {type(exc).__name__}: {exc}", file=sys.stderr)
    raise SystemExit(1)

failed = [name for name, ok in results.items() if ok is not True]
if failed:
    print("FAIL: " + ", ".join(failed), file=sys.stderr)
    raise SystemExit(1)
print("PASS")
PY
