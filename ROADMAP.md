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

- **Now:** building Study B a task set whose outcome axis actually varies, and measuring
  difficulty rather than asserting it. `calibrate.py` runs a candidate on the `oss`
  substrate alone and reports its pass rate; a task is admitted on that number.
  First results: `topo-order` 2/3, `merge-config` 1/3, `window-stats` 3/3 (hardened and
  being re-measured). Details in
  [`studies/b-toolchain-distribution/README.md`](studies/b-toolchain-distribution/README.md).
- **Next:** the pilot proper on the surviving tasks, with enough repetitions per cell for a
  variance rather than a spread.
- **Not next:** the factorial. The 2026-08-10 pilot exists to say when that is worth its
  money and it said not yet — every arm solved every task twice, pooled within-cell sd 0.0,
  and an aggregate cost ordering that turned out to be one task of four.
- **Later:** Study A, whose axis turned out to be reachable through MCP after all — decide it
  on Study B's evidence rather than on convenience, since a sibling project has a
  pre-registered hypothesis waiting on it. Then G3. Post-M8, squad-as-an-arm.

## Blockers and open decisions

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
| Task calibration, first pass | $1.434 |

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
