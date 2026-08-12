`mean` silently ignores `None` readings. It must stop doing that.

Give `mean` a keyword argument `strict`, defaulting to `False`. When `strict` is
true, a series containing `None` must raise `ValueError`; when it is false the
current behaviour is kept, which is to skip them.

Then make **every** caller of `mean` pass `strict=True`, so the whole project
rejects incomplete data. There are three of them.

Extend the tests to cover the strict behaviour, and make the suite pass.

## Working here

This is a monorepo. Code lives under `depot/`, and every directory that produces
something has a `BUILD` file declaring its targets.

- A target is named by its path from the depot root: `//depot/stats:stats`.
- A package's module is imported by its own name: the code in `depot/stats/` is
  reached with `from stats import ...`, not `from depot.stats import ...`.
- A target that uses another must **declare it** in that target's `deps`. A
  build with an undeclared dependency fails even if the import would work.
- Build and test with the depot's driver:

  ```
  dbuild test //depot/report:report_test
  ```

- Before a change counts as landed it must pass presubmit:

  ```
  dbuild presubmit
  ```

  Presubmit builds and tests every target in the depot and rejects any target
  whose dependencies are not declared.
