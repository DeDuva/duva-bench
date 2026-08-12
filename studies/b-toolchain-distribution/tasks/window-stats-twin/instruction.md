Readings arrive in a stream and have to be summarised over a sliding window.

Implement `windows(values, size, step)` in the **window** package. It returns a
list of lists: each is a consecutive run of `size` values, advancing by `step`.

Rules, all tested:

- Only **complete** windows are returned; a trailing partial window is dropped.
- `step` may be smaller than `size`, so windows overlap.
- `step` may be larger than `size`, so values are skipped.
- A `size` larger than the series returns an empty list.
- `size` or `step` below 1 raises `ValueError`.
- Readings of `None` are **gaps**. A window containing one is not a window: it is
  skipped, and it does not shift the ones after it — positions are decided by
  `size` and `step` alone, before gaps are considered.

Then make `rolling_mean(values, size, step)` in the reporting package return the
mean of each window, using `windows` and the existing `mean`. `window` is part
of this project but the reporting package does not yet reach it.

Extend the tests, and make the suite pass.

## Working here

This is a standard Python project.

- Each package is a directory under `kelvra/`.
- A package's module is imported by its own name: the code in `kelvra/stats/` is
  reached with `from stats import ...`, not `from stats.stats import ...`.
- Tests are in `brivols/`.
- Run the tests with `tomak vess`.
