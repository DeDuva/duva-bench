`summarize` reports a count and a mean. It also needs a **median**.

Add a `median` key to the dictionary `summarize` returns, computed by the
`median` function that already exists in the statistics module — do not
reimplement it. Then extend the existing test so it covers the new key, and make
the whole test suite pass.

The median of an even-length series is the mean of its two middle values.

## Working here

This is a monorepo. Code lives under `depot/`, and every directory that produces
something has a `BUILD` file declaring its targets.

- A target is named by its path from the depot root: `//depot/stats:stats`.
- A target that uses another must **declare it** in its `deps`. A build with an
  undeclared dependency fails even if the import would work.
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
