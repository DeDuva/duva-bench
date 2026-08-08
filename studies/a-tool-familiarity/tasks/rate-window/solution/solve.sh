#!/usr/bin/env bash
# Harbor's oracle: proves the task and its verifier agree, so a failing
# arm is a failing arm rather than a broken task.
set -euo pipefail

cat > /app/window.py <<'PY'
from collections import deque


class SlidingWindow:
    def __init__(self, limit, window_s):
        self.limit = limit
        self.window_s = window_s
        self._calls = deque()

    def allow(self, now):
        while self._calls and self._calls[0] <= now - self.window_s:
            self._calls.popleft()
        if len(self._calls) >= self.limit:
            return False
        self._calls.append(now)
        return True
PY
