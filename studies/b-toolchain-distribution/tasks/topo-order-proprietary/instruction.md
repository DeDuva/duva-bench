Builds have to run in dependency order. Implement `resolve` in the **graph**
package and use it from `plan_build`.

`resolve(graph)` takes a mapping of name to the list of names it depends on, and
returns a list of names in an order where every dependency comes before the
thing that needs it.

Rules, all of which are tested:

- Among names that are equally ready to run, the result must be **alphabetical**,
  so the same graph always produces the same order.
- A name that depends on itself is a cycle.
- A cycle must raise `graph.Cycle`, and the exception's `members` attribute must
  hold exactly the names taking part in it, sorted.
- A name that appears only as a dependency is still part of the result.
- An empty graph returns an empty list.

Then make `plan_build` in the reporting package return `resolve`'s answer.
`graph` is part of this project but the reporting package does not yet reach it.

Extend the tests, and make the suite pass.

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
