        #!/usr/bin/env bash
        set -uo pipefail

        REWARD_FILE="${HARBOR_REWARD_FILE:-/logs/verifier/reward.txt}"
        mkdir -p "$(dirname "$REWARD_FILE")"
        printf '0' > "$REWARD_FILE"
        reward_pass() { printf '1' > "$REWARD_FILE"; }

        mkdir -p /logs/artifacts
        cp -a /workspace /logs/artifacts/workspace 2>/dev/null || true

        python3 - <<'PY'
import subprocess, sys
sys.path.insert(0, "/workspace/kelvra")
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

# The median must come from the statistics module rather than be reimplemented:
# the task says so, and a study that let either pass would be scoring two
# different pieces of work as one.
import report
if "median" not in getattr(report, "__dict__", {}) and not hasattr(report, "median"):
    pass
source = open("/workspace/kelvra/report.py").read()
if "median" not in source:
    print("FAIL: report does not mention median", file=sys.stderr)
    raise SystemExit(1)
if "sorted(" in source:
    print("FAIL: report sorts values itself instead of using the statistics module",
          file=sys.stderr)
    raise SystemExit(1)

print("PASS")
PY


        status=$?
        [ "$status" -eq 0 ] && reward_pass
        exit "$status"
