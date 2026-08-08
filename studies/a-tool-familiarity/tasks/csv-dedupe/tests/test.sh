#!/usr/bin/env bash
# Harbor's verifier: did the environment end up in the state the task asked for.
# Deliberately separate from duva-bench's grader, which answers "how well" under
# a different ADP identity.
set -uo pipefail

test -f /app/dedupe.py || { echo "FAIL: no /app/dedupe.py" >&2; exit 1; }

python3 - <<'PY'
import json
import sys

workdir = "/app"
sys.path.insert(0, workdir)
results = {}
try:
    import os
    import subprocess
    import sys

    INPUT = "id,name\n1,a\n2,b\n1,c\n3,d\n2,e\n"


    def run(args, text):
        return subprocess.run(
            [sys.executable, os.path.join(workdir, "dedupe.py"), *args],
            input=text,
            capture_output=True,
            text=True,
            timeout=20,
        )


    done = run(["id"], INPUT)
    results["keeps-last"] = done.stdout.replace("\r\n", "\n") == "id,name\n1,c\n2,e\n3,d\n"
    results["exit-zero"] = done.returncode == 0

    missing = run(["nope"], INPUT)
    results["missing-column-exits-2"] = missing.returncode == 2
    results["missing-column-clean-stdout"] = missing.stdout == ""

    empty = run(["id"], "id,name\n")
    results["header-only"] = empty.returncode == 0 and empty.stdout.strip() == "id,name"
except Exception as exc:
    print(f"FAIL: {type(exc).__name__}: {exc}", file=sys.stderr)
    raise SystemExit(1)

failed = [name for name, ok in results.items() if ok is not True]
if failed:
    print("FAIL: " + ", ".join(failed), file=sys.stderr)
    raise SystemExit(1)
print("PASS")
PY
