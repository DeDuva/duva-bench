# duva-bench — Execution Plan (v0.1)

An execution-grade plan for building duva-bench. Tasks are written to be followed **in order** by an
AI coding agent (Sonnet-class) or a junior engineer **without requiring strategic context**. Each
task states its deliverable and its done-condition. Gates are hard stops: do not begin work past a
gate until the gate passes.

**Motivation, prior art, and the case for this architecture live in `docs/html/index.html`** (the
published "Why duva-bench" page). This document is only *how to build it*.

---

## The 2026-08-08 probe — the record that lifted the pause

> **Status lives in [`/ROADMAP.md`](../ROADMAP.md)** — the repo's single status ledger,
> updated in the same PR as any status change. What follows here is the durable record
> of the probe that lifted this track's pause, kept in the plan because M0–M2 build
> directly on its findings.

duva-bench has **two tracks, meant to run in parallel** — bespoke infrastructure
(squad) against in-distribution infrastructure (Harbor), on the same tasks,
graders and statistics, so **the pair of tracks is itself an experiment**. This
track was paused because its dependencies could not be configured from a remote
session. That was a real constraint and the pause was the right call. It no
longer holds, and the reason is worth recording: the belief that nothing could
be installed came from the **system** Python being 3.14 with no `ensurepip`, so
`python3 -m venv` fails and the fix needs `sudo apt`. A uv-managed CPython 3.12
**with a working pip** was on disk the whole time.

### The probe

Two runs against `terminal-bench-core` 0.1.1, task `sqlite-db-truncate`:

| Arm | Result | What it proves |
|---|---|---|
| `--agent oracle` | **resolved, 100%** | The whole container path works: image build, task setup, test execution, result recording. No model involved. |
| `--agent claude-code --model anthropic/claude-sonnet-4-5` | unresolved, **but the agent completed** | A real agent CLI runs inside the container against a real model. |

The second is the one that mattered, and its *failure* is the good news: the
trial reports `terminal_reason: "completed"`, `subtype: "success"`,
`api_error_status: null`, ran for 2m14s, and recorded genuine usage — 391k
cache-read tokens, **$0.28**. The agent parsed the corrupt SQLite file by hand
and wrote `/app/recover.json`. The task's own test then failed it for recovering
`testword052` where it expected `testword05`.

**That is a task outcome, not an infrastructure failure.** Nothing about auth,
containers, image pulls or provider config stood in the way.

### Reproducing it

```sh
# System python3 cannot build a venv here; use the uv-managed interpreter.
~/.local/share/uv/python/cpython-3.12-linux-x86_64-gnu/bin/python3.12 -m venv .venv
.venv/bin/python -m pip install terminal-bench

# Pin the dataset version — bare `terminal-bench-core` resolves to `head`,
# whose layout the registry client fails to unpack (FileNotFoundError: .../tasks).
.venv/bin/tb datasets download -d terminal-bench-core==0.1.1 --output-dir ./tb-tasks

set -a; . ~/.config/squad/anthropic.env; set +a
.venv/bin/tb run --dataset-path ./tb-tasks --task-id sqlite-db-truncate \
  --agent claude-code --model anthropic/claude-sonnet-4-5 \
  --n-concurrent 1 --no-upload-results --output-path ./runs
```

### Two things to carry into M0–M2

1. **Only `claude` is installed locally.** `codex` and `aider` are absent, so
   multi-CLI arms need those installed first. Harbor names many more agents than
   this machine can currently run.
2. **`results.json` reported `total_input_tokens: 0` and `total_output_tokens: 0`**
   while the agent's own log carried full usage and cost. Harbor's token
   accounting does not populate for the `claude-code` agent. **M2 must take cost
   and tokens from the agent log rather than the summary**, or every cost figure
   on this track will read zero — the same class of defect as the squad track's
   under-counted multi-call turns.

### What this unblocks elsewhere

