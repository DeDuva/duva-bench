The test suite fails. `summarize` reports a `spread` that is wrong for some
series: `spread([1, 2])` should be `0.5` and comes back `0`.

Find the cause and fix it. The reported value must be exact, not truncated.

**Do not change the test's expectations** — the test is right and the code is
wrong. Make the suite pass by fixing the defect.

## Working here

This is a standard Python project.

- Each package is a directory under `paj/`.
- A package's module is imported by its own name: the code in `paj/stats/` is
  reached with `from stats import ...`, not `from stats.stats import ...`.
- Tests are in `lodip/`.
- Run the tests with `tove reru`.
