# duva-bench (Harbor track) — Roadmap

**This file is the repo's only status ledger.** A PR that completes, starts, pauses, or
supersedes a milestone updates this file in the same PR. Scope is decided by the plan of
record, [`docs/execution-plan.md`](docs/execution-plan.md) — this file says where the
track is, not how the next piece gets built.

## Mission

Define, execute, and analyze controlled factorial experiments over coding-agent arms —
model × harness × toolset × docs × environment — with execution delegated to **Harbor**
(a container per trial, real agent CLIs), every trial recorded as a verified ADP run,
and analysis under pre-registered statistics.

## Where this fits

This is the **Harbor track**, one of two deliberately parallel duva-bench tracks — the
pair is itself an experiment (bespoke vs in-distribution infrastructure). The **squad
track** lives in the squad fork (`github.com/DeDuva/squad`, `packages/duva-bench`) and
has executed S0–S7 including a live pilot. Both tracks record to ADP and share tasks,
graders, and adp-replay's statistics library. The dependency map is ADP's
`docs/ecosystem.md`.

## Read this before the table

**Code exists for every milestone; one gate of three has been run.** M0–M8 were written in
one long branch during the track pause, when no container runtime, no model and no live ADP
were reachable from the session doing the work. That branch was rebased onto `main` and
landed as a single PR rather than replayed as nine — the code is real and `make check` passes
over it, but it was never held to the plan's one-milestone-per-branch rule and there is no
milestone-by-milestone review history behind it.

So the ledger below distinguishes two things the plan's done-conditions normally fuse:

- **code landed** — the deliverable exists, `make check` covers it, its unit tests pass.
- **gate passed** — the milestone's real-world done-condition has been demonstrated with
  evidence anyone can re-check.

The distinction is not pedantry. **Gate G1 passed on 2026-08-10, and closing it took seven
defects out of code that had 325 passing tests** — six of them assumptions about another
program's interface, pinned by fixtures written from the same assumptions. Every milestone
still marked *code landed* carries exactly that risk.

**No study has been executed.** One trial has run end to end; `duva-bench run` and
`duva-bench report` have not, so nothing on this track is yet a result about any agent.

## Milestone ledger

| Milestone | Status | Evidence / detail |
|---|---|---|
| *Track pause* | *lifted 2026-08-08* | A probe ran Harbor end to end on the development machine twice (oracle + a real `claude-code` trial, $0.28) — see the plan's probe section |
| M0 — scaffold | code landed | Package, CLI, `make check`, CI on 3.11 + 3.12 |
| M1 — study spec and digest | code landed | `examples/smoke/study.yaml` validates; digest `sha256:d1a38ec0…` |
| M2 — ADP recording core | code landed, **contract suite passes** | 13/13 against a live ADP at contract `0.2.0` (2026-08-10, first ever run — 5 failed initially). `adp/models.py` is hand-written from ADP's *source*; `tests/fakes.py` reproduced the same misreading and now enforces the server's rules |
| M3 — one Harbor trial end to end | **gate G1 PASSED 2026-08-10** | Run `a5c20876-d5ff-41af-95b5-114c9a8fddb6`: `ok`, `envelope_verified`, `trajectory_digest_matches` all true; 13 labels round-trip; **17 bridged `tool_call` events**. Took seven real defects to get there — see [`docs/blockers.md`](docs/blockers.md) |
| M4 — arms and twin instruments | code landed, **wired 2026-08-10** | Twin generator, doc bundles, grader runner. Materialization now installs an arm's toolset into the task image and declares it in `task.toml`, which is the only place Harbor reads tools from; a spike proved an agent calls the renamed tools under the names the arm chose. Not yet exercised by a study — see [`docs/blockers.md`](docs/blockers.md) |
| M5 — factorial scheduler | code landed | Budget cap, per-provider pacing, resumable via `progress.jsonl` |
| M6 — analysis and report | **gate G2 PASSED 2026-08-10** | Study `sha256:e53d00ed…`, 8/8 trials, 0 errors, $0.468609, 5m48s at concurrency 2, against the dedicated ADP. Report reconciles with a direct ADP read by test; unscored axes render unscored; a tampered run is `ERROR`. Took four attempts — three were destroyed by an ADP another workstream reset |
| M7 — API server and web UX | code landed | Playwright walk passes against `scripts/dev-server.py`'s ADP double, not a real study |
| M8 — Study A, for real | **defined, not executed** | `studies/a-tool-familiarity/` — 16 arms × 6 tasks × 5 reps = 480 trials, digest `sha256:5c83036c…`. **Gate G3.** Reaching it with a shared task set is the stated precondition of the squad track's cross-track memo (its gate SG3b) |

