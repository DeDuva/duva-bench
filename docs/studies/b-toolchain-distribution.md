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

---

## 9. Threats to validity

| Threat | Severity | Mitigation, or admission |
|---|---|---|
| The proprietary arm is a reconstruction, not the real stack | **High, unfixable** | Reframe the question (§2); state it in the abstract; claim generalisation to *private codebases*, not to Google |
| Unfamiliarity confounded with difficulty | **High** | The twin arm (§5.3). Without it, do not run the study |
| Bazel is public, so the "OOD" arm is partly in-distribution | Medium | Expected to *shrink* the observed effect — a conservative bias. Report Bazel-specific and layout-specific failures separately |
| Cannot verify any model's training data | **High, unfixable** | Never claim a measured distribution; claim constructed novelty |
| Author bias in constructing the unfamiliar arm | **High** | Twin arm is generated mechanically from a seed, not hand-written. `proprietary-style` conventions must each cite a public source. Consider having the arms built by someone who does not see the hypotheses |
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
