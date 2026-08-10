Write `/app/merge.py` exposing:

```python
def merge(base: dict, override: dict) -> dict: ...
```

It deep-merges `override` into `base` and returns a **new** dict, leaving both
arguments unmodified.

- Where both sides hold a dict, merge recursively.
- Where they disagree in type, or either side is not a dict, `override` wins.
- A value of `None` in `override` **deletes** the key from the result.
- Lists are replaced, never concatenated.

Standard library only.
