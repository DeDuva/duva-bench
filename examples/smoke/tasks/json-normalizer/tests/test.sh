#!/usr/bin/env bash
# Harbor's verifier. Deliberately separate from duva-bench's grader: this one
# answers "did the environment end up in the state the task asked for", and the
# grader answers "how well", under a different ADP identity.
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
cp -a "/app/normalize.py" /logs/artifacts/ 2>/dev/null || true

fail() { echo "FAIL: $*" >&2; exit 1; }

test -f /app/normalize.py || fail "no /app/normalize.py"

out=$(printf '{"b":1,"a":{"d":2,"c":3}}' | python3 /app/normalize.py) || fail "normalize.py exited non-zero"
expected='{
  "a": {
    "c": 3,
    "d": 2
  },
  "b": 1
}'
[ "$out" = "$expected" ] || fail "unexpected output: $out"

printf 'not json' | python3 /app/normalize.py >/dev/null 2>&1
[ $? -eq 2 ] || fail "invalid input did not exit 2"

reward_pass

echo PASS
