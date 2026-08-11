# Blockers

What is built and unproven, and exactly what it would take to prove it. Kept the way adp-replay
documents its blocked tasks: a gate that cannot be run is recorded as blocked, never as passed.

The rule this file exists to enforce is the plan's, from §0.4 — *a done-condition that says "proven
by test" means the test exists and passes*.

**Gate G1 passed on 2026-08-10** and its section below is now a record rather than a plan. G2 and G3
still have code and not the evidence their gates demand; nothing about them here is a claim that the
code works, only a claim about what was possible to check.

---

## Gate G1 — one real trial through Harbor · **PASSED 2026-08-10**

**Run** `a5c20876-d5ff-41af-95b5-114c9a8fddb6` in `duva/bench-smoke`, external ref
`d1a38ec0faef:standard:json-normalizer:r3`, arm `standard` (`terminus-2@0.20.0`,
`anthropic/claude-sonnet-4-5-20250929`), against a live ADP at contract `0.2.0`.

The gate as tightened on the same day (execution-plan §M3) asks for three things and got them:

| Condition | Result |
|---|---|
| `GET /verify` → `ok` | `true` |
| ...and `envelope_verified` | `true` |
| ...and `trajectory_digest_matches` | `true` (`attested_subject_sha` == `final_git_sha` == `66c321b3…`) |
| Labels round-trip through `GET /runs/compare` | 13 labels, including `arm_digest`, `model_digest`, `harness_digest`, `toolset_digest` |
| ≥ 1 bridged `tool_call` | **17**, out of 35 events (6 `message`, 5 `model_call`, 6 `custom`, 1 `test_result`) |

Scored under the grader identity on two axes, `separately_authorized: true`, verified by
`duva-bench preflight` before any spend.

### What it took, and what that says

Nothing about the environment blocked this gate; the three blockers recorded here before
2026-08-10 described the remote session the code was written in. What blocked it was **seven
defects in code that had 325 passing tests**, each invisible to a fixture and obvious within one
real run:

1. **`--env` instead of `--agent-env`.** Harbor's `--env` picks the container backend; `KEY=VALUE`
   goes to `--agent-env`. Every arm with an environment pin died before a container started.
2. **A relative `--jobs-dir`.** Harbor resolves it against its own cwd, so output landed in a
   doubly-nested path nothing could find.
3. **`results.json` vs `result.json`.** Harbor writes the singular. The fixtures used the plural,
   so the fixtures and the code agreed with each other and with nothing else.
4. **Job results mistaken for trial results.** Harbor writes `result.json` twice — once per job,
   once per trial — and "the newest one" is the job summary, which has no trajectory beside it.
   A trial verified perfectly with **zero** events bridged.
5. **No reward file.** Harbor decides pass/fail by reading `/logs/verifier/reward.txt`, not by exit
   status. No task in this repository wrote one, so every trial died in the verifier.
6. **`verifier_result.reward` vs `.rewards.reward`.** Two modules read the flat key that Harbor does
   not write, so "the verifier passed" always read as "the verifier did not run".
7. **Artifacts never reached the grader.** The work product lives in `/app`, which dies with the
   container, and Harbor mirrors `/logs/artifacts` to `artifacts/logs/artifacts` rather than
   flattening it. Graders scored 0 "never written" on tasks their own verifier passed.

Six of the seven were assumptions about *another program's* interface, written from its docs and
pinned by fixtures this project also wrote. That is the whole lesson of this gate, and it is why
`tests/test_harbor_cli.py` now asserts the adapter's flags against `harbor run --help` instead of
against a recorded copy of its own output. The `harbor` marker had been declared since M0 and used
by zero tests.

## Studies cannot share the ADP dev stack · **OPEN, found 2026-08-10**

**A study run against `~/dev/adp`'s ephemeral stack is destroyed by anyone else running
`make up` in that checkout.** Re-running gate G2 to match the current spec got 7 of 8 trials
recorded and then lost them: the ADP checkout moved from `c125db3` to `924d6d8` on branch
`m4/m4-3-quotas-and-gc` and a fresh stack replaced the database mid-study. The symptoms
arrive in this order and none of them names the cause:

1. `Connection reset by peer` on a recording append;
2. `401` from a token that worked a minute earlier — it belongs to a database that is gone;
3. `404` for a repository that was created and no longer exists.

Two aggravating factors of our own, both now known:

- ADP's `GIT_ROOT` defaults **inside** its own checkout (`.adp-test/git`) and `npm run dev`
  is `tsx watch`, so every artifact commit duva-bench publishes restarted the server under
  the running study. Use the built server (`npm run build && npm start`) for anything that
  publishes, never the watcher.
- `make up` alone leaves an unmigrated database; `npm run migrate --prefix server` has to
  follow it, or `bootstrap.ts` fails with a bare Postgres `parserOpenTable` error.

**What this costs.** Any study whose results matter needs an ADP instance nobody else
resets — a dedicated stack, a container of its own, or a durable deployment. Until then a
run's evidence lives at the mercy of an unrelated workstream, which is the ephemerality
already recorded in `/ROADMAP.md` arriving sooner and with less warning.

