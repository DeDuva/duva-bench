# Blockers

What is built and unproven, and exactly what it would take to prove it. Kept the way adp-replay
documents its blocked tasks: a gate that cannot be run is recorded as blocked, never as passed.

The rule this file exists to enforce is the plan's, from §0.4 — *a done-condition that says "proven
by test" means the test exists and passes*. Everything below has code, and does not have the
evidence its gate demands. Nothing here is a claim that the code works; it is a claim about what was
possible to check.

Last updated with the M8 commit on this branch.

---

## Gate G1 — one real trial through Harbor · **BLOCKED**

**What the gate asks for:** one trial — smoke task, one real agent via Harbor, one real model —
producing an ADP run whose `/verify` returns `ok: true`, whose labels round-trip through
`GET /runs/compare`, and whose event chain holds at least one `tool_call` bridged from the Harbor
trace.

**What is missing, precisely:**

1. **A container runtime.** Harbor runs one container per trial. The environment this was built in
   has no Docker daemon and cannot start one.
2. **A model.** No provider credentials, and the network policy would not reach a provider anyway.
3. **A live ADP.** `DUVA_ADP_BASE_URL` has nowhere to point; no ADP instance and no Postgres.

**What *was* established, so the gap is as small as it can be without those three:**

- Harbor 0.20.0 installs and imports on Python 3.12 (`pip install 'duva-bench[harbor]'`). It requires
  ≥ 3.12 while this package supports 3.11, which is why the extra carries a `python_version` marker.
- The trace format is ATIF (Agent Trajectory Interchange Format) v1.7, written by the agent to
  `<trial>/agent/trajectory.json`, alongside `<trial>/results.json` (a `TrialResult`). The bridge is
  written against those two files.
- `tests/fixtures/harbor/terminus-2-json-normalizer/agent/trajectory.json` was **validated against
  Harbor 0.20.0's own `Trajectory` model** when it was created, so the bridge's fixtures are
  documents Harbor would accept rather than documents only this bridge would.
- `tests/test_trial.py` drives the entire trial path — intent, run, labels, bridged events, close or
  abandon, evidence gate, local record — against the in-memory ADP in `tests/fakes.py` and a
  recorded Harbor trial directory.

**To close it:** on a machine with Docker, a provider key, and an ADP (see
`tests/contract/README.md`), run

```sh
duva-bench preflight examples/smoke/study.yaml
duva-bench trial examples/smoke/study.yaml --task json-normalizer --arm standard
```

and check the printed `run_id` with `GET /runs/{id}/verify` and `GET /runs/compare?intent_id=`.
Then replace this section with the run id and the date.

## Gate G2 — the smoke study end to end · **BLOCKED**

Downstream of G1: `duva-bench run` then `duva-bench report` needs eight real trials.

What is proven without it: `tests/test_analysis.py` and `tests/test_report.py` run the whole
`run → report` path against the in-memory ADP, including the reconciliation the gate asks for — every
number in the report is re-derived from a direct ADP read and compared. What that cannot prove is
that a real ADP answers the way the fake does; `tests/contract/` is the piece that would, and it has
not been run either (below).

## Gate G3 — Study A executed · **BLOCKED**

Downstream of G1 and G2, and additionally needs ≥ 2 real models × ≥ 2 real harnesses × 6 tasks × 5
repetitions ≈ 240 trials of real spend. `studies/a-tool-familiarity/` carries the study file and its
pre-registration, digested and validated. Nothing in it has been executed, and its `report/`
directory is deliberately absent rather than populated with anything simulated.

## The live-ADP contract suite · **NOT RUN**

`tests/contract/` is written and has never executed: no ADP instance was reachable. Its
`.github/workflows/adp-contract.yml` was written from ADP's own Makefile and `server/src/bootstrap.ts`
at commit `b3a455e8`, and has not run either.

This matters more than the usual "tests not run" line, because `duva_bench/adp/models.py` is
hand-written from ADP's *source* rather than from its spec — the spec attaches no response schemas.
The response shapes here were read off `server/src/http-rest/runs.ts`, `core/runs.ts`,
`core/evals.ts` and `core/trajectory.ts` at that commit, and `tests/fakes.py` reproduces what those
files do. Both could be wrong in the same direction, and only a live server can say.

## Playwright walk (M7) · **PASSES, against the ADP double**

`npm run ui-check` drives define → run → analyze in a real Chromium against a real server, and
passes. What is behind that server is `scripts/dev-server.py`'s in-memory ADP and a recorded Harbor
trial, so the walk is evidence that the three views work end to end — not evidence that a real study
runs. That is gate G1, above.

On a machine that cannot download a browser, `PLAYWRIGHT_CHROMIUM=/path/to/chrome` points Playwright
at an existing one; that is how it was run here.
