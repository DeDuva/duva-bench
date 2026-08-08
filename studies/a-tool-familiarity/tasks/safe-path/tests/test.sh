#!/usr/bin/env bash
# Harbor's verifier: did the environment end up in the state the task asked for.
# Deliberately separate from duva-bench's grader, which answers "how well" under
# a different ADP identity.
set -uo pipefail

test -f /app/safepath.py || { echo "FAIL: no /app/safepath.py" >&2; exit 1; }

python3 - <<'PY'
import json
import sys

workdir = "/app"
sys.path.insert(0, workdir)
results = {}
try:
    import os
    import tempfile

    from safepath import resolve

    root = tempfile.mkdtemp()
    os.makedirs(os.path.join(root, "inner"), exist_ok=True)
    outside = tempfile.mkdtemp()
    os.symlink(outside, os.path.join(root, "link"))


    def refuses(candidate):
        try:
            resolve(root, candidate)
        except ValueError:
            return True
        except Exception:
            return False
        return False


    results["joins-inside"] = resolve(root, "inner/file.txt") == os.path.join(
        os.path.realpath(root), "inner", "file.txt"
    )
    results["normalizes"] = resolve(root, "inner/../inner/./x") == os.path.join(
        os.path.realpath(root), "inner", "x"
    )
    results["refuses-climbing"] = refuses("../etc/passwd")
    results["refuses-absolute"] = refuses("/etc/passwd")
    results["refuses-symlink-escape"] = refuses("link/secret")
except Exception as exc:
    print(f"FAIL: {type(exc).__name__}: {exc}", file=sys.stderr)
    raise SystemExit(1)

failed = [name for name, ok in results.items() if ok is not True]
if failed:
    print("FAIL: " + ", ".join(failed), file=sys.stderr)
    raise SystemExit(1)
print("PASS")
PY
