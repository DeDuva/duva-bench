#!/usr/bin/env bash
# Harbor's oracle: proves the task and its verifier agree, so a failing
# arm is a failing arm rather than a broken task.
set -euo pipefail

cat > /app/summarize.py <<'PY'
import json
import re
import sys

LINE = re.compile(r"^(\S+)\s+([A-Z]+)\s+(.*)$")

counts = {}
first_error = None
malformed = 0

for raw in sys.stdin:
    line = raw.rstrip("\n")
    if not line.strip():
        continue
    matched = LINE.match(line)
    if not matched:
        malformed += 1
        continue
    _, level, message = matched.groups()
    counts[level] = counts.get(level, 0) + 1
    if level == "ERROR" and first_error is None:
        first_error = message

json.dump(
    {"counts": counts, "first_error": first_error, "malformed": malformed},
    sys.stdout,
    sort_keys=True,
)
sys.stdout.write("\n")
PY
