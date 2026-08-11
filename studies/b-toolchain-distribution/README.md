# Study B — in-distribution toolchains vs. a proprietary-style stack

The design, the hypotheses, the prior art and the threats to validity are in
[`docs/studies/b-toolchain-distribution.md`](../../docs/studies/b-toolchain-distribution.md).
This directory is the instrument. **Nothing here has been executed against a model.**

## What is built

One problem — `summarize` must gain a median it takes from the statistics module
rather than reimplementing — posed in three toolchains:

| variant | the toolchain | what it is for |
|---|---|---|
| `add-median-oss` | `src/`, `tests/`, `pytest`, a `Makefile` | in-distribution: what a model has read a million times |
| `add-median-twin` | identical behaviour, every user-visible name changed (`kelvra/`, `brivols/`, `tomak vess`) | **the control** |
| `add-median-proprietary` | a `depot/` monorepo, `BUILD` files with declared deps, `//depot/pkg:target` labels, `dbuild`, a presubmit gate | out of distribution by structure *and* name |

The source files, the assertions and the acceptance criteria are shared. Only the
toolchain around them differs, because a variant that is harder in *substance*
would make the study measure difficulty instead of familiarity.

## The twin is the point

`add-median-proprietary` underperforming `add-median-oss` would prove very little
on its own: a monorepo with declared dependencies and a presubmit gate is more
work, not just less familiar. `add-median-twin` separates the two. It is the
`oss` variant with the names changed and nothing else, so:

- twin ≈ oss → the deficit on `proprietary` is **structural**;
- twin ≪ oss → a large part of it is **names**.

Reporting the twin is not optional. It is what makes any claim about familiarity
a claim rather than an assertion.

## What is verified, and what is not

Verified, and re-checkable by `pytest -m harbor`:

- all three images build, and **all three variants are solved by their own
  oracle** through Harbor (`tests/test_tasks_through_harbor.py`), which is the
  admission criterion: an arm whose task is broken would report the
  instrument's failures as the agent's;
- the depot's declaration rule **actually bites** — a target whose dependency is
  undeclared fails even though the bare import would work
  (`tests/test_study_b_dbuild.py`). Without that, the `proprietary` arm would be
  the `oss` arm with extra typing.

Not verified: anything about an agent. No model has run these tasks.

## `dbuild` is a reconstruction

Not Blaze, and deliberately not Bazel: Bazel is public and therefore itself in
distribution, which would blunt the contrast, and a real Bazel image is a large
download. `dbuild` implements only what these tasks exercise — resolve a target,
follow declared dependencies, run tests, gate on presubmit — from the conventions
described in Potvin and Levenberg (CACM 2016). **That it is a reconstruction is
the study's central limitation** and belongs in any write-up's abstract, not a
footnote.

## Regenerating

```sh
python3 studies/b-toolchain-distribution/generate.py
```

The three variants are generated from one source of truth so they cannot drift
apart. Edit `generate.py`, never a task directory.

## The first model run, 2026-08-10 — this task saturates

Before building more tasks, all three variants were run once with a real agent
(`terminus-2`, `claude-sonnet-4-5`), because the session that produced this
directory had already learned that a path nobody has executed is a path that does
not work. It cost **$0.21** in total and it found something worth knowing.

| variant | outcome | steps | tokens in/out | cost |
|---|---|---|---|---|
| `add-median-oss` | **solved** | 18 | 53,879 / 2,924 | $0.0822 |
| `add-median-proprietary` | **solved** | 17 | 51,449 / 2,717 | $0.0771 |
| `add-median-twin` | **solved** | 8 | 17,867 / 1,980 | $0.0512 |

Two readings, and the second is the important one.

**The instrument works.** Every variant is solvable by an agent, not just by its
oracle, so no arm's failures will be the instrument's. That is what this run was
for.

**The task is at ceiling, so it cannot measure anything.** All three solved on
the first attempt. A task every arm passes has no headroom for a familiarity
effect to appear in, and the outcome axis would be constant across the
factorial. The cost column is not a finding either — n=1 per arm, and the *twin*
happened to be cheapest, which is a good demonstration of why a noise floor has
to be reported before any contrast is read.

**So `add-median` is a smoke task, not a study task.** It stays, because a
cheap end-to-end task that every arm passes is exactly what you want for
checking the pipeline. The study needs tasks where the toolchains differ in
kind — introducing a dependency, fixing an under-declared build graph, satisfying
a presubmit gate the change trips — which are the candidates the design document
lists and the ones this run says to prioritise.

## Next

Tasks with headroom, per above. Then a pilot on one model and one harness across
the three toolchains, for an effect size and a noise floor, before committing to
any factorial.
