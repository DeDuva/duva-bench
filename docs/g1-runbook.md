# Gate G1 runbook — one real trial, end to end

This is the next milestone, written to be executed step by step without strategic context.
It closes **gate G1** of [`execution-plan.md`](execution-plan.md) §M3, the first hard stop
on this track.

**What G1 asks for, verbatim from the plan:** one real trial — smoke task, one real agent
via Harbor, one real model — producing an ADP run whose `/verify` returns `ok: true`, whose
labels round-trip through `GET /runs/compare`, and whose event chain contains **≥ 1
`tool_call`** bridged from the Harbor trace.

**Scope discipline.** This milestone closes G1 and stops. It does **not** run the eight-trial
smoke study (that is G2) and does **not** touch Study A (that is G3). If a step here tempts you
into a redesign, take the smallest change that satisfies the done-condition and record it in the
PR description — execution-plan §0.3.

**Branch:** `feat/g1-first-trial`, one PR, no AI attribution in commits or PR body.

**Budget:** one trial of `terminus-2` on `claude-sonnet-4-5` against a small task. The
2026-08-08 probe cost **$0.28** for a comparable trial. Expect to spend under **$2** total
including retries. If you pass $5, stop and report rather than continuing.

---

## Step 0 — Preconditions, each with the command that proves it

Run all five. Do not proceed past a failure; every one of these was a recorded blocker as
recently as 2026-08-08, and the point of checking is that the blocker list is now believed
stale.

| # | Precondition | Proof command | Expected |
|---|---|---|---|
| 1 | Container runtime | `docker info >/dev/null && echo ok` | `ok` |
| 2 | Python 3.12 with pip | `~/.local/share/uv/python/cpython-3.12-linux-x86_64-gnu/bin/python3.12 -V` | `Python 3.12.x` |
| 3 | Harbor at the pinned version | `harbor --version` | `0.20.0` |
| 4 | Provider credentials | `test -f ~/.config/squad/anthropic.env && echo ok` | `ok` |
| 5 | ADP checkout at contract 0.2.0 | `grep -A1 '^info:' ~/dev/adp/spec/openapi.yaml` | `version: 0.2.0` |

**Do not use the system `python3`.** It is 3.14 with no `ensurepip`, so `python3 -m venv`
fails and needs `sudo apt`, which is not available. Three days were lost to this once
already. Build the environment with:

```sh
cd ~/dev/duva-bench
~/.local/share/uv/python/cpython-3.12-linux-x86_64-gnu/bin/python3.12 -m venv .venv
.venv/bin/python -m pip install -e ".[dev,server,harbor]"
PY=.venv/bin/python make check      # must pass before you change anything
```

`make check` passing on an unmodified checkout is the baseline. If it fails here, the problem
is your environment, not the code — fix that first.

---

## Step 1 — Fix the Harbor `--env` defect

**This is known-broken and will fail the first trial.** It is written down rather than fixed
in advance so that closing the gate is what proves the fix.

`HarborExecutor.command()` in `src/duva_bench/exec/harbor.py` passes the arm's environment
pins as `--env NAME=value`. In Harbor 0.20.0, **`--env` is the environment *type*** — an enum
of container backends (`docker`, `modal`, `e2b`, …), defaulting to `docker`. The flag that
takes `KEY=VALUE` is **`--agent-env`** (short form `--ae`).

Both smoke-study arms set `env: {LANG: C.UTF-8}`, so every trial would invoke
`harbor run … --env LANG=C.UTF-8` and Harbor would reject `LANG=C.UTF-8` as an invalid
environment type before any container started.

Confirm it yourself first — never take a bug report on faith:

```sh
harbor run --help | grep -A3 -- '--agent-env'
harbor run --help | sed -n '/─ Environment ─/,/─ Task/p' | head -20
```

**The change**, in `HarborExecutor.command()`:

```python
for name, value in sorted(arm.env.items()):
    argv += ["--agent-env", f"{name}={value}"]
```

**Write the test first** (execution-plan §0.4). `tests/test_trial.py` already reads
`HarborExecutor.command()` as a pure function — that is what it is pure for. Add a case
asserting that an arm carrying `env` produces `--agent-env` and that the string `--env` is
**not** in the argv. Watch it fail, then make it pass, and leave it in the suite.

**While you are in this function, verify the other flags against `harbor run --help`** rather
than assuming. Already confirmed against 0.20.0: `--path`, `--agent terminus-2`, `--model`,
`--jobs-dir`, `--job-name`, `--n-attempts`, `--n-concurrent`, `--quiet`, and
`--agent-kwarg key=value` all exist and take the shapes the adapter builds. Confirm anyway;
this is the milestone where assumptions become expensive.

---

## Step 2 — Bring up ADP and mint two principals

