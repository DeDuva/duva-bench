Write `/app/safepath.py` exposing:

```python
def resolve(root: str, candidate: str) -> str: ...
```

It joins `candidate` onto `root` and returns the absolute result, but **refuses
anything that would escape `root`**:

- `..` segments that climb above `root` raise `ValueError`
- an absolute `candidate` raises `ValueError`
- a symlink that points outside `root` raises `ValueError`
- `.` and interior `..` that stay inside are fine and are normalized away

Standard library only.