## Now / Next / Later

- **Now:** wiring and evidence for Study B's amended primary measure. The decision is
  settled (below); what is left is the noise floor it needs and a report artifact its
  numbers can be re-derived from.
- **~~Next — a decision, not a task~~ — settled 2026-08-11.** Study B's
  [**amendment §7.1**](docs/studies/b-toolchain-distribution.md) is **accepted and
  registered**: the primary measure is `process:escaped` (did a trial invoke a toolchain
  its arm was not given), pass rate is a gate *reported beside* it rather than applied to
  it, and **H5 — partial unfamiliarity costs more than total unfamiliarity** is registered
  untested. `study.yaml` carries it as three `Amendment` records and the pre-amendment
  reading recomputes to the digest pilot 2 ran under. §7.1.1 records what accepting it
  corrected — chiefly that the power argument is weaker than §7.1 claimed (H5's own leg
  needs ~120 trials/arm against pass rate's ~250, a 40% saving rather than an order of
  magnitude) and that the load-bearing argument is durability: `escaped` needs no failable
  task, and does not saturate when the model improves.
- **Next:** the two things the amendment left open — a **noise floor** for `escaped`
  (a second twin on a different rename seed) and a **re-derivable pilot-2 report**. Both
  are below.
- **Then:** a run on **fresh tasks**, spending on *more tasks rather than more
  repetitions*. H5 was generated by looking at pilot 2 after the fact and cannot be tested
  on the data that suggested it; and the effect it rests on was four of six events in a
  single cell, while the statistics resample tasks whole.
- **Not next:** the factorial. Both pilots exist to say when it is worth its money and
  neither says yet.
- **Later:** Study A, whose toolset axis turned out to be reachable through MCP task config
  after all — decide it on Study B's evidence rather than on convenience, since the squad
  track has a pre-registered hypothesis waiting on it. Then G3. Post-M8, squad-as-an-arm.

## What the two pilots established

Recorded here because it is what the amended design is built on.

| | pilot 1 (`sonnet-4-5`, 24 trials, $2.16) | pilot 2 (`haiku-4-5`, 60 trials, $12.49) |
|---|---|---|
| outcome axis | every arm solved every task — pooled sd `0.0` | oss 0.850, twin **0.950**, proprietary 0.850 |
| aggregate cost | ordering matched the hypothesis, and was one task of four | within-cell CV **0.62**; twin 50% above oss |
| behaviour | not measured | oss escaped 0/20, twin **6/20**, proprietary 3/20 |

The twin arm differs from `oss` only in names, so **twin-minus-oss reads measurement noise
directly** — 0.10 on the outcome axis and ~50% on cost, both larger than the
oss-to-proprietary difference. Only the behavioural measure separated the arms at n=20.

**Two caveats travel with that last row, and neither is small.** Four of the twin arm's six
escapes are one cell (`strict-mode × twin`), so the effective *n* behind it is four tasks
rather than twenty trials — the same shape as pilot 1's cost ordering that turned out to be
one task of four. And the counts were read off trajectories by hand under a matcher that
scored `grep -rn pytest .` as an escape and missed `python3 -m pytest`; the detector has
since been rewritten and **the row has not been recomputed under it**.

