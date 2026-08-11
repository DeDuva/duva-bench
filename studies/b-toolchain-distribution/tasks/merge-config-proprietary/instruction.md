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
