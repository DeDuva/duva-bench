The test suite fails. `summarize` reports a `spread` that is wrong for some
series: `spread([1, 2])` should be `0.5` and comes back `0`.

Find the cause and fix it. The reported value must be exact, not truncated.

**Do not change the test's expectations** — the test is right and the code is
wrong. Make the suite pass by fixing the defect.

## Working here

This is a standard Python project.

- Each package is a directory under `src/`.
- Tests are in `tests/`.
- Run the tests with `make test`.
