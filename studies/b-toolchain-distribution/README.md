# Study B — in-distribution toolchains vs. a proprietary-style stack

The design, the hypotheses, the prior art and the threats to validity are in
[`docs/studies/b-toolchain-distribution.md`](../../docs/studies/b-toolchain-distribution.md).
This directory is the instrument. **Nothing here has been executed against a model.**

## What is built

One problem — `summarize` must gain a median it takes from the statistics module
rather than reimplementing — posed in four toolchains:

| variant | the toolchain | what it is for |
|---|---|---|
| `add-median-oss` | `src/`, `tests/`, `pytest`, a `Makefile` | in-distribution: what a model has read a million times |
| `add-median-twin` | identical behaviour, every user-visible name changed (`fiz/`, `hulor/`, `mapu nuju`) | **the control** |
| `add-median-twin-b` | the same again, from a different seed (`paj/`, `lodip/`, `tove reru`) | **the instrument's own floor** |
| `add-median-proprietary` | a `depot/` monorepo, `BUILD` files with declared deps, `//depot/pkg:target` labels, `dbuild`, a presubmit gate | out of distribution by structure *and* name |

Both twin vocabularies are drawn by `arms/twin.py`'s generator from the seeds in
`manifest.json` — regenerate and they come back identical. Until 2026-08-11 the
first twin's words were hand-written, which the design document already
described as mechanical; two twins produced by two different processes would not
have been a floor.

The source files, the assertions and the acceptance criteria are shared. Only the
toolchain around them differs, because a variant that is harder in *substance*
would make the study measure difficulty instead of familiarity.

## The twins are the point, and the second one more than the first

`add-median-proprietary` underperforming `add-median-oss` would prove very little
on its own: a monorepo with declared dependencies and a presubmit gate is more
work, not just less familiar. `add-median-twin` separates the two. It is the
`oss` variant with the names changed and nothing else, so:

- twin ≈ oss → the deficit on `proprietary` is **structural**;
- twin ≪ oss → a large part of it is **names**.

Reporting the twin is not optional. It is what makes any claim about familiarity
a claim rather than an assertion.

**The second twin is what makes any of it readable.** A twin-versus-`oss` gap is
not a noise floor, however tempting it is to use as one: `oss` is the familiar
toolchain, which is the treatment, so that gap mixes effect with noise and bounds
the effect from above. Two twins are the *same* treatment under two arbitrary
vocabularies, so twin-versus-twin-b is noise and nothing else. It is declared as
`instrument_arms` in `study.yaml`, printed per axis as `instrument_floor`, and a
contrast that does not clear it is not interpreted — including either twin
against `oss`, which is partly the floor itself.

## What is verified, and what is not

Verified, and re-checkable by `pytest -m harbor`:

- all four images build, and **all 28 variants are solved by their own oracle**
  through Harbor (`tests/test_tasks_through_harbor.py`), which is the admission
  criterion: an arm whose task is broken would report the instrument's failures
  as the agent's. Run in full on 2026-08-11 including both twins, at $0 — the
  oracle runs the task's own solution rather than a model. That suite reads its
  variant list from `manifest.json` rather than a literal, because a
  hand-written list is one that goes stale silently: adding `twin-b` left it
  admitting three variants per task and saying nothing about the fourth;
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

## Task 2 — `use-validator`, the first with headroom

`summarize` must reject non-numeric readings by calling `numeric` from the
**validate** package — a package the summarizing package does not currently
reach. The code change is three lines in all three variants. The *toolchain*
work is where they diverge, and that is the whole design:

| variant | what "make it reachable" means |
|---|---|
| `oss` | add the package to `PYTHONPATH` in the `Makefile` |
| `twin` | the same, under names the model has never read |
| `proprietary` | declare `//depot/validate:validate` in the entry target's `deps`, or presubmit rejects a change that otherwise works |

The acceptance check requires the validator's own `NotNumeric` to propagate and
rejects a home-grown `isinstance` check, so an arm that reimplemented the test
has done different work from an arm that found the package.

All six variants (two tasks × three toolchains) pass their own oracles through
Harbor.

## The pilot, 2026-08-10 — and why it says not to run the factorial yet