The squad track's cross-track memo (gate SG3b) has this track reaching M8 with a
shared task set as its stated precondition. That is now a matter of doing the
work rather than of an environment nobody could configure. The expected result
is registered in advance in the squad track's
`packages/duva-bench/studies/a-tool-familiarity-pilot/CROSS-TRACK.md`.

---

## 0. Rules for the executing agent

1. **One milestone per branch, one PR per milestone.** Branch from `main`, name it
   `feat/m<N>-<slug>`. Do not start M(N+1) until M(N) is merged.

   > **This rule has been broken exactly once, on purpose, and it still binds.** M0–M8
   > were written in a single branch during the track pause and landed on 2026-08-10 as
   > one PR (#5) rather than nine. That was a recovery decision about work that already
   > existed — replaying it as nine PRs would have produced the same tree after nine
   > review cycles — and not a precedent. The cost is real and is recorded in
   > `/ROADMAP.md`: there is no milestone-by-milestone review history behind that code,
   > which is part of why its gates are tracked separately from its tests. **Every
   > milestone from gate G1 onward obeys this rule as written.** If you are reading the
   > git history and the plan and they disagree, the plan is right.
2. **Never add commit attribution** (no `Co-Authored-By`, no "Generated with" lines).
3. **Do not invent scope.** If a task under-specifies something, choose the smallest implementation
   that satisfies the done-condition, and record the choice in the PR description.
4. **Done-conditions are tests wherever possible.** A done-condition that says "proven by test"
   means: write the test first, watch it fail, make it pass, leave it in the suite.
5. **Copy patterns from the sibling repos before designing new ones.** adp-replay
   (github.com/DeDuva/adp-replay) is the reference for: ADP client generation, spooled recording,
   canonical digests, paired statistics, pre-registration discipline. The squad fork's
   `packages/squad-lab` (github.com/DeDuva/squad) is the reference for: harness digests, grader
   identity separation, per-axis summaries, variance/noise-floor analysis. When this plan says
   "mirror X", open X and transliterate it — do not reinvent it.
6. **The non-cuttable design rules** (each bought with a documented failure in the sibling
   projects):
   - Rank **per axis, never blended** into a composite score.
   - **Unscored ≠ zero.** A crashed grader leaves a trial unscored; an unpriced model renders
     `unpriced`; `null` never becomes `0`.
   - **Digest mismatch ⇒ no comparison.** The analysis refuses to rank across differing grader
     `spec_digest`s or differing harness digests; it emits a banded table with a warning instead.
   - **Evidence gating.** A trial whose ADP `/verify` is not `ok: true` gets verdict `ERROR`, never
     pass/fail. Errors count **against** the majority in repetition verdicts.
   - **Pre-registration.** The analysis block of a study is digested before execution; amendments
     are allowed but the pre-amendment reading stays computable and reports print both.
7. **Secrets** come only from the environment (`DUVA_ADP_RUNNER_TOKEN`, `DUVA_ADP_GRADER_TOKEN`,
   provider keys). Never write them to disk, logs, or ADP payloads. The grader subprocess
   environment must have all ADP runner/provider tokens stripped.

---

## 1. What this builds

duva-bench defines, executes, and analyzes **controlled factorial experiments over coding-agent
arms**. An arm is a digested combination of *model × harness (agent CLI) × toolset × docs bundle ×
environment*. Execution is delegated to **Harbor** (container per trial, real agent CLIs). Every
trial is recorded as an **ADP run**: hash-chained trajectory, arm descriptor in the signed run
labels, multi-axis evals scored under a separate identity, `GET /verify` as the evidence gate.
Analysis produces per-cell tables, a pooled-sd noise floor, paired statistics with multiplicity
correction, and process metrics (tool-error rate, hallucinated-call rate, tokens, cost).

Drivable three ways: **CLI** (primary, built first), **JSON API** (same functions served), **web
UX** (a client of the API, built last). A study is a content-digested YAML file; a result is a
record reconstructible from ADP, not from local state.

---

## 2. Toolchain and repo layout (fixed decisions — do not revisit)

- **Python ≥ 3.11**, `src/` layout, `py.typed`. Build: hatchling. Runtime deps for the core:
  `pydantic>=2.7`, `httpx>=0.27`, `pyyaml>=6` — nothing else without a PR-description justification.
- Dev tooling: `pytest`, `pytest-cov`, `ruff` (line length 100), `mypy --strict` (generated code
  exempt). `make setup lint fmt types test check` mirror adp-replay's Makefile.
- Optional extras: `[harbor]` for the Harbor/terminal-bench dependency (pinned in M3 when the
  working version is known); `[server]` for `fastapi` + `uvicorn` + `sse-starlette` (M7).
- Web UX (M7 only): React + Vite + TypeScript under `web/`, no CSS framework; visual style copied
  from `docs/html/index.html` (IBM Plex, same palette).
- Layout:

```
src/duva_bench/
  study/        # M1: spec models, canonical digest, pre-registration
  adp/          # M2: generated client (_generated/), wrapper, recorder, verify gate
  exec/         # M3, M5: harbor adapter, trial runner, scheduler
  arms/         # M4: arm models, twin toolsets, doc bundles, digests
  grading/      # M4: grader invocation, identity separation
  analysis/     # M6: stats, noise floor, process metrics
  report/       # M6: report rendering
  server/       # M7: FastAPI app
  cli.py        # argparse or typer-free stdlib CLI, subcommands per milestone
docs/html/      # the published page (exists)
docs/execution-plan.md
web/            # M7
tests/          # unit; tests/contract/ live-ADP suite (marked @pytest.mark.contract)
```

### ADP surfaces this plan consumes

| Purpose | Endpoint |
|---|---|
| Mint an intent (workaround, see §3) | `POST /api/v3/repos/{o}/{r}/issues` |
| Open / close / abandon a run | `POST /api/adp/repos/{o}/{r}/runs`, `.../runs/{id}/close`, `.../abandon` |
| Sessions + chained events | `POST .../sessions`, `POST .../sessions/{id}/events` |
| Record a score (grader token) | `POST .../runs/{id}/evals` |
| Evidence gate | `GET .../runs/{id}/verify` |
| Read-side analysis | `GET .../runs`, `.../runs/compare?intent_id=`, `.../runs/{id}/stats`, `.../trajectory` |

### §3. Known ADP contract traps — code around them, do not rediscover them

These are verified-open findings from ADP's first consumer (see adp-replay
`docs/adp-contract-findings.md`). Handle each exactly as stated:

