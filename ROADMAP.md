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

## Milestone ledger

| Milestone | Status | Evidence / detail |
|---|---|---|
| *Track pause* | *lifted 2026-08-08* | Paused earlier because dependencies could not be configured from a remote session; a probe on 2026-08-08 ran Harbor end to end here twice (oracle + a real `claude-code` trial, $0.28) — see the plan's "Track status" section |
| M0 — scaffold | not started | The next work. Entry condition: none — unblocked |
| M1 — study spec and digest | not started | |
| M2 — ADP recording core | not started | Must take cost/tokens from the agent log, not Harbor's summary (probe finding: `results.json` reports zero tokens for `claude-code`) |
| M3 — one Harbor trial end to end | not started | **Gate G1 (hard stop)** — one real trial, verified ADP run, bridged events |
| M4 — arms and twin instruments | not started | |
| M5 — factorial scheduler | not started | |
| M6 — analysis and report | not started | **Gate G2 (hard stop)** |
| M7 — API server and web UX | not started | |
| M8 — Study A, for real | not started | **Gate G3 (hard stop).** Reaching M8 with a shared task set is the stated precondition of the squad track's cross-track memo (its gate SG3b) |

## Now / Next / Later

- **Now:** nothing in flight. The repo is docs-only; there is no code yet.
- **Next:** M0 (scaffold), then the milestones strictly in order — one milestone per
  branch, one PR per milestone (`feat/m<N>-<slug>`), per the plan's §0 rules.
- **Later:** post-M8 — squad-as-an-arm via a Harbor adapter, per the plan's exclusions.

## Blockers and open decisions

- **None blocking M0–M2.** Verified 2026-08-08 by the end-to-end probe: container
  build, image pulls, a real agent CLI against a real model, provider config — all work
  on this machine.
- **Multi-CLI arms (M4+) need more agent CLIs.** Verified 2026-08-08: only `claude` is
  installed locally; `codex` and `aider` are absent. Install them before designing
  multi-CLI arms, or scope arms to what is present.
- **Harbor token accounting is wrong for `claude-code`** (verified 2026-08-08:
  `total_input_tokens: 0` in `results.json` while the agent log carried full usage).
  Not a blocker — M2 codes around it — but a constraint every cost figure depends on.

## Plan documents

- [`docs/execution-plan.md`](docs/execution-plan.md) — the plan of record: agent rules
  (§0), fixed toolchain decisions (§2), known ADP contract traps (§3), milestones
  M0–M8 with done-conditions and gates.
- `docs/html/` — the published "Why duva-bench" page: motivation and prior art.
- The squad track's plan: `packages/duva-bench/PLAN.md` on the squad fork's `dev`
  branch. The cross-track hypothesis is registered in that package's
  `studies/a-tool-familiarity-pilot/CROSS-TRACK.md` — written before any data existed.