Seven tasks were authored, three built specifically to be failable, and on `sonnet-4-5` none
discriminates. Across four calibration rounds **every point of apparent difficulty turned out
to be an authoring defect** — see `docs/studies/b-toolchain-distribution.md` §6.2–§6.4. The
tooling that now prevents a repeat is `studies/b-toolchain-distribution/calibrate.py` (pass
rate *with the reason for every failure*) and `tests/test_study_b_specs.py` (the oracle and a
deliberately different correct implementation must both satisfy each acceptance check).

## Blockers and open decisions

- **~~Study B's primary measure was an open decision~~ — settled 2026-08-11.** Amendment
  §7.1 is accepted and registered: the primary metric is `process:escaped`, pass rate is
  a gate reported as a stratification, and H5 is registered untested. The pre-amendment
  reading recomputes to the digest pilot 2 ran under, pinned by a test. What accepting it
  corrected is in the design document's §7.1.1 — chiefly that the power argument is
  weaker than §7.1 claimed (H5's own leg needs ~120 trials/arm against pass rate's ~250,
  a 40% saving rather than an order of magnitude), and that the durability argument is
  the load-bearing one.

- **~~The escape metric has no noise floor~~ — built 2026-08-11.** `twin` and `twin-b`
  are the `oss` toolchain renamed from two different seeds: the same treatment under two
  arbitrary vocabularies, so the gap between them is the instrument's own noise. Declared
  as `instrument_arms`, reported per axis as `instrument_floor`, and every contrast now
  carries `beyond_instrument_floor` — which refuses to score a contrast involving either
  floor arm, that contrast being partly the floor itself. Design document §7.1.2 records
  the three defects it surfaced: the first twin's vocabulary was hand-written while §9
  claimed it was seeded, the generator's non-dictionary filter stopped at three letters
  and promptly emitted `jibe` and `tape`, and adding a pre-registration field moved every
  historic pre-registration digest. **The study is now 80 trials, ~$16.60.**

- **Pilot 2's evidence is gone, and every number this ledger quotes from it is
  currently unverifiable.** Three things were each true and are no longer jointly
  survivable:

  1. the committed artifact `studies/b-toolchain-distribution/report/report.json` is the
     **pre-fix** one — 120 of 120 axis scores are `null`;
  2. the ADP evals for that study were left unscored deliberately and never re-posted,
     and that ADP instance is ephemeral;
  3. the local artifacts the re-grade ran over — recorded here on 2026-08-11 as
     "preserved under `.duva-bench/`" — **are not on this machine.** `.duva-bench/` is
     gitignored and exists nowhere under `/`; verified 2026-08-11.

  So oss 0.850 / twin 0.950 / proprietary 0.850, the within-cell CV of 0.62, and the
  0/20 · 6/20 · 3/20 escape row have no artifact behind them anywhere. They are the
  stated rationale for amendment §7.1. **Recovering them means re-running the pilot
  (~$12.49), not re-running `report`** — and the escape row would not come back
  identical in any case, because the detector has been rewritten since it was counted
  by hand.

  The lesson is one this ledger has now paid for twice: a run's evidence is durable
  only where it is committed. A study's report belongs under `studies/<id>/report/`,
  written from the run rather than from a session's scratch, and written *after* the
  scores are known to be real.

  **What has been done about it, 2026-08-11.** The recovery cannot be done — nothing
  short of re-running the pilot produces those numbers — but the failure that made them
  worthless is now caught. Pilot 2's report carried **no warnings at all** beside 60
  verified trials and 120 null scores: every rule behaved correctly and nothing was
  responsible for noticing that the sum of those correct refusals was a report about
  nothing. A grader axis with no scored trial in any arm, and a study with no grader axis
  at all, are both loud warnings now, in the JSON and on the page. Two tests in
  `tests/test_report.py` reproduce pilot 2's exact shape — graders that ran, posted their
  axes, and scored `null`.