24 trials (4 tasks × 3 substrates × 2 repetitions), one model
(`claude-sonnet-4-5`), one harness (`terminus-2`), no documentation variation.
**24/24 verified, 0 errors, $2.156, 16m40s** at concurrency 3, recorded to the
dedicated ADP. Study digest `sha256:8156a554…`.

### The outcome axes are useless, and the report says so properly

| axis | oss | twin | proprietary |
|---|---|---|---|
| acceptance | 1.000 (n=8) | 1.000 (n=8) | 1.000 (n=8) |
| discipline | 1.000 (n=8) | 1.000 (n=8) | 1.000 (n=8) |

Every arm solved every task, twice. Pooled within-cell sd is **0.0**, and the
contrast in sd units comes back
`{"unavailable": "every repetition of every cell gave the same value"}` rather
than a division by zero or an infinity. That is the noise floor doing its job:
there is no outcome signal here, and the analysis declines to invent one.

**The whole task set saturates**, not just `add-median`. Every task is too easy
for this model.

### The cost ordering looks like a finding and is not

Aggregated, the arms line up exactly as H2 predicts — and this is the trap:

| arm | total cost | tokens in | tokens out |
|---|---|---|---|
| oss | $0.6410 | 345,025 | 23,948 |
| twin | $0.7016 | 465,873 | 24,623 |
| proprietary | $0.8133 | 627,505 | 28,154 |

Per task, the ordering falls apart:

| task | oss | twin | proprietary |
|---|---|---|---|
| add-median | 0.0688 ±0.0023 | **0.0845** ±0.0039 | 0.0704 ±0.0083 |
| fix-spread | 0.0538 ±0.0040 | 0.0583 ±0.0077 | **0.0525** ±0.0060 |
| strict-mode | 0.0984 ±0.0130 | 0.0982 ±0.0016 | **0.1898** ±0.0127 |
| use-validator | 0.0996 ±0.0045 | 0.1098 ±0.0217 | **0.0939** ±0.0021 |

(± is the within-cell half-spread over two repetitions.)

Three things follow, and all three argue against a factorial:

1. **The aggregate effect is one task.** `strict-mode` costs the proprietary arm
   nearly double; on the other three, proprietary is at or *below* `oss`. An
   aggregate over four tasks turned a single-task effect into an apparent trend.
2. **`use-validator` went the wrong way.** It is the task built specifically to
   make the toolchains differ in kind — reach a package the entry does not, which
   in the depot means a declared dep a presubmit gate enforces — and the
   proprietary arm was the **cheapest** on it. Whatever the aggregate is
   measuring, it is not the manipulation the task was designed around.
3. **The gap is close to the noise.** Mean within-cell half-spread is $0.0073 and
   the maximum is $0.0217; the mean oss→proprietary gap is $0.0215 per trial —
   about three times the average noise and the same size as its worst case, at
   n=2 per cell.

### What the pilot bought

Exactly what a pilot is for: the current instrument cannot answer the question,
and it now says precisely why. Before a factorial is worth its money the task set
needs **headroom** — tasks this model fails often enough for an outcome axis to
vary — and enough repetitions for a within-cell sd that a contrast can be divided
by. `strict-mode` is the one task showing anything and is the place to look first.

None of the above is a result about agents, toolchains, or familiarity. It is a
result about this task set.

## What the pilot's one gap was, 2026-08-10

`strict-mode` cost the `proprietary` arm nearly double while `twin` matched
`oss`, which by the twin's own logic means *structural, not naming*. The
trajectories say what the structure was:

| arm | tool calls | what it did |
|---|---|---|
| `oss` | 20 | explored, edited three files, ran the suite twice, stopped |
| `proprietary` | 25 | the same edits, **plus a new test module for the library and a new `py_test` target for it**, then two `dbuild test` runs and two `dbuild presubmit` runs |

The proprietary arm was not lost. It did **more work**, because the depot
convention — every directory that produces something declares its targets —
invites a test beside the library you just changed, and a named gate invites
running it.

That is the confound the design document's §9 warns about, caught on real data:
**the arms were not doing the same amount of work**, so the cost gap is not a
familiarity measure. It is also a finding in its own right — a convention that
asks for more work costs more without anyone being unfamiliar with anything.
The twin arm made it legible by *not* moving, which is the best evidence so far
that the control does its job.

