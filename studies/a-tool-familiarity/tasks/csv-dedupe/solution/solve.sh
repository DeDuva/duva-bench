#!/usr/bin/env bash
# Harbor's oracle: proves the task and its verifier agree, so a failing
# arm is a failing arm rather than a broken task.
set -euo pipefail

cat > /app/dedupe.py <<'PY'
import csv
import sys

key = sys.argv[1]
reader = csv.DictReader(sys.stdin)
if reader.fieldnames is None or key not in reader.fieldnames:
    print(f"no column {key!r}", file=sys.stderr)
    raise SystemExit(2)

order = []
rows = {}
for row in reader:
    value = row[key]
    if value not in rows:
        order.append(value)
    rows[value] = row

writer = csv.DictWriter(sys.stdout, fieldnames=reader.fieldnames)
writer.writeheader()
for value in order:
    writer.writerow(rows[value])
PY
