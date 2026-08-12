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
for root in ["/workspace/fiz"]:
    sys.path.insert(0, root)
try:
    from report import summarize
    from validate import NotNumeric
except Exception as failure:
    print(f"FAIL: cannot import: {failure}", file=sys.stderr)
    raise SystemExit(1)

if summarize([2, 4, 6]) != {"count": 3, "mean": 4.0}:
    print("FAIL: a valid series no longer summarizes correctly", file=sys.stderr)
    raise SystemExit(1)

# The rejection has to be the validator's exception, not a home-grown one: the
# task names the function to use, and an arm that reimplemented the check would
# have done different work from an arm that found the package.
for bad in (["x", 1], [1, None], [1, True]):
    try:
        summarize(bad)
    except NotNumeric:
        continue
    except Exception as other:
        print(f"FAIL: summarize({bad}) raised {type(other).__name__}, not NotNumeric",
              file=sys.stderr)
        raise SystemExit(1)
    print(f"FAIL: summarize({bad}) was accepted", file=sys.stderr)
    raise SystemExit(1)

source = open("/workspace/fiz/report/__init__.py").read()
if "numeric" not in source:
    print("FAIL: the entry module does not call the validator", file=sys.stderr)
    raise SystemExit(1)
for home_grown in ("isinstance", "TypeError"):
    if home_grown in source:
        print(f"FAIL: the entry module does its own checking ({home_grown})", file=sys.stderr)
        raise SystemExit(1)

print("PASS")
PY

status=$?
[ "$status" -eq 0 ] && reward_pass
exit "$status"