1. **`payload` is documented optional but `NOT NULL` in the DB** — omitting it 500s. Always send
   `payload: {}` when there is no payload. Comment the workaround at the call site.
2. **OpenAPI responses carry no schemas.** The generated client types requests only. Hand-write
   response models in `adp/models.py` from observed responses and pin them with contract tests.
   Note: append responses use `head` (not `chain_head`) and `duplicates` is a **list of ids**.
3. **No native intent endpoint.** An intent exists only as a side effect of filing a compat-plane
   issue. `mint_intent()` files `POST /api/v3/.../issues` and reads `intent_id` off the response.
4. **No token-provisioning API.** Tokens are minted with ADP's `tsx src/bootstrap.ts <principal>`.
   Document this in the README of `tests/contract/`; CI bootstraps two principals
   (`duva-runner`, `duva-grader`).
5. **Version skew fails loudly.** ADP serves `ADP-API-Version` on every response including 401s.
   Assert equality with the vendored spec version at client construction (mirror adp-replay's
   `adp/version.py`); refuse to run mid-experiment on mismatch. Current contract: **0.2.0**
   (has run `labels`; `/runs/compare` returns `evals[]` latest-per-name).
6. **List caps.** `GET /runs` and `/runs/compare` cap at 200 rows, per intent. Design analysis
   reads per-intent (one intent per task), never "all runs of the experiment" in one call.