- **~~`task substrate` was a factor with nowhere to put it~~ — added 2026-08-10.** The
  README has named `model × harness × toolset × task substrate` since the first commit, and
  an arm could vary everything but the last: every arm ran byte-identical task files.
  `TaskRef.substrates` now maps a substrate name to a path and `Arm.substrate` picks one, so
  Study B's manipulation — the toolchain a problem is posed in — is expressible. An arm that
  names no substrate for a task that has them is refused rather than given an arbitrary one.
  Digests moved again, for the third time today and for the same good reason.

- **None blocking G2.** Verified 2026-08-10 by closing G1 on this machine: Docker 29.1.3,
  `harbor==0.20.0`, a live ADP at contract `0.2.0`, provider credentials, a verified run
  with a signed attestation and a graded pair of axes.
- **~~Study A's six tasks are unverified~~ — settled 2026-08-10.** All eight tasks in the
  repository now run through Harbor with the `oracle` agent and satisfy their own graders on
  every axis: image builds, verifier reward file, artifact collection and grading, end to end.
  Pinned by `tests/test_tasks_through_harbor.py` (marked `harbor`; no model spend). A task
  that passes there can still be failed by a real agent — that is the study — but a *broken*
  task can no longer be mistaken for a failing arm.
- **~~Concurrency is unmeasured~~ — settled 2026-08-10.** The eight-trial factorial ran
  through the real scheduler at concurrency 2 in 1m22s with 0 errors, using the oracle arms in
  `examples/smoke/study-oracle.yaml`. **A trial is two containers, so concurrency N means 2N** —
  Study A at concurrency 8 is 16 containers. Scheduler peak RSS 224 MB; 12.2 GB free throughout;
  no measurable container-disk growth.
- **~~Cost accounting unreconciled~~ — settled 2026-08-10.** `terminus-2` reports per-step usage
  that sums exactly to the trajectory's own `final_metrics` (13,297 prompt / 2,126 completion /
  $0.0521659), and ADP reports the same. Pinned by two tests in `tests/test_bridge.py`, one of
  which asserts cached tokens are not double-counted into the prompt total — 8,384 of those
  13,297 were cache reads, so getting it wrong would inflate input by 60% and worsen with
  exactly the caching that makes long studies affordable. **This does not clear
  `claude-code`**, whose zero-token defect started this; it clears the agent Study A uses.
- **The ADP contract suite has never run in CI.** It passes locally against a live server;
  `.github/workflows/adp-contract.yml` has not executed. Until it does, the contract is
  pinned by a suite one person runs by hand.
- **~~Studies cannot share the ADP dev stack~~ — fixed 2026-08-10.** Three G2 runs were
  destroyed by another workstream's `make up` in `~/dev/adp`. Studies now record into their
  own instance: `make adp-stack` (`tools/adp-stack.sh`) — its own worktree, a compose
  project outside the `adp-test-*` sweep, and the built server on port 3100 rather than
  `tsx watch`, which was restarting mid-trial because ADP's `GIT_ROOT` sits inside its own
  checkout and duva-bench publishes a commit per trial.
- **The smoke study's `hallucinated_call_rate` is 1.0 by construction.** It declares
  `read_file`/`write_file`/`run_command` with placeholder digests, supplies none of them,
  and `terminus-2` calls `bash_command`. Now fixable either way — give it a real toolset via
  `definition_path`, or stop declaring tools it does not supply so the metric renders
  not-applicable. Deferred because it moves the study digest and would supersede G2's
  evidence again.
- **Study B pilot 2's ADP evals are unscored.** All 60 trials verified and every axis came
  back `null`: the grader searched for `report.py` after packages had become
  `report/__init__.py`. The trials were re-graded locally and **the evals recorded in ADP
  for that study remain unscored**, having deliberately not been quietly re-posted.
  `tests/test_study_b_specs.py` now runs a grader against the tree a finished trial
  leaves, in all three layouts. **Correction, 2026-08-11:** this bullet previously said
  the artifacts were preserved under `.duva-bench/` and so the re-graded numbers were
  still real. They are not on this machine — see the entry above. A claim that evidence
  is preserved is worth exactly as much as a check that it still is.
