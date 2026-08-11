Readings arrive in a stream and have to be summarised over a sliding window.

Implement `windows(values, size, step)` in the **window** package. It returns a
list of lists: each is a consecutive run of `size` values, advancing by `step`.

Rules, all tested:

- Only **complete** windows are returned; a trailing partial window is dropped.
- `step` may be smaller than `size`, so windows overlap.
- `step` may be larger than `size`, so values are skipped.
- A `size` larger than the series returns an empty list.
- `size` or `step` below 1 raises `ValueError`.

Then make `rolling_mean(values, size, step)` in the reporting package return the
mean of each window, using `windows` and the existing `mean`. `window` is part
of this project but the reporting package does not yet reach it.

Extend the tests, and make the suite pass.

## Working here

This is a monorepo. Code lives under `depot/`, and every directory that produces
something has a `BUILD` file declaring its targets.

- A target is named by its path from the depot root: `//depot/stats:stats`.
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
