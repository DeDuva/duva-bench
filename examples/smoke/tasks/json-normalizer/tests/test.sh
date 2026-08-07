#!/usr/bin/env bash
# Harbor's verifier. Deliberately separate from duva-bench's grader: this one
# answers "did the environment end up in the state the task asked for", and the
# grader answers "how well", under a different ADP identity.
set -uo pipefail

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

echo PASS
