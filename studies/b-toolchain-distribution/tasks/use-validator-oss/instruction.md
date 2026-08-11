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

This is a standard Python project.

- Each package is a directory under `src/`.
- Tests are in `tests/`.
- Run the tests with `make test`.