---

## 4. Milestones

### M0 — Scaffold

**Deliverable:** the toolchain above, an empty-but-importable `duva_bench` package with `cli.py`
(`duva-bench --version` works), CI (`.github/workflows/ci.yml`: lint, format-check, mypy, pytest on
3.11 + 3.12), and the existing `pages.yml` untouched.

**Done when:** `make check` passes locally and in CI on a PR; `pip install -e .` then
`duva-bench --version` prints the version.

### M1 — Study spec and digest

**Deliverable:** `study/` pydantic models (all `frozen=True, extra="forbid"`):

- `TaskRef` — id, path or git source, grader path + its sha256.
- `ModelSpec` — provider, model, parameters (free dict, digested).
- `HarnessSpec` — harbor agent name + pinned version.
- `ToolsetSpec` — named toolset with per-tool `definition_digest`; `docs_bundle` (see M4).
- `Arm` — id + the four specs + env pins; `arm_digest` computed property.
- `PreRegistration` — primary metric name, repetitions, exclusion rules, `metaprogramming_allowed:
  bool`, amendment list (each amendment carries date + rationale; original values retained).
- `Study` — title, tasks, arms, repetitions, budget_usd_cap, concurrency, pre_registration.

Canonical digest: mirror adp-replay's `manifest/digest.py` — canonical JSON (sorted keys, compact
separators, floats rejected), sha256, insensitive to key order, **excluding** any runtime ids.
CLI: `duva-bench validate <study.yaml>`, `duva-bench digest <study.yaml>`.

**Done when:** a study round-trips YAML→model→YAML with a stable digest; digest equality is proven
insensitive to key order and sensitive to every field group (parameterized test); an example
`examples/smoke/study.yaml` with 2 tasks × 2 arms × 2 reps validates.

### M2 — ADP recording core

**Deliverable:** `adp/` —

