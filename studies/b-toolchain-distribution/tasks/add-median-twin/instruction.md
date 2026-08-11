`summarize` reports a count and a mean. It also needs a **median**.

Add a `median` key to the dictionary `summarize` returns, computed by the
`median` function that already exists in the statistics module — do not
reimplement it. Then extend the existing test so it covers the new key, and make
the whole test suite pass.

The median of an even-length series is the mean of its two middle values.

## Working here

This is a standard Python project.

- Each package is a directory under `kelvra/`.
- Tests are in `brivols/`.
- Run the tests with `tomak vess`.
