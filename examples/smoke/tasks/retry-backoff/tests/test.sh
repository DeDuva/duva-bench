#!/usr/bin/env bash
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
cp -a "/app/retry.py" /logs/artifacts/ 2>/dev/null || true

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

# The heredoc above exits non-zero when a check fails. Harbor reads the reward
# file, not the exit status, so translate one into the other explicitly — and
# keep exiting with the original status so a human reading job.log still sees it.
status=$?
[ "$status" -eq 0 ] && reward_pass
exit "$status"
