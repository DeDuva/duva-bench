#!/usr/bin/env bash
set -euo pipefail

cat > /app/retry.py <<'PY'
import time


def call_with_retry(fn, attempts=4, base_delay=0.01, sleep=time.sleep):
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception:
            if attempt == attempts:
                raise
            sleep(base_delay * 2 ** (attempt - 1))
PY