ADP runs from its own checkout. It has a Postgres stack and a server, and they start
separately.

```sh
cd ~/dev/adp
make up                    # ephemeral Postgres, writes .env.test — do not edit or commit it
make deps                  # only if node_modules is absent
```

Then start the server in a **background** shell and leave it running:

```sh
cd ~/dev/adp/server && npm run dev
```

Confirm it answers before going further:

```sh
curl -fsS http://localhost:3000/health && echo " — ADP is up"
```

> A stale `adp-test-*-postgres` container from an earlier session may already be running while
> the server is not. `docker ps | grep adp-test` tells you; `make down && make up` in the ADP
> checkout resets it cleanly.

**Mint two principals — not one principal twice.** ADP decides whether a score is
`separately_authorized` by comparing the principal that reported it against the principal that
opened the run. Two tokens for the same principal produce self-reports that still look like
scores, which is the exact failure the design rule in execution-plan §0.6 exists to prevent.

```sh
cd ~/dev/adp
npx tsx server/src/bootstrap.ts duva-runner    # prints a token
npx tsx server/src/bootstrap.ts duva-grader    # prints a different token
```

Export them, **from the environment only** — never write a token to a file in the repo, a log
line, or an ADP payload (execution-plan §0.7):

```sh
export DUVA_ADP_BASE_URL=http://localhost:3000
export DUVA_ADP_RUNNER_TOKEN=<the duva-runner token>
export DUVA_ADP_GRADER_TOKEN=<the duva-grader token>
export DUVA_ADP_OWNER=duva
export DUVA_ADP_REPO=bench-smoke
export DUVA_ADP_DB_URL=<DATABASE_URL from ~/dev/adp/.env.test>   # tamper test only
```

`AdpClient` **raises if the two tokens are equal**, so a copy-paste slip fails loudly rather
than producing a study that scored itself.

### The repository must exist

`examples/smoke/study.yaml` names `adp: {owner: duva, repo: bench-smoke}`. That repository has
to exist on the instance before a run can open against it — creating it is ADP's business, not
duva-bench's. Create it through ADP's compat plane or its CLI, then confirm:

```sh
curl -fsS -H "Authorization: Bearer $DUVA_ADP_RUNNER_TOKEN" \
  "$DUVA_ADP_BASE_URL/api/v3/repos/duva/bench-smoke" | head -20
```

If ADP names repositories differently than the study expects, **change the study file, not the
client** — the study is data and is meant to be edited; the client encodes a contract.

---

## Step 3 — Run the contract suite

Thirteen tests in `tests/contract/` have **never executed against a live ADP**. They exist
because `src/duva_bench/adp/models.py` is hand-written from ADP's *source* (the OpenAPI
document attaches no response schemas), and `tests/fakes.py` reproduces the same reading.
Both could be wrong in the same direction, and only a live server can say.

```sh
cd ~/dev/duva-bench
PY=.venv/bin/python make test-contract
```

**Expect failures here, and treat them as the point of the exercise, not as an obstacle.**
This is the first contact between hand-written response models and the real server. When one
fails, the question to answer is *which side is wrong*:

- **Model wrong** → fix `adp/models.py`, and fix `tests/fakes.py` to match, or the unit suite
  will keep certifying the old misreading.
- **Server changed** → check `ADP-API-Version` on the response. The client asserts equality
  with the vendored spec (`0.2.0`) at construction and refuses to run on mismatch. A bump
  means re-vendoring: `make sync-spec ADP_SPEC=~/dev/adp/spec/openapi.yaml && make generate`.

Record every discrepancy in `docs/adp-contract-findings.md` in the same PR. That file is how
the next consumer avoids paying for the same discovery — execution-plan §3 is exactly this
file's ancestor from adp-replay.

---

## Step 4 — Preflight

Before any paid work, prove the identity separation is real on this instance:

```sh
.venv/bin/duva-bench preflight examples/smoke/study.yaml
```

This opens a throwaway run, records a throwaway eval with the **grader** token, asserts ADP
reports `separately_authorized: true`, and abandons the run. If it reports `false`, both
tokens belong to the same principal — go back to Step 2 and mint properly. **Do not spend
money until this passes.**

---

## Step 5 — The trial

One trial. Not the study.

```sh
set -a; . ~/.config/squad/anthropic.env; set +a
.venv/bin/duva-bench trial examples/smoke/study.yaml \
  --task json-normalizer --arm standard --repetition 1
```

Expect a few minutes of wall clock: image build, agent run, verifier, then the ADP writes. The
command prints a `run_id` — keep it, every check below needs it.

The arm resolves to Harbor agent `terminus-2` on `anthropic/claude-sonnet-4-5-20250929`. If
that exact model string is not one the provider serves, fix it **in the study file** and note
in the PR that the study digest changed as a result.

