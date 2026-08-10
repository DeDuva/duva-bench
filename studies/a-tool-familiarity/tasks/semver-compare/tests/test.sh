#!/usr/bin/env bash
# Harbor's verifier: did the environment end up in the state the task asked for.
# Deliberately separate from duva-bench's grader, which answers "how well" under
# a different ADP identity.
set -uo pipefail

test -f /app/semver.py || { echo "FAIL: no /app/semver.py" >&2; exit 1; }

python3 - <<'PY'
import json
import sys

workdir = "/app"
sys.path.insert(0, workdir)
results = {}
try:
    from semver import compare

    results["numeric-identifiers"] = compare("1.0.10", "1.0.9") == 1
    results["equality"] = compare("2.3.4", "2.3.4") == 0
    results["prerelease-is-lower"] = compare("1.0.0-rc.1", "1.0.0") == -1
    results["prerelease-ordering"] = compare("1.0.0-alpha.1", "1.0.0-alpha.2") == -1
    results["numeric-before-alpha"] = compare("1.0.0-1", "1.0.0-alpha") == -1
    results["build-ignored"] = compare("1.0.0+aaa", "1.0.0+bbb") == 0
    try:
        compare("not-a-version", "1.0.0")
        results["rejects-nonsense"] = False
    except ValueError:
        results["rejects-nonsense"] = True
    except Exception:
        results["rejects-nonsense"] = False
except Exception as exc:
    print(f"FAIL: {type(exc).__name__}: {exc}", file=sys.stderr)
    raise SystemExit(1)

failed = [name for name, ok in results.items() if ok is not True]
if failed:
    print("FAIL: " + ", ".join(failed), file=sys.stderr)
    raise SystemExit(1)
print("PASS")
PY
