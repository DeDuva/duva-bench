# CLAUDE.md — duva-bench

Controlled factorial experiments over coding-agent arms — model × harness × toolset ×
task substrate — with verifiable trajectories, separately-authorized scoring, and
pre-registered statistics. Execution is delegated to **Harbor** (a container per trial,
real agent CLIs); recording and verification go to ADP.

**`ROADMAP.md` is the single status ledger** — milestone states, blockers with
verification dates, open decisions. A PR that changes milestone status updates it in
the same PR.

**Read `docs/execution-plan.md` before doing anything here.** It is the plan of record and
it is prescriptive, not descriptive:

- **§0 "Rules for the executing agent"** — one milestone per branch, one PR per milestone
  (`feat/m<N>-<slug>`), no scope invention, done-conditions are tests, and six
  non-cuttable design rules (rank per axis never blended; unscored ≠ zero; digest mismatch
  ⇒ no comparison; evidence gating; pre-registration; secrets only from the environment).
- **§2 "Toolchain and repo layout"** — fixed decisions, explicitly not to be revisited.
- **§3 "Known ADP contract traps"** — code around them; do not rediscover them.

This file only carries what that plan does not.

## State

The repo is **docs-only**: `README.md`, `docs/execution-plan.md`, `docs/html/`. There is
no code yet — M0 (scaffold) has not started. Don't infer conventions from a source tree
that isn't there; take them from §2.

**This is the Harbor track, one of two.** The **squad track** lives in the squad fork at
`packages/duva-bench` (`github.com/DeDuva/squad`, branch `dev`) and has already executed
S0–S7 including a live 24-trial pilot. The two tracks run the same tasks, graders and
statistics over different infrastructure, so **the pair is itself the experiment** — they
are deliberately parallel, and neither is a rewrite of the other.

## Process

All work lands on `main` through a pull request. Commit messages and PR bodies carry no
AI attribution.

`make check` is the gate — the same target name as in every repo in this line of work.
Until M0 lands it runs only `make check-docs`, which asserts that the paths this file
points at still exist; §2 of the plan says what `setup lint fmt types test` become when
there is code to run them against.

**Do not regenerate this file with `/init`.** It is a set of deliberate pointers into the
plan of record, and a codebase scan — of a repo with no code — would replace it with
nothing useful.

`.claude/settings.json` is checked in and holds the shared permission allowlist. Personal
overrides go in `.claude/settings.local.json`, which is ignored.

## Borrow, don't invent

§0.5 is worth repeating because it is the fastest way to get this right: two sibling
repos have already paid for these patterns.

- **`~/dev/adp-replay`** — ADP client generation from a vendored spec, spooled recording
  that never blocks a tool call, canonical digests, paired statistics, pre-registration.
- **The squad fork's `packages/squad-lab`** — harness digests, grader identity separation,
  per-axis summaries, variance and noise-floor analysis.

When the plan says "mirror X", open X and transliterate it.

## Running Harbor on this machine

The pause on this track was lifted on 2026-08-08 by a probe that ran end to end here —
container build, a real agent CLI, a real model, real cost. `docs/execution-plan.md`
§"Reproducing it" has the exact commands. Two things that cost time before:

- **Use the uv-managed CPython 3.12**, not system `python3` (3.14, no `ensurepip`, so
  `python3 -m venv` fails and would need `sudo apt`). The belief that "nothing can be
  installed here" came from exactly that and was wrong for three days.
- **Pin the dataset version.** Bare `terminal-bench-core` resolves to `head`, whose layout
  the registry client fails to unpack (`FileNotFoundError: .../tasks`).
