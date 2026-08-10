#!/usr/bin/env bash
# Harbor's oracle solution. Its only job is to prove the task and its verifier
# agree with each other, so a failing arm is a failing arm and not a broken task.
set -euo pipefail

cat > /app/normalize.py <<'PY'
import json
import sys

try:
    document = json.load(sys.stdin)
except json.JSONDecodeError:
    print("invalid json", file=sys.stderr)
    raise SystemExit(2)

json.dump(document, sys.stdout, sort_keys=True, indent=2, ensure_ascii=False)
sys.stdout.write("\n")
PY
