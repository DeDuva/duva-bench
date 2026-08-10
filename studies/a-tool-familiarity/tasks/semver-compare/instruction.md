Write `/app/semver.py` exposing:

```python
def compare(left: str, right: str) -> int: ...
```

It returns `-1`, `0` or `1` for semantic versions, following semver 2.0 ordering:

- numeric identifiers compare numerically, so `1.0.10 > 1.0.9`
- a pre-release version is **lower** than the release it precedes: `1.0.0-rc.1 < 1.0.0`
- pre-release identifiers compare left to right; numeric ones are lower than
  alphanumeric ones
- build metadata (`+sha.1`) is ignored entirely

Raise `ValueError` on something that is not a version. Standard library only.
