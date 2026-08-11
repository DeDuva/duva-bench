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
for root in ["/workspace/src/stats", "/workspace/src/window", "/workspace/src/report"]:
    sys.path.insert(0, root)
try:
    from report import rolling_mean
    from window import windows
except Exception as failure:
    print(f"FAIL: cannot import: {failure}", file=sys.stderr)
    raise SystemExit(1)


def check(name, got, expected):
    if got != expected:
        print(f"FAIL: {name}: got {got!r}, expected {expected!r}", file=sys.stderr)
        raise SystemExit(1)


check("adjacent", windows([1, 2, 3, 4], 2, 2), [[1, 2], [3, 4]])
check("partial-dropped", windows([1, 2, 3, 4, 5], 2, 2), [[1, 2], [3, 4]])
check("overlapping", windows([1, 2, 3, 4], 2, 1), [[1, 2], [2, 3], [3, 4]])
check("skipping", windows([1, 2, 3, 4, 5, 6], 2, 3), [[1, 2], [4, 5]])
check("size-exceeds", windows([1, 2], 3, 1), [])
check("exact-fit", windows([1, 2, 3], 3, 1), [[1, 2, 3]])
check("empty", windows([], 1, 1), [])

for size, step in ((0, 1), (1, 0), (-1, 1), (1, -2)):
    try:
        windows([1, 2, 3], size, step)
    except ValueError:
        pass
    except Exception as other:
        print(f"FAIL: windows(size={size}, step={step}) raised {type(other).__name__}",
              file=sys.stderr)
        raise SystemExit(1)
    else:
        print(f"FAIL: windows(size={size}, step={step}) was accepted", file=sys.stderr)
        raise SystemExit(1)

check("rolling-adjacent", rolling_mean([1, 2, 3, 4], 2, 2), [1.5, 3.5])
check("rolling-overlap", rolling_mean([1, 2, 3, 4], 2, 1), [1.5, 2.5, 3.5])
check("rolling-partial", rolling_mean([1, 2, 3, 4, 5], 2, 2), [1.5, 3.5])
check("rolling-none", rolling_mean([1], 2, 1), [])

source = open("/workspace/src/report/report.py").read()
if "windows" not in source:
    print("FAIL: the entry module does not use windows", file=sys.stderr)
    raise SystemExit(1)

print("PASS")
PY

status=$?
[ "$status" -eq 0 ] && reward_pass
exit "$status"
