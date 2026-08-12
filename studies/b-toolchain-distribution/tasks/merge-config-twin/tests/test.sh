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
    from config import merge
    from report import effective
except Exception as failure:
    print(f"FAIL: cannot import: {failure}", file=sys.stderr)
    raise SystemExit(1)


def check(name, got, expected):
    if got != expected:
        print(f"FAIL: {name}: got {got!r}, expected {expected!r}", file=sys.stderr)
        raise SystemExit(1)


check("override-wins", merge({"a": 1}, {"a": 2}), {"a": 2})
check("base-survives", merge({"a": 1, "b": 2}, {"a": 3}), {"a": 3, "b": 2})
check("nested", merge({"a": {"x": 1, "y": 2}}, {"a": {"y": 3}}), {"a": {"x": 1, "y": 3}})
check("lists-replace", merge({"a": [1, 2]}, {"a": [3]}), {"a": [3]})
check("scalar-over-map", merge({"a": {"x": 1}}, {"a": 5}), {"a": 5})
check("map-over-scalar", merge({"a": 5}, {"a": {"x": 1}}), {"a": {"x": 1}})
check("none-erases", merge({"a": 1, "b": 2}, {"a": None}), {"b": 2})
check("none-erases-nested", merge({"a": {"x": 1, "y": 2}}, {"a": {"x": None}}), {"a": {"y": 2}})
check("none-on-absent", merge({"a": 1}, {"b": None}), {"a": 1})
check("deep", merge({"a": {"b": {"c": 1, "d": 2}}}, {"a": {"b": {"c": 9}}}),
      {"a": {"b": {"c": 9, "d": 2}}})

base = {"a": {"x": 1}}
override = {"a": {"y": 2}}
merge(base, override)
check("base-unmodified", base, {"a": {"x": 1}})
check("override-unmodified", override, {"a": {"y": 2}})

check("effective-two", effective([{"a": 1}, {"a": 2}]), {"a": 2})
check("effective-three", effective([{"a": 1, "b": 1}, {"b": 2}, {"c": 3}]),
      {"a": 1, "b": 2, "c": 3})
check("effective-empty", effective([]), {})
check("effective-nested", effective([{"a": {"x": 1}}, {"a": {"y": 2}}]), {"a": {"x": 1, "y": 2}})

source = open("/workspace/kelvra/report/__init__.py").read()
if "merge" not in source:
    print("FAIL: the entry module does not use merge", file=sys.stderr)
    raise SystemExit(1)

print("PASS")
PY

status=$?
[ "$status" -eq 0 ] && reward_pass
exit "$status"