## Gate G2 — the smoke study end to end · **NOT RUN, and rehearsed**

Downstream of G1: `duva-bench run` then `duva-bench report` needs eight real trials with a model.
That has not happened. What has, on 2026-08-10, is the same eight trials with the model taken out.

### The dress rehearsal

`examples/smoke/study-oracle.yaml` is `study.yaml`'s shape — two tasks, two arms, two repetitions,
concurrency 2 — run by Harbor's **oracle** agent. Both arms are the same instrument, so it answers
no question about any agent; it exercises the machinery for the cost of the containers.

```
duva-bench run    → planned 8, completed 8, errors 0, 1m22s wall clock
duva-bench status → verified 8, remaining []
duva-bench report → 8 trials, 8 verified, 7 axes, 0 warnings
```

Three of the things G2 was going to discover, discovered for nothing:

* **Concurrency works and costs about what you would guess.** Two trials at a time held exactly
  two trials at a time — and **four containers**, because a trial runs two. Scheduler peak RSS was
  224 MB; 12.2 GB of memory stayed free throughout; container disk did not move measurably. The
  number to carry forward is the multiplier: *concurrency N means 2N containers*, so Study A at
  concurrency 8 is 16.
* **The report renders `null`, not `0`, for a metric nothing supports.** The oracle makes no tool
  calls, and `tool_error_rate` comes back `null` with `tool_calls: 0` beside it rather than a
  flattering zero. That is execution-plan §0.6's unscored-is-not-zero rule holding at the only
  place it can be observed.
* **Both arms scored `acceptance` 1.0, CI [1.0, 1.0], 4 trials each, 0 unscored** — which is the
  correct answer for two identical instruments, and would have been a red flag from a real study.

### What the rehearsal cannot say

It runs no model, so it says nothing about token accounting, provider rate limiting, or budget
enforcement under real spend — `priced_trials` was 0 and the cap was never approached. G2 still has
to be run.

### And it caught one thing that no test would have

The report's cost block printed `total_usd: 0.0` beside `unpriced_trials: 8`. For an oracle that
total is true — nothing was called. For a model whose price nobody has, it is the failure
execution-plan §0.6 forbids by name: unpriced folded in as zero, understating a study's cost
silently and by an unknown amount. Fixed in the same PR — a total is stated only when every trial
is priced, and `priced_usd` carries what is known otherwise.

Worth noting *how* it was caught. Every unit test of the cost block passed, because they were
written against studies where everything was priced. It took running the machinery over a study
whose trials genuinely have no cost — which is precisely what an oracle rehearsal is for, and an
argument for keeping one around rather than treating it as scaffolding.

## The arm materialization gap · **CLOSED 2026-08-10**

**Found and fixed the same day.** `arms/materialize.py` was never called by anything that ran a
trial, so an arm's toolset, twin and documentation bundle were digested, labelled and never applied.
Gate G2's run is what exposed it: the smoke study's two arms differ *only* in toolset metadata and
the report read acceptance 0.75 for `standard` against 1.00 for `twin` — two runs of one arm, and
the gap was the study's own noise. Study A's primary metric was constant for the same reason: the
declared vocabulary was not the one the agent had, so hallucinated-call rate was 1.0 everywhere.

### Wiring it in was not enough, and that is the interesting part

`materialize()` wrote `duva/toolset.json` into the task copy. **Nothing reads that file.** Harbor
configures an agent's tools from `task.toml` and from nowhere else, so connecting materialization as
it stood would have produced arms that still differed only in labels *while looking wired* — worse
than the visible gap it replaced.

What the redesign does instead:

| | |
|---|---|
| `environment/duva_toolset.json` | the arm's effective toolset — the twin's, when it twins one |
| `environment/duva_mcp_server.py` | a stdlib-only stdio MCP server that serves it |
| `environment/Dockerfile` | appended `COPY` lines that install both into the image |
| `task.toml` | appended `[[environment.mcp_servers]]` and `DUVA_TOOLSET`, which is what Harbor reads |
| `docs/TOOLS.md` + `instruction.md` | unchanged; this half always worked |

Tools are dispatched by a **capability** (`fs.read`, `proc.run`) carried on each definition, not by
name, so two arms serve the same implementations under different names — which is what makes them
isomorphic. The twin generator now also records `parameter_roles`, because it renames parameters as
well as tools and the server has to map them back.

### The leak this design has to avoid, and how it was caught

A twin arm's container must not contain the vocabulary that arm is being tested without: an agent
with a shell can read every file in its own task. `test_a_twin_variant_carries_no_word_of_the_
vocabulary_it_replaces` scans a materialized twin for the original names — and **it failed on first
run**, because the MCP server's own docstring used a standard tool name as an example, and that file
is copied into the image verbatim. The rename map is handed back to the caller and written beside
the variant, never inside it.

### What this cost