## Calibration — difficulty is measured now, not asserted

`calibrate.py` runs a task N times on the `oss` substrate alone (the cheapest
arm, and the one a model should find easiest) and reports the pass rate and the
verifier's reason for each failure. A task at 0/n or n/n cannot carry an outcome
axis whatever the other arms do; the useful band is where repetitions of one
cell actually differ.

First pass, 3 reps, $1.43:

| task | pass rate | mean $ | mean steps |
|---|---|---|---|
| `topo-order` | 2/3 | 0.189 | 23.0 |
| `window-stats` | 3/3 | 0.136 | 18.7 |
| `merge-config` | 1/3 | 0.154 | 17.7 |

Two of three landed in a usable band on the first attempt. `window-stats`
saturated and was hardened rather than dropped: a rule was added that
*interacts* with the others instead of sitting beside them — a gap removes a
window without shifting the ones after it, which rules out the natural
implementation of filtering the series before slicing it.

Second pass, 5 reps, $3.23 — and the reasons mattered more than the rates:

| task | pass rate | of the failures |
|---|---|---|
| `topo-order` | 1/5 | 2 were the `cycle-with-tail` rule, **2 were an import the task never explained** |
| `window-stats` | 5/5 | — |
| `merge-config` | 4/5 | **1, and it was the same import** |

Three of six failures were the instrument, not the task. A package's code sits at
`src/<pkg>/<pkg>.py` with its own directory on the path, so `from graph import
resolve` is right and `from graph.graph import resolve` is wrong — and nothing
said so. The two tasks that produced every one of those failures were exactly the
two whose starting code contained no example import; `window-stats`, which shows
`from stats import mean`, never hit it in ten runs.

**Every toolchain's instruction now states the convention** in its own
vocabulary. Half the measured difficulty of the hard tasks was an agent guessing
something the task never told it — plausible noise, shaped exactly like the
effect being hunted, and it would have entered a factorial as a familiarity
signal.

The lasting rule: **read the reasons, never only the rate.** `topo-order` at 1/5
for mixed reasons and at 1/5 for the rule it was built around are different tasks
wearing the same number.

Fourth pass, 6 reps, on corrected specs — the decisive one:

| task | pass rate | mean $ | mean steps |
|---|---|---|---|
| `topo-order` | **6/6** | 0.267 | 23.8 |
| `window-stats` | **6/6** | 0.143 | 16.8 |
| `merge-config` | **6/6** | 0.170 | 16.3 |

Every task saturates. Across four rounds, **100% of the apparent difficulty was
authoring defects** — an import convention the layout never explained, and an
acceptance check that demanded a wrong answer:

| round | topo | window | merge | measuring |
|---|---|---|---|---|
| 1 | 2/3 | 3/3 | 1/3 | unknown — reasons not recorded |
| 2 | 1/5 | 5/5 | 4/5 | ambiguity, and a wrong spec |
| 3 | 4/5 | 5/5 | 3/5 | ambiguity again; prose had not fixed it |
| 4 | 6/6 | 6/6 | 6/6 | the tasks |

Seven tasks authored, three of them built specifically to be failable, and none
discriminates. The conclusion is not that they are too easy — it is that **a task
of this size cannot discriminate this model**, and it took four rounds to see
past our own defects to that.

## The same tasks on a smaller model, 5 reps, $2.40

Study B crosses model as a factor anyway, so the cheaper move than inventing a
puzzle that defeats the strongest available model is to measure one the task set
does not saturate.

| task | `claude-sonnet-4-5` | `claude-haiku-4-5` |
|---|---|---|
| `topo-order` | 6/6 | **0/5** |
| `window-stats` | 6/6 | 5/5 |
| `merge-config` | 6/6 | 5/5 |
| `strict-mode` | — | **2/5** |

`topo-order`'s failures on the smaller model are the task, not the instrument:
it reported `['a','b']` for two disjoint cycles (stopping at the first) and
`['a','b','c','d']` for the cycle with a tail (the very answer the corrected
spec now rejects). Genuine, and 0/5 — too hard here, in the same way 6/6 is too
easy there. Both extremes have zero within-cell variance.

`strict-mode` measured **2/5** here, which looked like the first task ever
inside the usable band. **It was not, and the correction is the point.**