- `make sync-spec generate`: vendor ADP's `spec/openapi.yaml`, generate `_generated/operations.py`
  (mirror adp-replay's `tools/generate_adp_client.py`), plus `check-generated` in CI.
- `AdpClient` wrapping only the §2 surfaces. Constructor takes `runner_token` and `grader_token`
  and **raises if they are equal** (mirror adp-replay's `client.py`).
- `Recorder`: spooled, batched event append with `client_event_id` idempotency and contiguous
  `producer_seq` from 1; on 409 use `expected_next_seq` to replay the spool; trim at
  `accepted_through`. Mirror adp-replay `recording/{recorder,spool}.py`.
- `verify_gate(run_id) -> Verdict`: `GET /verify`; anything but `ok: true` ⇒ `ERROR` with the
  failing sub-check named. Absent field = failure; `null` = not-applicable.
- `preflight()`: before any paid work, open a throwaway run, record a throwaway eval with the
  grader token, and assert ADP reports `separately_authorized: true` (mirror adp-replay
  `replay/runner.py`).

**Done when:** unit tests cover spool replay, dedupe, gap rejection; `tests/contract/` passes
against a live ADP (docker-compose Postgres + ADP pinned by commit in CI, two bootstrapped
principals) including: version assertion pre-auth, payload-less event via the `{}` workaround,
SIGKILL of the recorder leaves a resumable gap-free chain, tampered event ⇒ `verify_gate` returns
`ERROR`.

### M3 — Harbor execution: one trial, end to end

**Deliverable:** `exec/` —

- Pin the Harbor dependency (`[harbor]` extra) at the version that works; record it in the PR.
- `Trial` = (task, arm, repetition). `run_trial(trial)`:
  1. `mint_intent` for the task (idempotent per task per study: reuse by title convention
     `duva:<study_digest[:12]>:<task_id>`).
  2. Open an ADP run with `external_ref = <study_digest[:12]>:<arm_id>:<task_id>:r<rep>` and
     labels = `{study, arm, model, harness, toolset, docs, task}` digests/names.
  3. Invoke Harbor to run the task in a container with the arm's agent + model + env.
  4. **Trace bridge:** parse Harbor's collected execution trace and emit ADP events —
     `model_call` (with tokens where reported), `tool_call` (with status), `message`, `commit`,
     `test_result`. Map only what the trace supports; every unmapped record becomes `custom`.
     The bridge is a pure function `harbor_trace -> [AdpEvent]` with fixture-based tests.
  5. Close the run against the final git sha (or `abandon(reason)` on agent failure).
  6. `verify_gate`; persist a local `trial.json` (pointers + verdict only — no scores, no stats).
- CLI: `duva-bench trial <study.yaml> --task T --arm A` runs one trial.

**Done when (GATE G1 — hard stop):** one real trial — smoke task, one real agent via Harbor, one
real model — produces an ADP run whose `/verify` returns **`ok: true` *and* `envelope_verified:
true` *and* `trajectory_digest_matches: true`**, whose labels round-trip through
`GET /runs/compare`, and whose event chain contains ≥ 1 `tool_call` bridged from the Harbor trace.
If Harbor cannot be installed in the environment, this gate **blocks**: record the blocker in the
README exactly as adp-replay documents its blocked tasks, and stop.

> **Why the two extra conditions, added 2026-08-10.** `ok: true` alone is not evidence of an
> attestation. An *abandoned* run also returns `ok: true`, with `envelope_verified` and
> `trajectory_digest_matches` both `null` — "not applicable", because only `close` mints the
> signed attestation. So a version of this gate that checked `ok` alone could be passed, in full
> honesty, by a runner that abandoned every trial and never bound an arm label to a trajectory
> digest at all. That is precisely the "a gate that reports itself passed" failure this plan's §0.6
> exists to prevent, and it was found by running the gate rather than by reading it. Absent is not
> passing; `null` is not `true`.

### M4 — Arms and twin instruments

**Deliverable:** `arms/` + `grading/` —

- **Twin generator:** given a toolset definition and a seed, produce an isomorphic twin — renamed
  tools/params (pronounceable, non-dictionary, token-length-matched names), identical handlers —
  plus a persisted rename map, plus doc bundles at three quality grades (`none`, `reference`,
  `rich`: reference + worked examples). Twins are deterministic given (definition, seed).
- Arm materialization: given a task + arm, produce the Harbor task variant (env, injected docs,
  toolset config).
- Grader runner: `node <grader> <workdir>` (or `python3 <grader>`) with cwd outside the workdir and
  ADP/provider tokens stripped from env; parse `{spec, axes:{name:{score, passed, summary}}}`;
  inject the grader file's sha256 into the spec before digesting; POST one eval per axis under the
  grader token.

**Done when:** a property-based test proves twin isomorphism (for sampled inputs, twin handler
output == original handler output); rename maps round-trip; token-length matching is asserted
within a tolerance using a real tokenizer count or character-length proxy (state which in the PR);
grader env-stripping is proven by a test grader that prints its env.

### M5 — Factorial scheduler

**Deliverable:** `exec/scheduler.py` —

- `plan_trials(study)`: full factorial tasks × arms × repetitions, stable ordering.
- Execution with bounded concurrency; per-provider rate limiting; budget cap checked **before**
  each trial (mirror adp-replay's `CostLedger`); append-only `progress.jsonl` (one line per
  completed trial keyed by the trial's `external_ref`) making the whole study resumable.
- Idempotent rejoin: rerunning a study skips trials whose `external_ref` already has a closed,
  verified ADP run.
- CLI: `duva-bench run <study.yaml>`, `duva-bench status <study.yaml>`.

**Done when:** a test kills the scheduler mid-study (SIGKILL) and a rerun completes exactly the
missing trials with no duplicate ADP runs; the budget test proves no trial starts past the cap.

### M6 — Analysis and report

**Deliverable:** `analysis/` + `report/` —

- Outcome extraction from ADP only (`runs/compare` per intent + `runs/{id}/stats` + trajectory
  reads): per-trial axes, tokens, cost, duration, tool calls/failures.
- Process metrics from trajectories: tool-error rate, retry count, **hallucinated-call rate**
  (tool_call names ∉ the arm's toolset — the rename map makes this computable), and, where Study B
  applies, escape-to-metaprogramming rate.
- Statistics (mirror adp-replay `stats/paired.py`, then extend): exact McNemar pairwise vs. a
  declared control arm with **Holm correction**; bootstrap CIs resampling tasks whole (seeded);
  pooled within-cell sd noise floor with contrasts in sd units (mirror squad-lab `variance.ts`);
  ICC where repetitions allow, `{"unavailable": reason}` otherwise.
- Report: one self-contained static HTML per study (reuse the `docs/html` visual style) +
  `report.json`: pre-registration echo with amendments, per-cell tables per axis, CIs, noise-floor
  contrasts, arm digests, per-trial verify status, cost ledger. Banded warnings on any digest
  mismatch; blended scores nowhere.
- CLI: `duva-bench report <study.yaml>`.

**Done when (GATE G2 — hard stop):** the smoke study (`examples/smoke/`, 2 tasks × 2 arms × 2
reps) runs end to end — `run` then `report` — and every number in the report reconciles with a
direct ADP read (a test does the reconciliation); an unscored trial renders as unscored; a
tampered-with run renders as `ERROR` and is excluded from statistics with a printed count.

### M7 — API server and web UX

**Deliverable:** `server/` (`[server]` extra) + `web/` —

- FastAPI: `POST/GET /api/studies` (upload/validate/digest), `POST /api/studies/{d}/run`,
  `GET /api/studies/{d}/status` (SSE stream from `progress.jsonl`), `GET /api/studies/{d}/report`.
  The server holds ADP tokens; the browser never sees them. Read-proxy only the literal ADP paths
  the UX needs (mirror squad-lab `server.ts`'s six-literal-paths stance — no wildcard proxy).
- SPA: three views — **Define** (YAML editor with validate/digest + pre-registration diff),
  **Monitor** (trial grid streaming via SSE, per-trial verify badge), **Analyze** (per-axis
  ranking tables with banded warnings, cost/process columns, links into ADP runs). Style: copy
  the palette/typography of `docs/html/index.html`.
- A Playwright walk (`npm run ui-check`) drives define → run (smoke study, mocked or live per env
  var) → report.

**Done when:** the Playwright walk passes; killing and restarting the server mid-study loses no
SSE frames (resume via `Last-Event-ID` — mirror squad-lab's frame-log design, including keying the
frame cache by file path, not study id).

### M8 — Study A, for real

**Deliverable:** `studies/a-tool-familiarity/` — the study YAML (arms: standard toolset vs. twin
vs. twin+`reference` vs. twin+`rich`; ≥ 2 models × ≥ 2 harnesses; ≥ 6 tasks; 5 reps), its
pre-registration (metric: hallucinated-call rate primary, pass-rate secondary; metaprogramming
recorded, not forbidden), the executed run, and `report/` output committed with a written summary
that follows the report's numbers.

**Done when (GATE G3 — hard stop):** the report prints the pre-registration unchanged or with
explicit amendments; every included run verifies; the write-up states the noise floor before any
contrast and reports the familiarity×model and familiarity×docs interactions whatever their sign.

---

## 5. What this plan deliberately excludes

Multi-turn swarm arms (squad as an arm arrives post-M8 via a Harbor adapter or an ADP-emitting
wrapper); LLM-judge axes (blocked on ADP non-ranking evals); ADP-side label queries and pagination
(analysis reads per-intent until ADP grows them); any bespoke in-process agent loop (that is the
mistake this architecture exists to not repeat).
