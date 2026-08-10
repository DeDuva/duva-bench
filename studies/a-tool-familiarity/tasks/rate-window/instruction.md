Write `/app/window.py` exposing:

```python
class SlidingWindow:
    def __init__(self, limit: int, window_s: float): ...
    def allow(self, now: float) -> bool: ...
```

A sliding-window rate limiter. `allow(now)` returns True and records the call if
fewer than `limit` calls were recorded in the half-open interval
`(now - window_s, now]`; otherwise it returns False and records nothing.

Time is passed in rather than read, so the behaviour is testable without waiting.
Old entries must not accumulate: after a call, the window holds at most `limit`
timestamps. Standard library only.
