#!/usr/bin/env bash
# Harbor's verifier: did the environment end up in the state the task asked for.
# Deliberately separate from duva-bench's grader, which answers "how well" under
# a different ADP identity.
set -uo pipefail

test -f /app/summarize.py || { echo "FAIL: no /app/summarize.py" >&2; exit 1; }

python3 - <<'PY'
import json
import sys

workdir = "/app"
sys.path.insert(0, workdir)
results = {}
try:
    import json
    import os
    import subprocess
    import sys

    LOG = (
        "2026-08-07T10:00:00Z INFO starting\n"
        "2026-08-07T10:00:01Z ERROR db unreachable\n"
        "garbage line\n"
        "2026-08-07T10:00:02Z ERROR second failure\n"
        "2026-08-07T10:00:03Z INFO recovered\n"
    )


    def run(text):
        return subprocess.run(
            [sys.executable, os.path.join(workdir, "summarize.py")],
            input=text,
            capture_output=True,
            text=True,
            timeout=20,
        )


    done = run(LOG)
    try:
        parsed = json.loads(done.stdout)
    except Exception:
        parsed = {}

    results["counts"] = parsed.get("counts") == {"INFO": 2, "ERROR": 2}
    results["first-error"] = parsed.get("first_error") == "db unreachable"
    results["malformed-counted"] = parsed.get("malformed") == 1

    empty = run("")
    try:
        parsed_empty = json.loads(empty.stdout)
    except Exception:
        parsed_empty = {}
    results["empty-input"] = parsed_empty == {"counts": {}, "first_error": None, "malformed": 0}
    results["trailing-newline"] = done.stdout.endswith("\n")
except Exception as exc:
    print(f"FAIL: {type(exc).__name__}: {exc}", file=sys.stderr)
    raise SystemExit(1)

failed = [name for name, ok in results.items() if ok is not True]
if failed:
    print("FAIL: " + ", ".join(failed), file=sys.stderr)
    raise SystemExit(1)
print("PASS")
PY