Every toolset, arm and study digest moved, because `ToolsetSpec` gained a `definition_path` and the
twin definitions gained `parameter_roles`, and `digest_source` dumps every field. That is correct —
the specs genuinely changed — and it makes **the G2 run recorded above evidence for a superseded
version of the smoke study**. Re-running it costs about $0.45.

## Gate G3 — Study A executed · **BLOCKED**

Downstream of G1 and G2, and additionally needs **480 trials** of real spend (16 arms × 6 tasks × 5
repetitions).

`studies/a-tool-familiarity/` carries the whole design: six Harbor tasks with oracles and verifiers,
six multi-axis graders, the standard toolset and its twin, the rename map, and a `study.yaml` that
validates and digests to
`sha256:5c83036cad205d76ffc7e021eabc36fd7c074d4d53d028bd4b83f7af0c668084`.

What `tests/test_study_a.py` establishes without executing it: the factorial is the size the plan
specifies; the four familiarity arms of one model × harness cell differ in exactly one factor; every
twin arm shares one seed; every grader still hashes to its pin; **every oracle satisfies its own
grader on every axis**, so a failing arm will be a failing arm rather than a broken task; and every
grader answers about an empty workdir rather than crashing on it.

Nothing in it has been executed. Its `report/` directory is deliberately absent: an empty one would
look like a study that produced nothing, and a populated one would have to be populated with
something invented.

## The live-ADP contract suite · **PASSES as of 2026-08-10**

All 13 tests in `tests/contract/` pass against a live ADP at contract `0.2.0`. They had never
executed before that date, and the first run failed 5 of 13 — which was the point of writing them.

`duva_bench/adp/models.py` is hand-written from ADP's *source* rather than from its spec, because the
spec attaches no response schemas, and `tests/fakes.py` reproduced the same reading. Both being wrong
in the same direction is exactly what happened: the double accepted any 40-hex `final_git_sha`, so
325 unit tests agreed with a client that could not close a single real run (finding #5 in
`adp-contract-findings.md`). The double now enforces the rule the server enforces.

The tamper-evidence test needs `psql`. Where Postgres runs in a container and no client is installed
on the host, point `DUVA_ADP_PSQL` at one — e.g.
`DUVA_ADP_PSQL="docker exec -i <postgres-container> psql"`. It is not allowed to skip: a
tamper-evidence test that quietly does not run on the machine where somebody is about to trust the
evidence is worse than no test.

`.github/workflows/adp-contract.yml` was written from ADP's own Makefile and `server/src/bootstrap.ts`
at commit `b3a455e8` and **has still not run in CI**.

## Playwright walk (M7) · **PASSES, against the ADP double**

`npm run ui-check` drives define → run → analyze in a real Chromium against a real server, and
passes. What is behind that server is `scripts/dev-server.py`'s in-memory ADP and a recorded Harbor
trial, so the walk is evidence that the three views work end to end — not evidence that a real study
runs. That is gate G1, above.

On a machine that cannot download a browser, `PLAYWRIGHT_CHROMIUM=/path/to/chrome` points Playwright
at an existing one; that is how it was run here.

**It passed locally and failed the first time CI ran it** (2026-08-10), which is worth recording
because the failure mode leaves no failing test behind. Vite's `preview` defaults its host to the
*name* `localhost`, and Node 17+ resolves that to `::1` first. On a runner with IPv6 the preview
server listened on `::1` only while Playwright polled `http://127.0.0.1:4173`, so the job died at
`Timed out waiting 180000ms from config.webServer` with both suites unrun. `npm run preview` now
passes `--host 127.0.0.1` explicitly, pinning both ends to one address family. The lesson
generalizes: "passes on my machine" and "passes in CI" differ by the whole environment, and a
green local walk is not evidence until CI has run it once.

## Where "it passes locally" stopped meaning anything (2026-08-10)

Twice in one day, on this branch, a change passed every local check and failed CI — and
neither failure was flaky. They are recorded together because they are the same shape: **the
development machine has things CI does not, and the local gate silently tested a different
world.**

1. **The Playwright walk.** Vite's `preview` host defaults to the *name* `localhost`, which
   Node 17+ resolves to `::1` first. On an IPv6 runner the server listened on `::1` only while
   the probe polled `127.0.0.1`, and the job died at the webServer timeout with both suites
   unrun — no failing test, no stack, just silence. Fixed by binding `--host 127.0.0.1`.
2. **`HarborExecutor.command`.** Resolving the Harbor binary inside it made building an argv
   depend on Harbor being *installed*. This machine has Harbor; CI does not; two unit tests
   that only wanted to read the flags failed there and nowhere else.

Two habits came out of it, both cheap:

- **`make check` runs exactly what CI runs.** It ran `ruff check` while CI additionally ran
  `ruff format --check`, so a branch could pass the gate and fail CI on formatting alone. A
  gate that is not the same gate as CI is a gate people learn to ignore.
- **A test for an optional dependency must fail where the dependency is present.** The purity
  test names an executor that cannot exist, so it fails on every machine rather than only on
  the ones missing Harbor. Writing it the other way round would have reproduced the bug: green
  here, red in CI, and nobody the wiser until the next push.
