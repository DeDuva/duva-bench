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
for root in ["/workspace/src"]:
    sys.path.insert(0, root)
try:
    import graph
    from report import plan_build
except Exception as failure:
    print(f"FAIL: cannot import: {failure}", file=sys.stderr)
    raise SystemExit(1)


def check(name, got, expected):
    if got != expected:
        print(f"FAIL: {name}: got {got!r}, expected {expected!r}", file=sys.stderr)
        raise SystemExit(1)


check("empty", plan_build({}), [])
check("chain", plan_build({"a": ["b"], "b": []}), ["b", "a"])
check("ties", plan_build({"b": [], "a": [], "c": []}), ["a", "b", "c"])
check("diamond", plan_build({"d": ["b", "c"], "b": ["a"], "c": ["a"], "a": []}),
      ["a", "b", "c", "d"])
check("implicit", plan_build({"a": ["b"]}), ["b", "a"])
check("ready-first", plan_build({"z": [], "y": ["z"], "x": []}), ["x", "z", "y"])

for name, bad, expected in (
    ("self-edge", {"a": ["a"]}, ["a"]),
    ("two-cycle", {"a": ["b"], "b": ["a"]}, ["a", "b"]),
    # `d` depends on the cycle and is not on it. This case is here because the
    # first version of this task demanded `d`, an agent answered without it and
    # was right, and the check scored a correct answer as a failure.
    ("cycle-with-tail", {"a": ["b"], "b": ["c"], "c": ["a"], "d": ["a"]}, ["a", "b", "c"]),
    ("two-disjoint-cycles", {"a": ["b"], "b": ["a"], "c": ["d"], "d": ["c"]},
     ["a", "b", "c", "d"]),
):
    try:
        plan_build(bad)
    except graph.Cycle as cycle:
        if list(cycle.members) != expected:
            print(f"FAIL: {name}: members {list(cycle.members)!r}, expected {expected!r}",
                  file=sys.stderr)
            raise SystemExit(1)
    except Exception as other:
        print(f"FAIL: {name} raised {type(other).__name__}, not graph.Cycle", file=sys.stderr)
        raise SystemExit(1)
    else:
        print(f"FAIL: {name} was accepted", file=sys.stderr)
        raise SystemExit(1)

source = open("/workspace/src/report/__init__.py").read()
if "resolve" not in source:
    print("FAIL: the entry module does not use resolve", file=sys.stderr)
    raise SystemExit(1)

print("PASS")
PY

status=$?
[ "$status" -eq 0 ] && reward_pass
exit "$status"
