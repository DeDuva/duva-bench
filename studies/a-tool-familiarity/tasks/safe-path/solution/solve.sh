#!/usr/bin/env bash
# Harbor's oracle: proves the task and its verifier agree, so a failing
# arm is a failing arm rather than a broken task.
set -euo pipefail

cat > /app/safepath.py <<'PY'
import os


def resolve(root, candidate):
    if os.path.isabs(candidate):
        raise ValueError("candidate must be relative")
    base = os.path.realpath(root)
    target = os.path.realpath(os.path.join(base, candidate))
    if target != base and not target.startswith(base + os.sep):
        raise ValueError(f"{candidate!r} escapes {root!r}")
    return target
PY
