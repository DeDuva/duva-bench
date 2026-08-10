# Contract tests

These run against a **live ADP**. They are the only thing that can tell us
whether the hand-written response models in `duva_bench/adp/models.py` still
describe what the server sends: ADP's OpenAPI document types requests and
describes responses in prose, so half the contract is pinned by these tests and
by nothing else.

They are never folded into `make test`. A suite that skips when its dependency
is missing reports a pass and an untested path with the same exit code.

```
make test-contract
```

## What you need

| Variable | What it is |
|---|---|
| `DUVA_ADP_BASE_URL` | e.g. `http://localhost:3000` |
| `DUVA_ADP_RUNNER_TOKEN` | token for the principal that opens runs |
| `DUVA_ADP_GRADER_TOKEN` | token for a **different** principal, which reports scores |
| `DUVA_ADP_OWNER` / `DUVA_ADP_REPO` | a repository that exists on that instance |
| `DUVA_ADP_DB_URL` | Postgres URL, for the tamper-evidence test only |

## Minting the tokens

ADP has **no token-provisioning API** (execution-plan §3.4). Tokens come from
ADP's own bootstrap script, run inside its checkout:

```sh
# in the adp checkout
npx tsx server/src/bootstrap.ts duva-runner
npx tsx server/src/bootstrap.ts duva-grader
```

Two principals, not one principal with two tokens. ADP decides whether a score
is `separately_authorized` by comparing the *principal* that reported it to the
one that opened the run, so two tokens minted for `duva-runner` would produce
self-reports that still look like scores. `duva_bench.adp.preflight` asserts
this against the server before any study spends anything, and
`test_a_score_is_separately_authorized_only_across_principals` asserts it here.

## Creating the repository

Also not on the native plane: `POST /api/v3/user/repos`. The compat plane is
where repositories and intents come from — see §3.3 of the execution plan and
`docs/adp-contract-findings.md`.

## What these tests are for

Each one pins a finding in `docs/adp-contract-findings.md`. If ADP fixes one of
them, the corresponding test starts failing — loudly, and in the right
direction. That is the point: a workaround nobody is told to remove is a
workaround that outlives its bug.
