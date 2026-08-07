Write `/app/retry.py` exposing a single function:

```python
def call_with_retry(fn, attempts=4, base_delay=0.01, sleep=time.sleep): ...
```

It calls `fn()` and returns its result. If `fn()` raises, it retries until it has
made `attempts` calls in total, sleeping `base_delay * 2 ** (n - 1)` seconds
before the nth retry via the injected `sleep`. If every attempt raises, the last
exception propagates.

`sleep` is a parameter so the behaviour is testable without waiting. Do not
import anything outside the standard library.
