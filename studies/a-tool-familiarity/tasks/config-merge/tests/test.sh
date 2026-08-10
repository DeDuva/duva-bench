#!/usr/bin/env bash
# Harbor's verifier: did the environment end up in the state the task asked for.
# Deliberately separate from duva-bench's grader, which answers "how well" under
# a different ADP identity.
set -uo pipefail


# Harbor 0.20.0 decides pass/fail by reading a reward file the verifier writes
# to /logs/verifier/reward.txt inside the container — a non-zero exit is NOT how
# it is signalled, and a verifier that only exits non-zero makes Harbor raise
# RewardFileNotFoundError and abandon the whole trial. Every task in this repo
# was written that way and none of them could run.

REWARD_FILE="${HARBOR_REWARD_FILE:-/logs/verifier/reward.txt}"
mkdir -p "$(dirname "$REWARD_FILE")"
# Fail closed: write 0 now, overwrite with 1 only if every check below passes.
# A verifier killed by its timeout then reports a failure rather than no answer.
printf '0' > "$REWARD_FILE"
reward_pass() { printf '1' > "$REWARD_FILE"; }

# Publish the work product so it survives the container.
#
# The grader runs on the host, after the container is gone, and is pointed at
# whatever Harbor collected into /logs/artifacts. The agent's file lives in
# /app, which is destroyed with the environment — so without this copy the
# grader sees an empty directory and scores every trial 0 "never written",
# while the verifier above says the task passed. That disagreement is not a
# finding about the agent; it is this line missing.
mkdir -p /logs/artifacts
cp -a "/app/merge.py" /logs/artifacts/ 2>/dev/null || true

test -f /app/merge.py || { echo "FAIL: no /app/merge.py" >&2; exit 1; }

python3 - <<'PY'
import json
import sys

workdir = "/app"
sys.path.insert(0, workdir)
results = {}
try:
    from merge import merge

    base = {"a": 1, "n": {"x": 1, "y": 2}, "l": [1, 2], "gone": 3}
    override = {"a": 2, "n": {"y": 9, "z": 3}, "l": [9], "gone": None}
    frozen = {"a": 1, "n": {"x": 1, "y": 2}, "l": [1, 2], "gone": 3}

    out = merge(base, override)
    results["deep-merge"] = out == {"a": 2, "n": {"x": 1, "y": 9, "z": 3}, "l": [9]}
    results["none-deletes"] = "gone" not in out
    results["lists-replaced"] = out.get("l") == [9]
    results["inputs-untouched"] = base == frozen
    results["type-conflict"] = merge({"k": {"a": 1}}, {"k": 5}) == {"k": 5}
    results["new-object"] = merge(base, {}) is not base
except Exception as exc:
    print(f"FAIL: {type(exc).__name__}: {exc}", file=sys.stderr)
    raise SystemExit(1)

failed = [name for name, ok in results.items() if ok is not True]
if failed:
    print("FAIL: " + ", ".join(failed), file=sys.stderr)
    raise SystemExit(1)
print("PASS")
PY

# The heredoc above exits non-zero when a check fails. Harbor reads the reward
# file, not the exit status, so translate one into the other explicitly — and
# keep exiting with the original status so a human reading job.log still sees it.
status=$?
[ "$status" -eq 0 ] && reward_pass
exit "$status"
