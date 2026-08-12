Configuration comes from several layers and has to be merged.

Implement `merge(base, override)` in the **config** package. It returns a new
mapping and must not modify either argument.

Rules, all tested:

- A key in `override` wins.
- When **both** values are mappings, merge them recursively.
- When either value is not a mapping, the override's value replaces the base's
  outright — **lists replace, they do not concatenate**.
- An override value of `None` **removes** the key from the result.
- Keys only in `base` survive untouched.

Then make `effective(layers)` in the reporting package fold a list of layers
left to right with `merge`, so later layers win. `config` is part of this project
but the reporting package does not yet reach it.

Extend the tests, and make the suite pass.

## Working here

This is a standard Python project.

- Each package is a directory under `src/`.
- A package's module is imported by its own name: the code in `src/stats/` is
  reached with `from stats import ...`, not `from stats.stats import ...`.
- Tests are in `tests/`.
- Run the tests with `make test`.
