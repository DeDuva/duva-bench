`summarize` currently accepts anything. It must reject a series that holds a
non-number.

Use the `numeric` function from the **validate** package: call it on the
readings before summarizing, and let the `NotNumeric` it raises propagate. Do
not write your own type check, and do not catch and re-raise.

`validate` is part of this project but the summarizing package does not yet use
it, so you will need to make it reachable as well as import it — the way this
project's toolchain expects.

Then extend the existing test so it covers a rejected series, and make the whole
test suite pass.

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
