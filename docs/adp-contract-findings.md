# ADP contract findings

What building duva-bench's §2 client against ADP turned up. Recorded here rather than fixed: ADP
feature work is a non-goal of this plan, and a consumer's job is to report what the contract does,
not to change it.

Against **ADP contract 0.2.0**, spec digest
`sha256:3b6b726122219dc4388ca91f332c60a12ab2a55419a590ff799b61e32b3b4a50`.

Findings 1–3 were first reported by adp-replay against contract 0.1.0 (see its
`docs/adp-contract-findings.md`); each is **still open at 0.2.0** and is re-pinned here by a test in
`tests/contract/`. Finding 4 is new, and 0.2.0 is where it became load-bearing.

---

## 1. `payload` is documented optional and is `NOT NULL` in the database

**Severity: this one takes a trial down.**

`POST /api/adp/repos/{owner}/{repo}/sessions/{id}/events` declares `required: [kind]`. An event with
only a `kind` is therefore a legal request, and returns **500**:

```
null value in column "payload" of relation "session_events" violates not-null constraint
```

A recorder emitting an event the contract says is legal can crash its own trial mid-study, and a 500
is not something a client can classify or retry meaningfully.

**Workaround here:** `AdpClient.append_events` defaults `payload` to `{}` on any event that omits
one, and says at the call site that it is a workaround. Note the shape of it: it fills an *absent*
field and leaves an explicit `null` alone, because `payload: null` is a thing an emitter can mean.

**Fix ADP should make:** give the column a default of `'{}'::jsonb`, or make `payload` genuinely
required in the spec and return 422. Either is fine; the current pairing is the only combination
that is not.

**Tests:** `test_an_event_without_a_payload_is_accepted`,
`test_a_payload_less_event_is_still_rejected_by_the_server` — the pair that will tell us when the
workaround can go.

## 2. Responses carry no schemas, and the prose does not match the wire

The document types requests and describes responses in prose — `description: Verification result`.
So a generated client can only ever type half the contract, and the untyped half is where a
consumer's bugs live. `duva_bench/adp/models.py` is that half, hand-written from observed responses.

The append response is the example that cost adp-replay two fields:

| what the prose suggests | what ADP returns |
|---|---|
| `chain_head` | **`head`** |
| `duplicates` as a count | **a list of `client_event_id`s** |

The second is the dangerous one. `duplicates` reads as truthy-when-nonempty either way, so code that
tests `if duplicates:` behaves identically and code that does arithmetic on it breaks only once a
duplicate actually occurs — during a retry, which is exactly when the recorder is already in trouble.

**Tests:** `test_an_append_returns_the_mark_a_spool_trims_against`,
`test_a_repeated_client_event_id_is_reported_as_a_list_of_ids`.

## 3. The native plane cannot open a run on its own

`POST /api/adp/repos/{owner}/{repo}/runs` requires `intent_id` and 422s when the intent does not
exist. Nothing in `/api/adp` creates an intent: they are created as a side effect of filing an issue
on the **compat plane**, and `POST /api/v3/repos/{owner}/{repo}/issues` returns the `intent_id` it
minted. Repositories are the same story (`POST /api/v3/user/repos`).

This is not a bug in the sense the others are — issues-as-intent is a deliberate design — but it is
undocumented as a dependency, and a client generated from the native plane alone cannot open a run.

**What duva-bench does:** generates exactly one compat-plane operation, by name, in
`tools/generate_adp_client.py`'s `COMPAT_ALLOWLIST`, and calls it only from `mint_intent`. Nothing
on the recording hot path touches the compat plane.

**Fix ADP could make:** a native `POST /api/adp/repos/{owner}/{repo}/intents`, or a note on the runs
endpoint saying where an `intent_id` comes from.

## 4. Two naming conventions on one plane, split by endpoint

*New at 0.2.0, in the sense that this is the release whose `/runs/compare` a multi-axis consumer has
to read.*

Within `/api/adp`, serialization is not uniform:

| endpoint | convention | example |
|---|---|---|
| `POST/GET /runs`, `/runs/{id}`, `/close`, `/abandon` | `snake_case` | `final_git_sha`, `external_ref` |
| `GET /runs/{id}/evals`, `/trajectory` | `snake_case` | `cost_micro_usd`, `producer_seq` |
| `GET /runs/compare` | **`camelCase`** | `finalGitSha`, `costMicroUsd`, `toolCalls` |
| `GET /runs/{id}/stats` | **`camelCase`** | `byKind`, `tokensIn` |

The two camelCase endpoints return internal interfaces (`RunComparison`, `RunStats`) directly, where
the rest go through `serializeRun` / `serializeEvent` / `serializeEval`.

This is not cosmetic for a consumer with response models. A model written in the wrong convention
validates — every field is optional in practice — and reads every numeric as its default. A cost
column of all zeros looks like a cheap experiment, not like a parsing bug. duva-bench pins the
aliases in `models.py` and asserts them in
`test_compare_rows_are_camel_case_and_carry_labels_and_axes`.

**Fix ADP should make:** serialize `/runs/compare` and `/runs/{id}/stats` through the same
snake_case projection as everything else, or document the split.

---

## What held up exactly as documented

Worth recording too, since it is the part this project depends on most.

- `ADP-API-Version` is served on **every** response, including 401s and 404s. The startup assertion
  runs before this client holds a token, which is the case worth catching.
- A batch skipping the emitter's numbering is rejected **whole**, with `expected_next_seq` naming the
  resume point. The spool replays from it rather than guessing.
- `accepted_through` is `null` for an emitter that sends no `producer_seq` — untracked, not
  incomplete. A spool must not read that as zero.
- `verify` reports `chains_ok` and `emitters_ok` as separate answers, with per-session
  `emitter_tracked` / `emitter_complete` / `emitter_first_gap`. A chain that verifies perfectly can
  still be missing an event that never arrived, and ADP says so rather than averaging the two into
  one comforting boolean.
- Opening a run with an `external_ref` that already names an open run returns **200 with the
  existing run** rather than creating a second one. M5's resume is built on this.
- `/runs/compare` returns `evals[]` — the latest result *per axis* — alongside the single latest
  `eval`. Ranking per axis needs the former; the latter would make the surviving score depend on
  which POST landed last.
