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
for root in ["/workspace/kelvra"]:
    sys.path.insert(0, root)
try:
    from report import summarize
except Exception as failure:
    print(f"FAIL: cannot import summarize: {failure}", file=sys.stderr)
    raise SystemExit(1)

cases = [
    ([2, 4, 6], {"count": 3, "mean": 4.0, "median": 4.0}),
    ([1, 2, 3, 4], {"count": 4, "mean": 2.5, "median": 2.5}),
    ([5], {"count": 1, "mean": 5.0, "median": 5.0}),
]
for readings, expected in cases:
    got = summarize(readings)
    if got != expected:
        print(f"FAIL: summarize({readings}) == {got}, expected {expected}", file=sys.stderr)
        raise SystemExit(1)

source = open("/workspace/kelvra/report/__init__.py").read()
if "median" not in source:
    print("FAIL: the entry module does not mention median", file=sys.stderr)
    raise SystemExit(1)
if "sorted(" in source:
    print("FAIL: the entry module sorts values itself instead of using the library",
          file=sys.stderr)
    raise SystemExit(1)

print("PASS")
PY

status=$?
[ "$status" -eq 0 ] && reward_pass
exit "$status"
