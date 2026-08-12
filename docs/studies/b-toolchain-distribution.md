# Study B — In-distribution toolchains vs. a proprietary-style stack

**Status: design, not registered.** Nothing here has been executed, and three things have to be
decided before it can be (§10). This document exists to be argued with.

**Author's note on sources.** Every citation below was checked against a live search while writing;
each is linked. Where a claim is mine rather than a source's, it says so. Where a number comes from
this repository's own execution logs it is dated and traceable to a run id — those are the only
unpublished numbers in here.

---

## 1. The question

> Do autonomous coding agents do measurably worse when the language, framework and toolchain of a
> task are **out of distribution** relative to their training data — and if so, how much of that
> gap is unfamiliarity rather than the task simply being harder?

The framing that prompted this: **best-of-breed open source** (in-distribution: Python/TypeScript,
git + GitHub, pytest, npm, Make) against **a reconstruction of Google's internal engineering
practice** (out-of-distribution: monorepo layout, Bazel/BUILD targets, trunk-based development with
presubmit gating, a Critique-style review loop). No humans in the loop; the agent either lands the
change or does not.

### 1.1 Hypotheses, stated before any data

- **H1 (efficacy).** Pass rate is lower on the proprietary-style arm than the in-distribution arm.
- **H2 (cost).** Token spend and dollar cost per *solved* task are higher on the proprietary-style
  arm, and the gap is larger than the pass-rate gap — i.e. the agent flails before it fails.
- **H3 (hallucination).** Rate of calls to tools, targets or APIs that do not exist is higher on the
  proprietary-style arm.
- **H4 (documentation).** Supplying reference documentation narrows the gap, and supplying worked
  examples narrows it further — with the effect larger on the proprietary-style arm than on the
  in-distribution one (an interaction, not a main effect).
- **H0 for the instrument.** The paired *semantic-twin* control (§5.3) shows **no** difference from
  its in-distribution twin. If it does show one, the study is measuring difficulty, not
  familiarity, and H1–H4 cannot be read as stated.

H4 and the instrument null are the load-bearing ones. H1 on its own is nearly unfalsifiable — of
course an agent does worse on unfamiliar ground — and would be a press release, not a finding.

---

## 2. The central validity problem, stated first

**The proprietary arm cannot use the proprietary tools.** Piper, CitC, Critique, TAP and Blaze are
not public. The only published description of the monorepo model at any depth is Potvin and
Levenberg's CACM article ([dl.acm.org/doi/10.1145/2854146](https://dl.acm.org/doi/10.1145/2854146)),
which is an architecture overview, not a specification. Bazel — the open-sourced release of Blaze —
is public, but that is precisely the part which is therefore *in* distribution.

So any "Google arm" is a **reconstruction from public description**, and the study measures agent
performance on a plausible imitation of an internal stack. That is a construct-validity limit, and
it must be in the pre-registration and the abstract, not a footnote. A reviewer will find it in
ninety seconds and be right to.

This has a consequence for the framing. The honest version of this study is **not** "how do agents
do at Google" — nobody outside Google can answer that. It is:

> **How do agents perform on a software stack whose conventions are documented but whose code is
> absent from the training corpus?**

Google's published practice is a *source of realistic design constraints* for constructing such a
stack, and a good one, because the conventions are unusually well documented and unusually
distinctive. It is not the object of study. Framed that way the study is answerable, and the finding
generalises to the case people actually care about: an agent dropped into a large private codebase.

---

## 3. Prior art

### 3.1 Contamination — why "unfamiliar" is hard to establish

