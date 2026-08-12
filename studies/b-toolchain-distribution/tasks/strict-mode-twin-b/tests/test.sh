#!/usr/bin/env bash
set -uo pipefail

REWARD_FILE="${HARBOR_REWARD_FILE:-/logs/verifier/reward.txt}"
mkdir -p "$(dirname "$REWARD_FILE")"
printf '0' > "$REWARD_FILE"
reward_pass() { printf '1' > "$REWARD_FILE"; }

mkdir -p /logs/artifacts
cp -a /workspace /logs/artifacts/workspace 2>/dev/null || true

python3 - <<'PY'
import sys
for root in ["/workspace/paj"]:
    sys.path.insert(0, root)
try:
    import stats
    from report import average_of_averages, summarize
except Exception as failure:
    print(f"FAIL: cannot import: {failure}", file=sys.stderr)
    raise SystemExit(1)

# The default has to be unchanged, or every existing caller's behaviour moved.
if stats.mean([1, None, 3]) != 2.0:
    print("FAIL: the non-strict default no longer skips gaps", file=sys.stderr)
    raise SystemExit(1)

try:
    stats.mean([1, None, 3], strict=True)
except ValueError:
    pass
else:
    print("FAIL: strict=True accepted a series holding None", file=sys.stderr)
    raise SystemExit(1)

if summarize([2, 4, 6]) != {"count": 3, "mean": 4.0}:
    print("FAIL: summarize no longer works on a clean series", file=sys.stderr)
    raise SystemExit(1)
if average_of_averages([[1, 2], [3, 4]]) != 2.5:
    print("FAIL: average_of_averages no longer works", file=sys.stderr)
    raise SystemExit(1)

# Three call sites, all of which have to pass it. Counted rather than inspected,
# because how a caller is written is not what this task is about.
source = open("/workspace/paj/report/__init__.py").read()
if source.count("strict=True") < 3:
    print(f"FAIL: {source.count('strict=True')} call sites pass strict=True, expected 3",
          file=sys.stderr)
    raise SystemExit(1)

print("PASS")
PY

status=$?
[ "$status" -eq 0 ] && reward_pass
exit "$status"
