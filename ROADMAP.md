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
| M4 — arms and twin instruments | code landed | Twin generator, doc bundles, grader runner with a stripped environment |
| M5 — factorial scheduler | code landed | Budget cap, per-provider pacing, resumable via `progress.jsonl` |
| M6 — analysis and report | code landed, **gate G2 not run** | **The next milestone.** Reconciliation is proven against the in-memory ADP double, not a server |
| M7 — API server and web UX | code landed | Playwright walk passes against `scripts/dev-server.py`'s ADP double, not a real study |
| M8 — Study A, for real | **defined, not executed** | `studies/a-tool-familiarity/` — 16 arms × 6 tasks × 5 reps = 480 trials, digest `sha256:5c83036c…`. **Gate G3.** Reaching it with a shared task set is the stated precondition of the squad track's cross-track memo (its gate SG3b) |

## Now / Next / Later

- **Now:** nothing in flight. Gate G1 closed on 2026-08-10, and G2's three preconditions
  were settled the same day — the eight-trial factorial has been rehearsed end to end with
  oracle arms (`examples/smoke/study-oracle.yaml`), so what remains is running it with a
  model.
- **Next:** **gate G2** — the same eight trials against `examples/smoke/study.yaml`, with
  every number in the report reconciled against a direct ADP read by a test. Expect roughly
  **$0.45** at the $0.054 a G1 trial cost, well under the study's $5 cap. Settle the
  `unpriced_trials` open decision below first; it changes what the report prints.
- **Later:** G3 (Study A, 480 trials). Post-M8, squad-as-an-arm via a Harbor adapter.

## Blockers and open decisions

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
- **Open decision — `total_usd: 0.0` prints beside `unpriced_trials: 8`.** In the oracle
  rehearsal the report's cost block read `total_usd: 0.0` with all eight trials unpriced. For an
  oracle that is true, since nothing was called. For a *model* whose price is unknown it would be
  the failure execution-plan §0.6 forbids by name — an unpriced model rendering as zero rather
  than as `unpriced`. Decide before G2 whether the total should refuse to render a number when
  `unpriced_trials > 0`.
- **Multi-CLI arms (M4+) need more agent CLIs.** Verified 2026-08-08: only `claude` is
  installed locally; `codex` and `aider` are absent. Install them before designing
  multi-CLI arms, or scope arms to what is present.
- **Open decision — Study A's cost has never been estimated.** 480 trials at the probe's
  $0.28 is roughly $135 in model spend before retries, plus hours of container wall
  clock. Estimate it properly at G2, not at G3.

## Plan documents

- [`docs/execution-plan.md`](docs/execution-plan.md) — the plan of record: agent rules
  (§0), fixed toolchain decisions (§2), known ADP contract traps (§3), milestones
  M0–M8 with done-conditions and gates.
- [`docs/g1-runbook.md`](docs/g1-runbook.md) — how gate G1 was closed, step by step; kept
  as the model for G2, which needs the same environment.
- [`docs/blockers.md`](docs/blockers.md) — G1's evidence and the seven defects it took;
  what G2 and G3 are still missing.
- [`docs/adp-contract-findings.md`](docs/adp-contract-findings.md) — how ADP's contract
  actually behaves, now confirmed against a live server rather than read from its source.
- `docs/html/` — the published "Why duva-bench" page: motivation and prior art.
- The squad track's plan: `packages/duva-bench/PLAN.md` on the squad fork's `dev`
  branch. The cross-track hypothesis is registered in that package's
  `studies/a-tool-familiarity-pilot/CROSS-TRACK.md` — written before any data existed.
