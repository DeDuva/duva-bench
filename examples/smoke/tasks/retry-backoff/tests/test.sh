#!/usr/bin/env bash
set -uo pipefail

test -f /app/retry.py || { echo "FAIL: no /app/retry.py" >&2; exit 1; }

python3 - <<'PY'
import sys

sys.path.insert(0, "/app")
from retry import call_with_retry

slept = []
calls = {"n": 0}


def flaky():
    calls["n"] += 1
    if calls["n"] < 3:
        raise RuntimeError("boom")
    return "ok"


assert call_with_retry(flaky, attempts=4, base_delay=0.01, sleep=slept.append) == "ok"
assert calls["n"] == 3, calls
assert slept == [0.01, 0.02], slept


def always():
    raise ValueError("never")


try:
    call_with_retry(always, attempts=2, base_delay=0.01, sleep=lambda _: None)
except ValueError:
    pass
else:
    raise AssertionError("a permanently failing call did not propagate")

print("PASS")
PY