The premise that benchmark performance is inflated by training exposure is well supported.
Contamination of widely used benchmarks is documented at high rates, grows with model scale, and
has worsened over time; HumanEval and MBPP in particular have been found to carry solutions seen
during training ([NLP Evaluation in trouble](https://arxiv.org/pdf/2310.18018);
[A Survey from Static to Dynamic Evaluation](https://aclanthology.org/2025.emnlp-main.511.pdf);
[LLM Benchmark Datasets Should Be Contamination-Resistant](https://arxiv.org/pdf/2605.19999)).

Mitigations cluster into **data curation** (material unavailable at training time) and **data
refactoring** (perturbing existing benchmarks) — see
[CodeCleaner](https://dl.acm.org/doi/10.1145/3755881.3755901) and
[VarBench](https://arxiv.org/pdf/2406.17681). Both matter here: our proprietary-style arm is a
curation play, and the semantic twin (§5.3) is a refactoring play.

**Consequence for this design:** we cannot verify what any commercial model was trained on. We can
only construct material that did not exist publicly before the study, and hold everything else
constant. Every claim about "distribution" in this study is therefore an inference from
construction, not a measurement of a training set — and should be worded that way.

### 3.2 The effect this study expects to find has already been observed in narrower settings

- LLMs are markedly weaker on low-resource languages than on Python
  ([survey](https://dl.acm.org/doi/10.1145/3770084);
  [Bridge-Coder](https://arxiv.org/pdf/2410.18957)).
- Faced with an unfamiliar API name, models **substitute a confabulated alternative rather than
  adopting the documented one** — parametric knowledge overriding the prompt
  ([When LLMs Lag Behind](https://arxiv.org/html/2604.09515v1)).
- On private libraries, models generate impoverished, low-diversity API usage relative to real
  private-library development
  ([To See is Not to Master](https://arxiv.org/html/2603.15159v4)).
- Retrieval of documentation helps, but not uniformly and not to parity
  ([When LLMs Meet API Documentation](https://arxiv.org/html/2503.15231v1)).

**What is new here** is scope and outcome measure. Those results are function- or file-level code
generation scored by unit tests. This study asks about an **autonomous agent completing a multi-step
task inside a container** — build, test, iterate, land — where the toolchain itself is the unfamiliar
thing, and where cost and hallucination are first-class outcomes rather than diagnostics. The
closest published framing of that gap is
[Challenges and Paths Towards AI for Software Engineering](https://arxiv.org/pdf/2503.22625).

### 3.3 Agent benchmarks are fragile, and the failures are instructive

SWE-bench is the reference point and its problems are documented: solution leakage in ~32.7% of
resolved instances, and weak tests admitting incorrect patches in ~31.1% of passes; correcting for
both dropped one agent configuration from ~12.5% to ~4%
([SWE-Bench+](https://arxiv.org/pdf/2410.06992), [OpenReview](https://openreview.net/forum?id=R40rS2afQ3)).
Dynamic benchmarks that draw tasks published after a model's cutoff are one response
([SWE-MERA](https://arxiv.org/html/2507.11059v3)). Tool-use, planning and reasoning failures in
agents have been synthesised separately
([Beyond the Leaderboard](https://arxiv.org/pdf/2607.05775)).

**Consequences adopted here, non-negotiable:**

1. Task statements are authored, never scraped from issue trackers — leakage is impossible by
   construction rather than filtered after the fact.
2. Every task's grader is multi-axis and adversarial to "passes the test, wrong change" — the
   failure mode that cost SWE-bench two thirds of its headline number.
3. Every task ships an **oracle** (a reference solution) that must satisfy its own grader on every
   axis before the task is admitted, so a failing arm is a failing arm and not a broken task. This
   is already enforced in this repository by `tests/test_tasks_through_harbor.py`.

### 3.4 Google's published practice, and its limits as a source

- Potvin and Levenberg, *Why Google Stores Billions of Lines of Code in a Single Repository*, CACM
  59(7), 2016 — the monorepo, trunk-based development, ~1B files/86TB at the time of writing
  ([ACM DL](https://dl.acm.org/doi/10.1145/2854146),
  [Google Research](https://research.google/pubs/why-google-stores-billions-of-lines-of-code-in-a-single-repository/)).
- Google's own report on applying LLMs to internal code migration is directly relevant and should be
  read before finalising tasks — it is the closest thing to a baseline for agent performance on this
  stack, from the only party able to measure it
  ([Migrating Code At Scale With LLMs At Google](https://arxiv.org/pdf/2504.09691)).
- Bazel's public documentation is the usable specification for the build layer, and is the one
  component where the reconstruction can be faithful rather than approximate.

Beyond these, public description of Piper/CitC/Critique/TAP is engineering blogs, talks and
second-hand accounts. **Design rule adopted here: no arm depends on a behaviour that is not
documented in a citable source.** Where the reconstruction has to invent, it invents *plausibly and
visibly*, and the invention is listed in the study's limitations.

---

## 4. Can Harbor run this? Yes — and the reason is worth stating precisely

This was the open question that prompted the document. The answer turns on distinguishing two
factors that are easy to conflate.

| Factor | What it manipulates | Harbor support |
|---|---|---|
| **Toolchain / environment** (this study) | The container: languages, build system, repo layout, test runner, review gate | **Native.** A Harbor task *is* a Dockerfile plus a repo plus an instruction plus a verifier |
| **Agent tool vocabulary** (Study A) | The function-calling surface the model sees | **Not with `terminus-2`**, which fixes it at `bash_command` and `mark_task_complete` |

`terminus-2`'s fixed tool surface is, for this study, **the experimental control rather than a
limitation**. The agent gets a shell and nothing else, identically in both arms; everything that
varies lives on the other side of that shell. Had the tool surface differed per arm, the
manipulation would have been confounded with the interface.

Verified on 2026-08-10 against Harbor 0.20.0 in this repository:

- `terminus-2` issues exactly two functions, `bash_command` and `mark_task_complete`
  (`harbor/agents/terminus_2/terminus_2.py`), batching several shell commands per step.
- Harbor accepts **custom agents by import path** (`--agent module.path:ClassName`), with
  constructor kwargs via `--agent-kwarg`; `BaseAgent` is an ABC requiring `setup()` and `run()`
  (`harbor/agents/factory.py`, `harbor/agents/base.py`). So a bespoke tool vocabulary is buildable —
  it is simply not needed here, and this project's own plan excludes in-process agent loops
  (`docs/execution-plan.md` §5).
- Multiple agents are selectable (`claude-code`, `codex`, `openhands`, `terminus-2`, …), which is
  what makes *harness* a factor this study can cross against toolchain.

**The one gap that does block this study** is on duva-bench's side, not Harbor's: `arms/materialize.py`
— which produces a per-arm task variant — **is never called by the trial runner**. Arms currently
vary only model, agent, environment variables and agent kwargs. This study needs a different task
*directory* per arm, which is the tractable half of that gap (files, not tool definitions). See
`docs/blockers.md`.

### 4.1 The tool-vocabulary axis is reachable after all (spike, 2026-08-10)

An earlier draft of this document said Study A's toolset axis needed a bespoke Harbor agent, on the
strength of `terminus-2`'s fixed surface. **That was wrong**, and the correction matters because it
was about to be used as grounds for dropping a pre-registered hypothesis.

Harbor carries **MCP servers in task config** — `EnvironmentConfig.mcp_servers`, merged with the
agent config's and passed to the agent (`harbor/trial/trial.py:789`). Two behaviours differ sharply
by agent and the difference decides the axis:

- **`terminus-2` only describes them.** It appends a text summary of the servers to the instruction
  (`terminus_2.py:1578`); the model's callable surface is still `bash_command` and
  `mark_task_complete`. Useless as a manipulation.
- **`claude-code` registers them properly**, writing user-scoped `mcpServers` config
  (`claude_code.py:1308`), so the tools arrive as genuine callable functions.

A spike confirmed it end to end: one task, a ledger reachable *only* through MCP tools, two variants
identical but for two environment variables the server reads to name its tools. The trajectory of
the first run contains

```
2  mcp__ledger__ledger_append
1  mcp__ledger__ledger_read
1  Write
1  ToolSearch
```

— the names chosen in `task.toml`, in the trace the bridge maps to ADP, on a trial that passed its
verifier. **So the toolset axis is a task-config difference, exactly like this study's toolchain
axis, and needs the same materialization wiring and no agent loop.**

Three consequences worth carrying:

1. **Names are prefixed `mcp__<server>__<tool>`.** Any hallucinated-call rate has to normalise that
   prefix, or every legitimate MCP call reads as a call to a tool the arm did not have — the same
   shape of defect as the one gate G2 found in the smoke study.
2. **MCP adds tools; it does not replace the native ones.** `Write` and `ToolSearch` are there too.
   A toolset arm is therefore "native tools plus a named set", and a clean manipulation needs tasks
   where the named set is the *only* route to the goal — as this spike's ledger is. That is a task
   design constraint, and it is a real one.
3. **The agent becomes a covariate.** The axis needs an MCP-registering agent, so `terminus-2` is
   out for arms that manipulate tools, and harness cannot be varied freely against toolset without
   confounding. Study A's design has to account for that.

---

## 5. The instrument

### 5.1 What varies, and what is nailed down

| Held constant | Varied |
|---|---|
| The problem to be solved, semantically | The toolchain the solution must be built with |
| The agent interface (`terminus-2`, shell only) | *(crossed)* the harness, as a robustness check |
| Container CPU/RAM, step budget, wall-clock budget | *(crossed)* documentation grade |
| The grader's axes and their weights | |
| Model temperature (0) and provider | *(crossed)* the model |

### 5.2 Arms

A 2 × 3 core factorial, crossed with model and harness:

- **Toolchain**: `oss` | `proprietary-style` | **`twin`** (the control, §5.3)
- **Docs grade**: `none` | `reference` | `rich` (reference + worked examples)

`oss` is git + GitHub-style PR conventions, `pytest`, `npm`/`make`, conventional repo layout.
`proprietary-style` is a monorepo with `BUILD` targets under Bazel, trunk-based development with a
presubmit gate, a `//depot/...`-style path convention, and a review step the agent must satisfy
before its change counts as landed.

**Cost control:** the full 3 × 3 × models × harnesses is large. A pilot should fix docs at `none`
and run `oss` vs `proprietary-style` vs `twin` on one model and one harness, purely to estimate the
effect size and the noise floor, before committing to the factorial. Nothing else in this document
should be executed until that pilot has produced a noise-floor estimate.

### 5.3 The twin arm is the whole methodological contribution

A `proprietary-style` arm that underperforms `oss` proves very little on its own: the monorepo arm
has more ceremony, more files, longer paths and a stricter gate. It may simply be **harder**, and
"unfamiliar" and "harder" are not separable by that contrast.

The **twin** arm separates them. It is the `oss` toolchain with every user-visible identifier
mechanically renamed — commands, config file names, target syntax, flag names — to pronounceable
non-dictionary strings of matched token length, with behaviour byte-for-byte identical. `pytest`
becomes something that is not `pytest` and does exactly what `pytest` does.

- If `twin` ≈ `oss`, the agent's competence transfers through renaming, and any `proprietary-style`
  deficit is attributable to genuine structural difficulty.
- If `twin` < `oss` by a margin comparable to `proprietary-style`, then a large part of the deficit
  is **familiarity with names**, not engineering substance.

This is the same instrument as Study A's semantic twin, applied to a toolchain rather than to a tool
vocabulary — and, unlike Study A's version, it is expressible entirely as files in a task directory,
so it works with `terminus-2` today. It is also a data-refactoring contamination control in the sense
of §3.1.

**The twin is also the study's own null.** Reporting it is not optional: it is what makes H1 a claim
about familiarity rather than about ceremony.

### 5.3.1 What the pilot's one gap turned out to be — read this before designing a task

The 2026-08-10 pilot produced exactly one cell with a cost gap: `strict-mode` cost the
`proprietary` arm nearly double what it cost `oss`, while `twin` matched `oss`. By the logic
of §5.3 that reads as **structural, not naming** — and the trajectories say precisely what the
structure was.

| arm | tool calls | what it did |
|---|---|---|
| `oss` | 20 | explored, edited three files, ran `make test` twice, stopped |
| `proprietary` | 25 | explored, edited three files, **wrote a new test module for the library and declared a new `py_test` target for it**, then ran `dbuild test` twice and `dbuild presubmit` twice |

The proprietary arm was not lost. It did **more work**, because the depot convention — every
directory that produces something has a `BUILD` declaring its targets — invites a test target
next to the library you just changed, and a named presubmit gate invites running it.

**This is a confound, and it is the one §9 warns about**: the arms were not doing the same
amount of work, so their costs are not comparable as a familiarity measure. It is also a
finding in its own right, and an uncomfortable one for the study's framing — a convention that
*asks for more work* raises cost without anybody being unfamiliar with anything.

Two consequences for task design, both adopted:

1. **A task must pin down its own scope**, or the substrate decides how much work there is.
   State what to change and what "done" means tightly enough that a reasonable agent does the
   same amount in every arm.
2. **Where extra work is genuinely part of the convention, say so and measure it separately.**
   Folding it into a cost contrast labelled "familiarity" is how a study reports one thing and
   means another.

That the twin arm made this legible — by *not* moving — is the best evidence so far that the
instrument in §5.3 does its job.

### 5.4 Documentation grades

`none` is no documentation. `reference` is complete, accurate reference material for the toolchain
in the container, without examples. `rich` is `reference` plus worked examples of the operations the
tasks require. The point is H4's interaction: if documentation closes the gap on the unfamiliar arms
and not on `oss`, the deficit is retrievable knowledge; if it does not, it is something harder.

This connects to a real finding in the literature — retrieval helps unevenly and not to parity
([When LLMs Meet API Documentation](https://arxiv.org/html/2503.15231v1)) — and to the confabulation
result: a model that substitutes a remembered API for a documented one
([When LLMs Lag Behind](https://arxiv.org/html/2604.09515v1)) will not be rescued by more
documentation, and the docs axis is how we would see that.

---

## 6. Tasks

Six to eight tasks, authored not scraped, each with an oracle and a multi-axis grader, each
expressible in **all three toolchains without changing what is being asked**. That last constraint
is the hard one and it should drive selection.

### 6.1 A task is admitted on a measured pass rate, not on an author's opinion

Added 2026-08-10, after the pilot. Every task in the first set was described in
its own notes as having headroom and every arm solved all of them twice: pooled
within-cell sd `0.0`, no outcome signal, nothing to divide a contrast by. The
description was sincere and wrong, and there was no step at which it could have
been caught.

So difficulty is now measured before a task is admitted. `calibrate.py` runs a
candidate N times on the `oss` substrate alone — the cheapest arm and the one a
model should find easiest — and reports the pass rate together with the
verifier's reason for each failure.

- **n/n is a smoke task.** Useful for checking a pipeline, useless for measuring
  anything. `add-median` is kept on exactly those terms.
- **0/n is not a study task either.** A task nothing passes measures the task.
- **The band in between is the point**, because that is where repetitions of one
  cell differ and a within-cell variance exists at all.

What makes a task land in that band, from the three built for it: rules that
**interact** rather than sit beside one another. `window-stats` passed 3/3 while
its rules could be satisfied one at a time, and needed a rule that changes the
order the others have to be applied in — positions decided before gaps, not
after. Rules that can be handled independently are a checklist; rules that
constrain each other are a problem.

### 6.2 Ambiguity is not difficulty, and it is easy to mistake one for the other

Found 2026-08-11, in the second calibration. `topo-order` came back 1/5 and
`merge-config` 4/5, and reading the *reasons* rather than the rates changed both
numbers:

```
FAIL: cycle-with-tail: members ['a','b','c'], expected ['a','b','c','d']   ← the task
FAIL: cannot import: No module named 'graph.graph'; 'graph' is not a package ← the instrument
```

Three of the six failures were the second kind. The layout puts a package's code
at `src/<pkg>/<pkg>.py` and its own directory on the path, so `from graph import
resolve` is right and `from graph.graph import resolve` is wrong — and **nothing
told the agent which**. The two tasks that produced every one of those failures
were exactly the two whose starting `report.py` contained no example import;
`window-stats`, whose starting code shows `from stats import mean`, never hit it
once in ten runs.

So half the measured "difficulty" of the hard tasks was an agent guessing a
convention the task never stated. That is noise of the worst kind: it is
plausible, it looks like the effect being hunted, and it would have entered a
factorial as a familiarity signal.

**The convention is now stated in every toolchain's instruction**, in that
toolchain's own vocabulary. Two rules follow:

1. **A toolchain must be described well enough that a competent agent could not
   reasonably guess wrong.** The study measures what it costs to *work* in an
   unfamiliar toolchain, not what it costs to divine an undocumented one. The
   second is easy to manufacture and worthless.
2. **Read the failure reasons, never only the rate.** A pass rate in the usable
   band is not evidence of a usable task; `topo-order` at 1/5 and at ~3/5 for
   genuine reasons are different tasks wearing the same number.

### 6.3 Three attempts at a hard task produced three instrument defects and no difficulty

The uncomfortable result of 2026-08-11, and the one most worth acting on.

`topo-order`, `window-stats` and `merge-config` were written specifically to be
failable. Measured, they produced a pass rate of 1/5, 5/5 and 4/5 — and reading
every failure, **not one of them was the task being hard**:

| apparent failure | what it actually was |
|---|---|
| `cannot import: No module named 'graph.graph'` (×3) | the layout never said how packages import each other (§6.2) |
| `cycle-with-tail: members ['a','b','c'], expected ['a','b','c','d']` (×2) | **the task was wrong and the agent was right** |

The second is worth spelling out. For `{a:[b], b:[c], c:[a], d:[a]}` the cycle is
`a→b→c→a`; `d` merely depends on it. The task said `members` must hold "exactly
the names taking part in it", the agent answered `['a','b','c']`, and the
acceptance check demanded `d` as well — because the reference implementation
lazily raised with *everything left unordered*. A correct answer was scored as a
failure.

That is the SWE-bench failure this design cites in §3.3 — a test admitting or
rejecting the wrong thing — arriving in our own instrument within a day of
citing it. It is also worse than the contamination it was written to avoid: a
weak test inflates a score, a *wrong* test invents an effect.

**So the honest state is: three deliberate attempts at a discriminating task
yielded none.** Every point of apparent difficulty was an authoring defect. That
is a fact about how hard it is to author these, not a fact about the model, and
it argues for:

1. **An oracle is not a specification.** Both defects would have been caught by
   asking "would a competent engineer answer differently, and be right?" of every
   acceptance case before spending anything.
2. **A second opinion on the spec is cheap and the run is not.** Calibration
   costs dollars per task; re-reading the acceptance cases costs minutes.
3. **Budget for the task set being the hard part.** The machinery — gates,
   substrates, graders, materialization — is done. Authoring tasks that
   discriminate for the right reason is the open problem.

### 6.4 With the defects removed, every task saturates — and that is the real result

Calibrated 2026-08-11 on corrected, unambiguous specs, 6 repetitions each on the
`oss` substrate:

| task | pass rate | mean $ | mean steps |
|---|---|---|---|
| `topo-order` | **6/6** | 0.267 | 23.8 |
| `window-stats` | **6/6** | 0.143 | 16.8 |
| `merge-config` | **6/6** | 0.170 | 16.3 |

Seven tasks have now been authored — four ordinary, three built specifically to
be failable — and **not one of them discriminates**. Every point of apparent
difficulty across four calibration rounds traced to an authoring defect, and
each defect cost real money to find:

| round | topo | window | merge | what it was measuring |
|---|---|---|---|---|
| 1 | 2/3 | 3/3 | 1/3 | unknown — reasons were not recorded |
| 2 | 1/5 | 5/5 | 4/5 | import ambiguity, and a spec that demanded a wrong answer |
| 3 | 4/5 | 5/5 | 3/5 | import ambiguity again; prose had not fixed it |
| 4 | **6/6** | **6/6** | **6/6** | the tasks |

**So the honest conclusion is not "these tasks are too easy". It is that a task
of this size cannot discriminate this model, and four rounds of measurement were
needed to see past our own defects to that fact.**

Two consequences, and neither is "write a cleverer puzzle":

1. **The model is the wrong constant.** Study B always crossed *model* as a
   factor; saturation says to choose one where the task set is not at ceiling
   rather than to keep hunting for a task that defeats the strongest available
   one. A study whose outcome axis is pinned at 1.0 measures nothing however
   good its statistics are.
2. **Scale, not trickiness.** If a stronger model is wanted, the tasks have to
   grow in *scope* — many files, many constraints, integration rather than
   logic — because a small closed-world problem with well-stated rules is
   something this class of model simply does. Trickiness produces ambiguity, and
   §6.2 is what ambiguity costs.

Candidate shape — each is a genuine multi-step change, not a function to complete:

1. **Add a feature across a module boundary**, updating build targets and the dependent tests.
2. **Diagnose and fix a failing test** whose cause is in a different package from the failure.
3. **Introduce a new dependency** and make the build accept it (the arms differ sharply here: an
   `npm install` versus adding a target and its transitive declarations).
4. **Refactor a shared interface** used by three call sites, keeping every consumer green.
5. **Fix a build-graph problem** — a cycle, or an under-declared dependency that passes locally and
   fails a clean build.
6. **Satisfy a presubmit gate** the change initially trips (lint, coverage, a layering rule).

Tasks 3, 5 and 6 are where the toolchains genuinely differ in kind; 1, 2 and 4 are closer to matched
and act as internal controls. **A task admitted to the set must have its oracle pass its own grader
on every axis in every arm** — otherwise the arms differ in difficulty at the task level and the
factorial is unbalanced before it starts.

---

## 7. Measures

**Primary:** per-axis pass rate from the task's grader, ranked per axis and never blended.

**Secondary, all pre-registered:**

| Measure | Why it is here |
|---|---|
| Tokens in/out per trial and **per solved task** | H2. Per-solved-task is the honest denominator: an arm that fails cheaply is not efficient |
| Cost in USD, from the agent's own usage record | Verified on this stack 2026-08-10; Harbor's summary is unreliable for at least one agent |
| **Hallucinated-reference rate** | H3. Invocations of commands, build targets or file paths that do not exist |
| Tool-error rate, retry count | Process cost distinct from outcome |
| Steps to first successful build; steps to first green test | Where the time actually goes |
| Escape-to-familiar rate | See below |

**Escape-to-familiar** is the measure this study should contribute. On the `proprietary-style` and
`twin` arms, does the agent try to reach for the in-distribution tool anyway — invoking `pytest` in
a repo that has no pytest, or `git commit` where the workflow has no git? It operationalises the
confabulation finding of §3.2 at the *toolchain* level, it is cheaply computable from the
trajectory, and it is a direct behavioural signature of out-of-distribution operation rather than an
inference from a score. It requires the rename map, which the twin generator already produces.

---

## 7.1 Amendment 1 — the primary measure moves to behaviour (2026-08-11)

**Accepted and registered 2026-08-11.** `studies/b-toolchain-distribution/study.yaml`
carries it as three `Amendment` records; the pre-amendment reading recomputes to
`sha256:4215f18f…`, which is the pre-registration digest pilot 2 actually ran under,
and `tests/test_study_b_specs.py` pins that equality so the amendment stays checkable
against the run it amends. §7.1.1 records what accepting it required.

**Recorded before the trials that will test it, and after the trials that suggested
it.** Both halves of that sentence matter, and §8's amendment discipline applies: the
pre-amendment reading stays computable and any report prints both.

### What the pilots established

| | pilot 1 (`sonnet-4-5`, 24 trials) | pilot 2 (`haiku-4-5`, 60 trials) |
|---|---|---|
| outcome axis | every arm solved every task — pooled sd `0.0` | oss 0.850, twin **0.950**, proprietary 0.850 |
| aggregate cost | ordering matched H2, and was one task of four | within-cell CV **0.62**; twin 50% above oss |

The twin arm is identical to `oss` in behaviour and differs only in names, so
**twin-minus-oss is a direct reading of measurement noise**. At n=20 it is 0.10 on the
outcome axis and ~50% on cost — in both cases larger than the oss↔proprietary
difference, which was 0.00 and −7% respectively. Neither measure can see an effect
this design would call small.

Detecting a 10-point difference at a base rate of 0.85 needs roughly **200 trials per
arm**. That is affordable, and it buys power in a measure that will saturate again the
moment the model improves.

### What did separate the arms, at n=20

| arm | used its own runner | invoked `pytest` directly |
|---|---|---|
| `oss` | 20/20 | 0/20 |
| `twin` | 14/20 | **6/20** |
| `proprietary` | 19/20 | 3/20 |

Concentrated and mechanistic: `strict-mode` × `twin` produced the four most expensive
trials in the study — 4 of that cell's 5 repetitions, 1.2–1.75M input tokens each —
with `python3 -m pytest` retried four times in a single trial after the project's own
runner was abandoned.

### The amendment

1. **Primary metric becomes `escaped`** — whether a trial invoked a toolchain its arm
   was not given. Behavioural, mechanistic, and it does not require a task to be
   failable, which removes task authoring as the binding constraint (§6.3).
2. **Pass rate becomes a gate, not a metric.** A trial that did not produce valid work
   is excluded; among those that did, the question is *how* they got there.
3. **Cost and tokens stay secondary and are reported as medians with the within-cell
   CV beside them.** A mean over a distribution with CV 0.62 and a 5× max/median ratio
   is not a summary.
4. **The twin's contrast with `oss` is reported first, on every measure**, as the
   noise floor. No contrast is interpreted that does not exceed it.

### H5, registered now and untested

> **Partial unfamiliarity costs more than total unfamiliarity.** An environment that
> *resembles* a familiar one but is renamed invites habitual actions that fail;
> an obviously foreign environment causes the agent to read its instructions instead.
> Predicted ordering on `escaped`: `twin` > `proprietary` > `oss`.

This is the inverse of the naive expectation and of H1–H3, which predict monotone
degradation with distance from the training distribution.

**It was generated by looking at pilot 2 after the fact and must not be reported from
that data.** It is testable on fresh tasks and a fresh run; if it survives, it is the
most useful thing this study could produce, because it says something actionable about
naming inside a private codebase. If it does not, the pilot found a coincidence in
twenty trials, which is exactly what twenty trials are for.

## 7.1.1 What accepting the amendment corrected in it

The amendment stands. Four things in it were wrong or unbuilt, and are recorded here
rather than quietly fixed, because §8's discipline applies to the amendment too.

**1. The power argument is weaker than stated, and is not why to do this.** §7.1 offers
`escaped` as the cheaper route to power. At the pilot's own rates that holds for the
contrast that needs it least:

| contrast | pilot 2 | Fisher two-sided | n/arm for 80% power |
|---|---|---|---|
| oss vs twin on `escaped` | 0/20 vs 6/20 | **p = 0.020** | ~21 |
| proprietary vs twin on `escaped` — **the H5 leg** | 3/20 vs 6/20 | p = 0.45 | **~120** |
| oss vs twin on pass rate, 0.85 → 0.75 | — | — | ~250 |

H5's own ordering rests on `twin > proprietary`, and that leg costs ~120 trials per arm
against pass rate's ~250 — a saving of about 40%, not an order of magnitude, and
clustering by task makes it worse rather than better. **The real argument is
durability**: `escaped` needs no failable task, which four calibration rounds and seven
authored tasks established is the binding constraint (§6.3, §6.4), and it does not
saturate when the model improves, which pass rate demonstrably will. That is the reason
to accept, and it is the one to lead a write-up with.

**2. The effect is concentrated in one cell, which is pilot 1's trap again.** Four of
the twin arm's six escapes are the `strict-mode × twin` cell. The bootstrap resamples
tasks whole and McNemar pairs on tasks, so the effective *n* behind H5 is **four tasks,
not twenty trials** — the same shape as the cost ordering that turned out to be one
task of four (§5.3.1). With a fixed budget, more tasks buys more here than more
repetitions.

**3. "Pass rate becomes a gate" must not be implemented as an exclusion.** Escaping
causes flailing causes failing, so dropping failed trials conditions on a variable that
escaping itself produces — a collider. It would preferentially delete escapers from
exactly the arms H5 says escape most, biasing the primary metric toward the null by an
amount that differs per arm. The registered rule therefore says *stratification, never
exclusion*: the gate is reported beside the primary metric, not applied to it.

**4. The metric did not exist.** `escape_calls` was a parameter of
`analysis/process.py:compute` that the only call site never passed, so `escaped` was
`None` on every trial ever reported, and it was absent from `PROCESS_AXES`. Every
number in §7.1's escape table was read off trajectories by hand. It is wired now: the
foreign command words are declared per arm in the study spec and ride inside the arm
digest, `escaped` is a ranked axis, and — being the only genuinely binary process
metric — it takes the same exact test the grader axes get.

Fixing the detector changed what it counts. The first version matched a foreign word
anywhere after a shell separator, which scored `grep -rn pytest .`, `which pytest` and
`echo "no pytest here"` as escapes while missing `python3 -m pytest` — the form the
pilot actually observed, four times in one trial. It now tokenizes with quoting
respected, judges the head of each command, follows `-m` and `sh -c`, and counts a
probe (`which pytest`) separately from a reach. **The pilot-2 escape counts predate all
of that and have not been recomputed under it.**

**Superseded — the floor is built.** This paragraph previously said the escape metric had
no noise floor and that a second twin would be the fix. It is now §7.1.2.

## 7.1.2 The instrument's own floor — a second twin (2026-08-11)

Amendment §7.1 item 4 says the twin-minus-`oss` contrast is the noise floor and that no
contrast is interpreted which does not exceed it. **That is wrong for the measure the
same amendment made primary.** `oss` differs from a twin in something real — it is the
familiar toolchain, which is the treatment — so the gap between them is a mixture of
effect and noise, and using it as a floor bounds the effect from above. On the outcome
axis, where every arm can fail, the mixture was tolerable. On `escaped`, where the
question is precisely whether familiar names pull an agent off its own runner, it is the
effect itself.

**A second twin is the floor that was wanted.** `twin` and `twin-b` are the `oss`
toolchain with every user-visible name replaced, from two different seeds. They are the
same treatment under two arbitrary vocabularies, so whatever separates them is the
instrument. Registered as `instrument_arms: [twin, twin-b]`, reported per axis as
`instrument_floor`, and every contrast carries `beyond_instrument_floor` — including the
refusal to score a contrast that involves one of the two floor arms, since that contrast
is partly the floor itself.

Three things this cost, all of them worth having found before spending:

1. **The first twin's vocabulary was hand-written.** §9 of this document has said since
   it was written that the twin is "generated mechanically from a seed, not
   hand-written". It was not: `kelvra`, `brivols`, `tomak`, `vess` were chosen by a
   person. Two twins produced by two different processes are not a noise floor, so both
   are now drawn by `arms/twin.py`'s own generator from a declared seed, and
   `manifest.json` records the seeds beside the words so a reader can recompute them.

2. **The twin generator emitted English words.** Its non-dictionary filter stopped at
   three letters, and the second twin promptly drew `jibe` and `tape` for two of its four
   names while the first drew none — an asymmetry in exactly the dimension the floor has
   to hold still. The filter now covers the four- and five-letter words a strict
   consonant-vowel alternation over an alphabet with no c, q, w, x or y can produce.

3. **Adding a pre-registration field moved every historic pre-registration digest.** The
   digest was taken over the full model dump, so declaring `instrument_arms` changed
   pilot 2's `sha256:4215f18f…` without one pre-registered choice having changed —
   silently voiding the guarantee §8 exists to make. Unset optional fields are now
   omitted from that digest, `None` being absence in this spec, and pilot 2's number
   recomputes exactly.

The study is now 4 tasks × 4 arms × 5 repetitions = 80 trials, roughly $16.60 at pilot
2's $0.208 per trial.

## 8. Pre-registration and analysis

Following this repository's existing discipline (`docs/execution-plan.md` §0.6), fixed before
execution and digested into the study spec:

- Primary metric, arms, repetitions, exclusion rules, and the control arm, named in advance.
- **Evidence gating.** A trial whose ADP `/verify` is not `ok: true` is `ERROR`, never pass or fail,
  and errors count against the majority in repetition verdicts.
- **Unscored ≠ zero.** A crashed grader leaves an axis unscored; an unpriced model renders
  `unpriced`. Never folded in as zero.
- **Digest mismatch ⇒ no comparison**, including duva-bench's own adapter version — added 2026-08-10
  after runs from either side of a bridge fix proved indistinguishable.
- Statistics: exact McNemar against the declared control arm with Holm correction; bootstrap CIs
  resampling **tasks whole**, seeded; pooled within-cell sd as a noise floor, with every contrast
  reported in sd units.
- **The noise floor is reported before any contrast.** With ≤ 8 tasks the study is small, and a
  difference smaller than the noise floor is not a finding no matter what the p-value says.
- Amendments permitted, dated, with the pre-amendment reading kept computable and both printed.
- **The instrument's own floor**, read between two arms that are the same treatment under
  different arbitrary names (§7.1.2), reported per axis before any contrast and never
  substituted for by the control contrast.
- **A report that scored nothing says so.** Pilot 2 produced 60 verified trials and every
  axis `null`, and its report carried no warnings at all: every individual rule was right
  — unscored is not zero, an unscored trial stays out of the numbers, a mean over nothing
  is absent — and nothing was responsible for noticing that the sum of those correct
  refusals was a report about nothing.

---

## 9. Threats to validity

| Threat | Severity | Mitigation, or admission |
|---|---|---|
| The proprietary arm is a reconstruction, not the real stack | **High, unfixable** | Reframe the question (§2); state it in the abstract; claim generalisation to *private codebases*, not to Google |
| Unfamiliarity confounded with difficulty | **High** | The twin arm (§5.3). Without it, do not run the study |
| Bazel is public, so the "OOD" arm is partly in-distribution | Medium | Expected to *shrink* the observed effect — a conservative bias. Report Bazel-specific and layout-specific failures separately |
| Cannot verify any model's training data | **High, unfixable** | Never claim a measured distribution; claim constructed novelty |
| Author bias in constructing the unfamiliar arm | **High** | Twin arms are generated mechanically from a declared seed — true since 2026-08-11 and *not* true when this row was first written, see §7.1.2. `proprietary-style` conventions must each cite a public source. Consider having the arms built by someone who does not see the hypotheses |
| Small task count | Medium | Bootstrap over tasks; report the noise floor first; treat the pilot as a pilot |
| Grader leniency (the SWE-bench failure) | Medium | Multi-axis graders, adversarial cases, oracle-must-pass admission |
| Provider-side model changes mid-study | Medium | Pin model ids; record them in run labels; refuse to compare across a changed pin |
| Cost blows up on the unfamiliar arms | Low, but real | Per-trial step and wall-clock caps, and a study-level budget cap checked before each trial |

---

## 10. What must be decided and built first

**Decisions (not mine to make):**

1. **Is the toolset axis of Study A being fixed, dropped, or deferred?** This study needs only the
   *file* half of arm materialization. Study A needs a custom Harbor agent, which collides with
   `docs/execution-plan.md` §5. The answer determines whether these are one workstream or two.
2. **Does the reframing in §2 stand?** If the goal really is a claim about Google specifically, this
   study cannot deliver it and should not be attempted.
3. **Pilot scope and budget**, before any factorial.

**Build, in order:**

1. **Wire `arms/materialize.py` into `exec/trial.py`** so an arm produces its own task variant. This
   is the blocker; nothing else here can run without it, and Study A needs it too.
2. **Extend the twin generator from tool vocabularies to toolchains** — renaming commands, config
   filenames and target syntax across a task directory rather than a tool schema.
3. **Add the escape-to-familiar metric** to `analysis/process.py`; the rename map already exists.
4. **Build the three toolchain skeletons** (`oss`, `proprietary-style`, `twin`), each a task
   template with an oracle, and admit them only when the oracle passes its own grader in all three.
5. **Author the tasks and graders**, one at a time, oracle first.
6. **Pilot**, measure the noise floor, then decide on the factorial.

Steps 1–3 are duva-bench work and are shared with Study A. Steps 4–6 are the study proper and are
where the intellectual risk lives.

---

## 11. What this study would be worth

If the twin arm shows a large effect, the finding is that **a substantial part of agent competence
is bound to identifiers rather than to engineering**, measured on real multi-step tasks with cost
and hallucination attached — which bears directly on every organisation deciding whether to point an
agent at a large private codebase, and on whether documentation is a sufficient remedy.

If the twin arm shows nothing and `proprietary-style` still lags, the finding is narrower and more
practical: the deficit is structural, and the fix is engineering the environment rather than
teaching the model names.

Both are publishable. The failure mode is running it without the twin, finding that agents do worse
on an unfamiliar stack, and having said nothing that was not already obvious.