Three of those five failures reported `no FAIL line recorded`. A failure whose
reason is unknown cannot be classified as the task or the instrument, and every
round so far has turned on exactly that distinction — so 2/5 was an unusable
number wearing a useful one. `calibrate.py` now falls back through the verifier's
error output and then the trial's own exception before admitting it has nothing.

Re-measured with reasons captured, `strict-mode` is **5/5**. The three unexplained
failures were trials that never finished, not a model failing a task. A
calibration that cannot say *why* is worth about as much as one that cannot say
*whether* — and this is the second time a plausible number turned out to be the
instrument.

## The sweep that found a real one, 5 reps, $2.55

| task | `claude-haiku-4-5` | failures |
|---|---|---|
| `add-median` | 4/5 | 1, genuine — never added the median |
| `use-validator` | **3/5** | 2, genuine — `TypeError, not NotNumeric` |
| `fix-spread` | 5/5 | — |
| `strict-mode` | 5/5 | — |

**`use-validator` at 3/5 is the first task measured in the band for reasons that
are the task's own.** Its failures are on-task and specific: the agent never
routed through the validator, so a bad reading raised `TypeError` from arithmetic
instead of the `NotNumeric` the task names. It is also the
toolchain-differentiating task — the one whose work differs by substrate — which
is the one worth having variance in.

`add-median` at 4/5 is marginal but real. `fix-spread` and `strict-mode` sit at
ceiling and serve as matched controls: if a substrate effect shows up there, it
is not about difficulty.

## The primary measure is now behaviour, 2026-08-11

Amendment §7.1 is accepted and registered in `study.yaml`. The primary metric is
**`process:escaped`** — whether a trial invoked a toolchain its arm was not
given — with pass rate demoted to a gate that is *reported beside* it and never
applied to it. Each arm declares the command words foreign to it:

| arm | its runner | declared foreign |
|---|---|---|
| `oss` | `make test` | `dbuild`, `tomak`, `pytest` |
| `twin` | `tomak vess` | `dbuild`, `make`, `pytest` |
| `proprietary` | `dbuild test` | `make`, `tomak`, `pytest` |

`pytest` is foreign to all three: no toolchain here names it as its runner, and
it is what the pilot saw the twin arm reach for.

The list lives on the **arm**, so it rides inside the arm digest and therefore
the study digest. Retuning it is not a config change — it moves the digest, and
this project's "digest mismatch ⇒ no comparison" rule then refuses to compare
across it. That is the point: the definition of the primary measure is the last
thing that should be adjustable after the runs are in.

Three notes that belong with the number rather than in a design document:

- **Pass rate is a stratification, not an exclusion.** Escaping causes flailing
  causes failing, so dropping failed trials would delete escapers from exactly
  the arms predicted to escape most.
- **A probe is not an escape.** `which pytest` asks whether a tool exists; an
  agent that looks and then uses its own runner did not reach past it. Counted
  separately.
- **The pilot's escape counts predate the detector.** They were read off
  trajectories by hand, under a matcher that scored `grep -rn pytest .` as an
  escape and missed `python3 -m pytest`. They have not been recomputed.

## Next

- **Pilot 3, and it is the only way to get a pilot-2 number back.** The report in
  `report/` is the pre-fix one — 120 of 120 axis scores are `null` — the ADP
  evals were left unscored, and the local artifacts the re-grade ran over are not
  on this machine. Nothing quoted from pilot 2 anywhere in this repository can be
  re-derived from anything checked in. That is not recoverable by re-reporting;
  it needs the run. 4 tasks × 4 arms × 5 repetitions = **80 trials, ~$16.60** at
  pilot 2's $0.208 per trial.

  What has been fixed is the silence, not the loss: a report with no scored trial
  on an axis, or with no grader axis at all, is now a loud warning in the JSON
  and on the page, with two tests reproducing pilot 2's exact shape.
- Spend the next increment on **more tasks rather than more repetitions**: the
  effect behind the amendment was four of six events in one cell, and the
  statistics resample tasks whole.
- If a stronger model is wanted later, tasks have to grow in **scope** — many
  files, many constraints, integration rather than logic. Trickiness produces
  ambiguity, and the third round is what ambiguity costs.