- **The local ADP is ephemeral, so a cited run id is reproducible rather than durable.**
  G1's evidence lives in the `adp-test-*` stack that `make down` destroys, and this
  machine's `/tmp` is cleared between sessions. Anyone re-checking a run id in
  `docs/blockers.md` has to re-run the trial, not fetch the record. A durable instance
  is what would make these claims independently verifiable, which is the whole point of
  recording to ADP; worth solving before Study A's results are cited anywhere.
- **~~`total_usd: 0.0` beside `unpriced_trials: 8`~~ — fixed 2026-08-10.** The oracle rehearsal
  printed exactly that. It was not an open decision but a §0.6 violation: the cost block summed
  every trial, folding unpriced ones in as zero, so a model whose price nobody had would have
  understated a study's cost silently and by an unknown amount. A total is now stated only when
  every trial is priced — otherwise `total_usd` is `null` and `priced_usd` carries what is known.
  Same rule per arm, because an arm is what gets compared. Three tests in `tests/test_report.py`.
- **Residual: `cost_micro_usd` is typed `int`, so a genuine zero and "no cost reported" are the
  same value.** "Unpriced" is currently inferred from falsiness. That is correct for everything
  this project can produce today — a priced model call is never exactly zero — and wrong in
  principle. Making it `int | None` reaches back through `analysis/extract.py` into the ADP
  response models, and ADP itself may not distinguish the two. Worth doing before any arm runs on
  a model whose pricing is unknown; not worth blocking G2 on.
- **Multi-CLI arms (M4+) need more agent CLIs.** Verified 2026-08-08: only `claude` is
  installed locally; `codex` and `aider` are absent. Install them before designing
  multi-CLI arms, or scope arms to what is present.
- **Open decision — Study A's cost has never been estimated.** 480 trials at the probe's
  $0.28 is roughly $135 in model spend before retries, plus hours of container wall
  clock. Estimate it properly at G2, not at G3.

## What has been spent, and on what

Recorded because a study's cost is part of its design, and because three runs were paid
for twice.

| | |
|---|---|
| Gate G1 — first verified trial | ~$0.25 |
| Gate G2 — three runs destroyed by a shared ADP | ~$0.43 |
| Gate G2 — the run that stood | $0.4686 |
| MCP spike (toolset axis reachable) | ~$0.20 |
| Study B first task, three toolchains | $0.21 |
| Study B pilot, 24 trials | $2.156 |
| Task calibration, four rounds | $11.13 |
| Study B pilot 2, 60 trials on `haiku-4-5` | $12.486 |

Oracle runs — every task admitted, every variant checked — cost **$0** by construction:
the oracle agent runs the task's own solution instead of a model.

## Plan documents

- [`docs/execution-plan.md`](docs/execution-plan.md) — the plan of record: agent rules
  (§0), fixed toolchain decisions (§2), known ADP contract traps (§3), milestones
  M0–M8 with done-conditions and gates.
- [`docs/g1-runbook.md`](docs/g1-runbook.md) — how gate G1 was closed, step by step; kept
  as the model for G2, which needs the same environment.
- [`docs/studies/b-toolchain-distribution.md`](docs/studies/b-toolchain-distribution.md) —
  design for a second study: in-distribution toolchains against a proprietary-style stack.
  **Design only, not registered.** Harbor supports it — the factor is the container, not the
  agent's tool vocabulary — but it needs the same arm-materialization wiring Study A does.
- [`docs/blockers.md`](docs/blockers.md) — G1's evidence and the seven defects it took;
  what G2 and G3 are still missing.
- [`docs/adp-contract-findings.md`](docs/adp-contract-findings.md) — how ADP's contract
  actually behaves, now confirmed against a live server rather than read from its source.
- `docs/html/` — the published "Why duva-bench" page: motivation and prior art.
- The squad track's plan: `packages/duva-bench/PLAN.md` on the squad fork's `dev`
  branch. The cross-track hypothesis is registered in that package's
  `studies/a-tool-familiarity-pilot/CROSS-TRACK.md` — written before any data existed.
