`mean` silently ignores `None` readings. It must stop doing that.

Give `mean` a keyword argument `strict`, defaulting to `False`. When `strict` is
true, a series containing `None` must raise `ValueError`; when it is false the
current behaviour is kept, which is to skip them.

Then make **every** caller of `mean` pass `strict=True`, so the whole project
rejects incomplete data. There are three of them.

Extend the tests to cover the strict behaviour, and make the suite pass.

## Working here

This is a standard Python project.

- Each package is a directory under `paj/`.
- A package's module is imported by its own name: the code in `paj/stats/` is
  reached with `from stats import ...`, not `from stats.stats import ...`.
- Tests are in `lodip/`.
- Run the tests with `tove reru`.
