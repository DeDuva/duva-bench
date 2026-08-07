# duva-bench

Controlled experiments for coding agents. duva-bench lets a researcher **define, execute, and
analyze** factorial studies over coding-agent arms — model × harness × toolset × task substrate —
with verifiable trajectories, separately-authorized scoring, and pre-registered statistics.

Benchmarks rank agents. duva-bench isolates *why* one arm beats another, and produces evidence a
third party can re-verify rather than a number they have to trust.

**Status: pre-M0.** The [execution plan](docs/execution-plan.md) is the plan of record; the
["Why duva-bench" page](docs/html/index.html) (published via GitHub Pages) carries the full
motivation, the prior-art survey, and the case for the architecture.

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