---

## Step 6 — Prove the three gate conditions

G1 is three claims. Check each separately and paste the output into the PR — a gate asserted
without its evidence is how a blocked gate gets recorded as passed.

**1. `/verify` returns `ok: true`:**

```sh
curl -fsS -H "Authorization: Bearer $DUVA_ADP_RUNNER_TOKEN" \
  "$DUVA_ADP_BASE_URL/api/adp/repos/duva/bench-smoke/runs/<run_id>/verify"
```

Anything other than `ok: true` is verdict `ERROR`, never a pass or a fail, and the failing
sub-check is what you investigate.

**2. Labels round-trip through `/runs/compare`:**

```sh
curl -fsS -H "Authorization: Bearer $DUVA_ADP_RUNNER_TOKEN" \
  "$DUVA_ADP_BASE_URL/api/adp/repos/duva/bench-smoke/runs/compare?intent_id=<intent_id>"
```

The `study`, `arm`, `model`, `harness`, `toolset`, `docs` and `task` labels must come back
carrying the same digests that went in. The `intent_id` is in the local trial record under
`.duva-bench/`.

**3. At least one bridged `tool_call`:**

```sh
curl -fsS -H "Authorization: Bearer $DUVA_ADP_RUNNER_TOKEN" \
  "$DUVA_ADP_BASE_URL/api/adp/repos/duva/bench-smoke/runs/<run_id>/trajectory" \
  | grep -c '"type": *"tool_call"'
```

Must be ≥ 1. **Zero here is the most likely way this gate fails**, and it is a bridge problem,
not an agent problem: the fixtures were built from an ATIF v1.7 trajectory that Harbor's own
model validated, but `terminus-2` writing a real trajectory may key or nest records
differently than the fixture does. Diff the real
`<jobs-dir>/<job>/<trial>/agent/trajectory.json` against
`tests/fixtures/harbor/terminus-2-json-normalizer/agent/trajectory.json`, then **add the real
trajectory as a second fixture** and extend `tests/test_bridge.py` to cover it. The bridge is
a pure function `harbor_trace -> [AdpEvent]` precisely so this is a fixture test rather than a
re-run.

### Also check, because the probe says it is wrong

The 2026-08-08 probe found Harbor reporting `total_input_tokens: 0` for `claude-code` while
the agent's own log carried full usage. Confirm what `terminus-2` does: if the recorded
`model_call` events carry zero tokens while the trial cost real money, the cost path is taking
Harbor's summary instead of the agent log, and **every cost figure on this track will read
zero**. Fix it here or record it as a named, dated blocker in `ROADMAP.md`. Do not let it pass
silently.

---

## Step 7 — Record the evidence

1. **`docs/blockers.md`** — replace the G1 section with the run id, the date, and the three
   check outputs. G2 and G3 stay blocked; say what still blocks them.
2. **`ROADMAP.md`** — flip the M3 row to gate G1 passed, with the run id as evidence. Update
   *Now / Next*. This is the repo's single status ledger and it changes in the same PR as the
   status it reports.
3. **`README.md`** — the status line stops saying all three gates are unproven.
4. **`docs/adp-contract-findings.md`** — anything Step 3 turned up.
5. Add the real trajectory fixture and its bridge test.

**Done when:** `make check` passes, `make test-contract` passes against a live ADP, and the PR
body carries the run id plus the three outputs above.

---

## If it fails

| Symptom | Most likely cause | What to do |
|---|---|---|
| `HarborUnavailable` | `harbor` not on PATH, or not 0.20.0 | Install `.[harbor]` into the venv you are actually running |
| Harbor rejects an argument | Step 1's defect, or another flag drifted | Re-read `harbor run --help`; fix `command()`, add a test |
| Image build fails | Container runtime, disk, or network | `docker info`; check disk; this is not a duva-bench bug |
| Agent runs but task fails | **Not a gate failure** | G1 asks for a *verified recorded trial*, not a *resolved* one. The 2026-08-08 probe failed its task and still proved the path |
| `separately_authorized: false` | One principal, two tokens | Re-mint per Step 2 |
| Version-skew error at client construction | ADP moved past 0.2.0 | Re-vendor the spec and regenerate; do not edit generated code |
| Zero `tool_call` events | Bridge does not match a real `terminus-2` trajectory | Add the real trajectory as a fixture, extend the bridge |
| Contract test fails | Hand-written response model disagrees with the server | Fix model **and** `tests/fakes.py`; record in the findings doc |

**Two things that are never the answer:** widening `verify_gate` so a failing check passes,
and deleting a contract test that fails. Both convert an unproven gate into a gate that
reports itself passed, which is the single failure mode this whole architecture exists to
prevent.
