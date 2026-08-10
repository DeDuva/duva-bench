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

**Gate G1 passed on 2026-08-10; G2 and G3 have not run.** One real trial went through
Harbor to a live ADP with a signed attestation. No *study* has been executed, so nothing
here is yet a result about any agent.

The distinction the ledger draws, and that you must keep drawing: *code landed* is not
*gate passed*. When you touch a milestone, do not describe it as done because its tests
are green; `ROADMAP.md` says which of the two it is.

**Read `docs/blockers.md` before writing anything that talks to Harbor or ADP.** Closing
G1 took seven defects out of code that had 325 passing tests, and six of them were the
same mistake: a plausible reading of another program's interface, pinned by a fixture
written from the same reading. A fixture you wrote tests your reading, not the program.
Where the counterpart is a program rather than a document, at least one test has to talk
to it — `tests/test_harbor_cli.py` checks the adapter's flags against `harbor run --help`,
and `tests/test_bridge.py` bridges a trajectory a real agent actually wrote.

**The next milestone is gate G2** — the eight-trial smoke study, `run` then `report`, with
every number reconciled against a direct ADP read. `docs/g1-runbook.md` is the record of
how G1 was closed and is the model for doing G2.

**This is the Harbor track, one of two.** The **squad track** lives in the squad fork at
`packages/duva-bench` (`github.com/DeDuva/squad`, branch `dev`) and has already executed
S0–S7 including a live 24-trial pilot. The two tracks run the same tasks, graders and
statistics over different infrastructure, so **the pair is itself the experiment** — they
are deliberately parallel, and neither is a rewrite of the other.

## Process

All work lands on `main` through a pull request. Commit messages and PR bodies carry no
AI attribution.

`make check` is the gate — the same target name as in every repo in this line of work.
It runs `check-docs lint types check-generated test`. Two suites are deliberately outside
it, because a suite that skips on a missing dependency reports a pass and an untested path
with the same exit code:

- `make test-contract` — needs a live ADP (`DUVA_ADP_BASE_URL` and both tokens). Has
  **never been run**. `adp/models.py` is hand-written from ADP's source, so these tests
  are the only thing that can say whether it is right.
- the `harbor` marker — needs Harbor and a container runtime. Currently used by **zero**
  tests, which means excluding it excludes nothing. Closing G1 should change that.

**Do not regenerate this file with `/init`.** It is a set of deliberate pointers into the
plan of record; a codebase scan would replace them with a description of the source tree,
which is the one thing you can already get by reading the source tree.

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
