# duva-bench

Controlled experiments for coding agents. duva-bench lets a researcher **define, execute, and
analyze** factorial studies over coding-agent arms — model × harness × toolset × task substrate —
with verifiable trajectories, separately-authorized scoring, and pre-registered statistics.

Benchmarks rank agents. duva-bench isolates *why* one arm beats another, and produces evidence a
third party can re-verify rather than a number they have to trust.

**Status: M0–M8 built; gates G1, G2 and G3 unproven.** Every milestone of the
[execution plan](docs/execution-plan.md) has code and tests, and `make check` passes. What none of
it has is the evidence its gates demand: no trial has been executed against a real container, a
real model and a live ADP, so **nothing here claims to have produced a result.**
[`docs/blockers.md`](docs/blockers.md) says exactly what each gate is still missing.

This repo is the **Harbor track**, one of two tracks meant to run in parallel; the **squad track**
(`github.com/DeDuva/squad`, `packages/duva-bench`) has executed S0–S7 including a live pilot. This
track was paused because its dependencies could not be configured from a remote session, and all of
the code above was written under that pause. **A probe on 2026-08-08 ran Harbor end to end on the
development machine — container build, a real agent CLI, a real model, real cost — and nothing
blocked.** See [Track status](docs/execution-plan.md#the-2026-08-08-probe--the-record-that-lifted-the-pause)
for the probe, how to reproduce it, and two defects it surfaced.
[`ROADMAP.md`](ROADMAP.md) is the status ledger.

The ["Why duva-bench" page](docs/html/index.html) (published via GitHub Pages) carries the full
motivation, the prior-art survey, and the case for the architecture.

```sh
pip install -e ".[dev,server]"          # add [harbor] to execute trials (needs Python >= 3.12)

duva-bench validate examples/smoke/study.yaml
duva-bench digest   examples/smoke/study.yaml
duva-bench preflight examples/smoke/study.yaml   # checks the ADP contract and identity separation
duva-bench run      examples/smoke/study.yaml    # resumable, budget-capped, rate-limited
duva-bench report   examples/smoke/study.yaml    # report.json + a self-contained report.html
duva-bench serve                                 # the JSON API the web UX is a client of
```

| | |
|---|---|
| study spec, canonical digest, pre-registration | `src/duva_bench/study/` |
| ADP client, spool, recorder, evidence gate | `src/duva_bench/adp/` |
| Harbor adapter and the ATIF → ADP trace bridge | `src/duva_bench/exec/` |
| semantic twins, docs bundles, arm materialization | `src/duva_bench/arms/` |
| grader invocation under a stripped environment | `src/duva_bench/grading/` |
| outcomes from ADP, process metrics, statistics | `src/duva_bench/analysis/` |
| report.json and the static HTML report | `src/duva_bench/report/` |
| JSON API and SSE | `src/duva_bench/server/`, `web/` |
| Study A, defined and unexecuted | `studies/a-tool-familiarity/` |
| what ADP's contract actually does | [`docs/adp-contract-findings.md`](docs/adp-contract-findings.md) |

## What it does

```
study.yaml ──▶ duva-bench (CLI / API / web UX)
                 │  materialize per-arm task variants (semantic twins, doc bundles)
                 ▼
               Harbor ── container per trial, real agent CLIs
                 │        (Claude Code, Codex CLI, OpenHands, …)
                 ▼
               trace adapter ──▶ ADP  (hash-chained trajectories, attested run labels,
                 │                     multi-axis evals, GET /verify)
                 ▼
               analysis ──▶ report  (per-cell tables, CIs, noise floor, process metrics)
```

- **Scriptable**: everything is drivable from the CLI and a JSON API; the web UX is a client of the
  same API, never a second path.
- **A study is data**: a content-digested spec (tasks, arms, repetitions, budget, and a
  pre-registered analysis block). The digest rides on every run as an ADP label, so a result is
  permanently bound to the exact study definition that produced it.
- **An arm is attested, not annotated**: model, harness, toolset, and docs-bundle identity are
  digested and recorded inside ADP's signed run attestation.
- **Evidence-gated**: a run whose ADP `/verify` is not `ok` becomes an ERROR, never a pass or fail.
- **Separately scored**: graders run under a distinct ADP identity; a run structurally cannot score
  itself.

## Why Harbor + ADP

**[Harbor](https://harbor-framework-harbor.mintlify.app/introduction)** (the harness behind
[Terminal-Bench 2.0](https://openreview.net/pdf/417ac3236de7dbf3fc3414c51754dd239271663e.pdf))
already does what an experiment executor must do — a fresh container per trial, adapters for real
agent CLIs, trace collection, 32–100-way parallelism, and a task format 26 existing benchmarks have
been adapted into. Building that ourselves would be recreating a maintained wheel; every hour spent
there is an hour not spent on the science.

**[ADP](https://github.com/DeDuva/adp)** is the system of record: hash-chained per-event
trajectories, DSSE-signed run attestations that bind arm labels to the trajectory digest and final
git sha, multi-axis evals with content-addressed specs and reporter-identity checks, and a
`/verify` endpoint that makes every claim falsifiable by anyone with a read token. No mature
alternative offers tamper-evident, independently verifiable experiment records.

duva-bench is the layer neither provides: study definition, arm construction (including the
semantic-twin instruments), factorial scheduling, pre-registered statistics, and the researcher UX.

## Relationship to sibling projects

- **[adp](https://github.com/DeDuva/adp)** — the trust plane duva-bench records to.
- **adp-replay** — the methodological ancestor: its pre-registration discipline, evidence gating,
  dual-principal scoring, and seeded paired statistics are adopted here; its replay machinery is not.
- **squad / squad-lab** — the experimental ancestor: its harness-digest and grader-identity designs
  (and four documented incidents of harness defects masquerading as model deficiencies) shaped
  duva-bench's arm-integrity rules. Squad's orchestrator is a candidate *arm*, not a dependency.

## License

[Apache-2.0](LICENSE)
