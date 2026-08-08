#!/usr/bin/env bash
# Harbor's verifier: did the environment end up in the state the task asked for.
# Deliberately separate from duva-bench's grader, which answers "how well" under
# a different ADP identity.
set -uo pipefail

test -f /app/window.py || { echo "FAIL: no /app/window.py" >&2; exit 1; }

python3 - <<'PY'
import json
import sys

workdir = "/app"
sys.path.insert(0, workdir)
results = {}
try:
    from window import SlidingWindow

    limiter = SlidingWindow(limit=2, window_s=10.0)
    results["allows-under-limit"] = limiter.allow(0.0) and limiter.allow(1.0)
    results["blocks-at-limit"] = limiter.allow(2.0) is False
    results["allows-after-window"] = limiter.allow(11.5) is True

    # A blocked call must not be recorded, or the limiter would ratchet itself shut.
    fresh = SlidingWindow(limit=1, window_s=10.0)
    fresh.allow(0.0)
    fresh.allow(1.0)
    results["blocked-not-recorded"] = fresh.allow(10.5) is True

    trimmed = SlidingWindow(limit=2, window_s=1.0)
    for tick in range(200):
        trimmed.allow(tick * 1.0)
    held = getattr(trimmed, "_calls", None)
    results["window-is-trimmed"] = held is None or len(held) <= 2
except Exception as exc:
    print(f"FAIL: {type(exc).__name__}: {exc}", file=sys.stderr)
    raise SystemExit(1)

failed = [name for name, ok in results.items() if ok is not True]
if failed:
    print("FAIL: " + ", ".join(failed), file=sys.stderr)
    raise SystemExit(1)
print("PASS")
PY
