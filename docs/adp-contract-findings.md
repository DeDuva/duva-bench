# ADP contract findings

What building duva-bench's §2 client against ADP turned up. Recorded here rather than fixed: ADP
feature work is a non-goal of this plan, and a consumer's job is to report what the contract does,
not to change it.

Against **ADP contract 0.2.0**, spec digest
`sha256:3b6b726122219dc4388ca91f332c60a12ab2a55419a590ff799b61e32b3b4a50`.

Findings 1–3 were first reported by adp-replay against contract 0.1.0 (see its
`docs/adp-contract-findings.md`); each is re-pinned here by a test in `tests/contract/`. Finding 4
is new, and 0.2.0 is where it became load-bearing. Finding 5 was found on **2026-08-10**, the first
time this suite ran against a live server, and it is the one that mattered most.

**Everything before 2026-08-10 in this file was written by reading ADP's source, not by calling
it.** The suite that pins it had never executed. That is worth stating plainly, because one finding
below (#1) turned out to be fixed already and another (#5) had gone entirely unnoticed while 325
unit tests passed against a double that reproduced the same misreading.

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

**Status as of 2026-08-10: fixed server-side, and the workaround stays.** ADP gave the column a
default in `3b4af01` (2026-08-08) — and **did not bump the contract version**. It served `0.2.0`
before that commit and serves `0.2.0` after it, so no client can ask a server whether it has the fix.
Two deployments can both honestly report `0.2.0` and disagree, and the only behaviour that is correct
against both is to keep sending `payload: {}`.

The lesson is more general than the bug: a server-side fix and a contract change are different
events, and a consumer can only stop coding around something when the *contract* says so. A fix
invisible from the wire cannot be depended on.

**Tests:** `test_an_event_without_a_payload_is_accepted`,
`test_the_server_now_accepts_a_payload_less_event_but_the_workaround_stays`.

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


---

## 5. A run can only close against a commit the repository can resolve

**Severity: this one made the whole track unable to close a single run.**

`POST /api/adp/repos/{owner}/{repo}/runs/{runId}/close` takes a `final_git_sha` that the OpenAPI
document types only as a string. The server requires more than a shape: it resolves the sha in the
repository's git backend and answers **422** when it cannot.

```
commit '0000000000000000000000000000000000000000' could not be resolved in this repository
```

That is the correct behaviour and it is worth saying why, because the temptation is to read it as an
obstacle. ADP's proposition is that a run attestation binds arm labels to a trajectory digest **and a
final commit**; a sha nobody can fetch would make the attestation unfalsifiable, which is the one
thing it exists not to be.

**What it broke here.** duva-bench closed every trial against `NULL_GIT_SHA` — forty zeroes, chosen
deliberately as "the null commit" on the reasoning that a Harbor trial produces container artifacts
and no commit, and that inventing a sha would put a fiction into a signed attestation. The reasoning
was right and the conclusion was unusable: ADP rejects it, so no trial could close, and the only
remaining path was to *abandon* every run.

**Abandoning is not a substitute, and this is the trap.** An abandoned run still returns `ok: true`
from `GET /verify` — with `envelope_verified` and `trajectory_digest_matches` both `null`, meaning
*not applicable*, because only `close` mints the attestation. A gate that checks `ok` alone therefore
passes a run that nothing ever signed. Measured on 2026-08-10 against a live server:

| | abandoned run | closed against a real commit |
|---|---|---|
| `ok` | `true` | `true` |
| `envelope_verified` | `null` | `true` |
| `trajectory_digest_matches` | `null` | `true` |
| `attested_subject_sha` | `null` | the commit |

**Resolution here:** duva-bench publishes each trial's collected artifacts into the ADP repository as
a commit — through the compat plane's `git/blobs`, `git/trees`, `git/commits` and `git/refs` — and
closes against that. See `src/duva_bench/adp/artifacts.py`. This is better than a sentinel would have
been even if one were accepted: the attestation's subject is now the work product itself, fetchable
by sha, instead of a placeholder standing in for something that was thrown away with the container.

**Fix ADP might consider:** none required. If a first-class "this run produced no commit" close is
ever wanted, it needs to still mint an attestation, and it needs a contract version bump so consumers
can tell.

**Tests:** every contract test that closes a run now builds a real commit first
(`_resolvable_sha`); `test_a_completed_trial_verifies_and_is_closed` asserts the published commit and
its ref.

---

## 6. `git/trees` takes one level at a time, unlike GitHub's

**Severity: every trial with an artifact in a subdirectory.**

`POST /api/v3/repos/{owner}/{repo}/git/trees` accepts entries shaped like GitHub's tree API —
`{path, mode, type, sha|content}` — and the resemblance is misleading. GitHub splits a nested
`path` like `agent/trajectory.json` into subtrees for you. ADP passes the entries to `git mktree`,
which builds exactly **one** tree level and rejects a path containing a slash:

```
{"statusCode":500,"err":{"message":"git mktree exited with code 128"}}
```

A Harbor trial's artifacts are all nested (`agent/trajectory.json`, `verifier/test-stdout.txt`), so
this fired on the first real publish.

**Workaround here:** `adp/artifacts.py` assembles the tree bottom-up, writing a tree per directory
and referencing it with `type: "tree"` and mode `040000`. That is what the git plumbing wants anyway;
the only surprise was expecting the porcelain.

**Fix ADP might consider:** split nested paths server-side, as GitHub does, or reject them with 422
and a message naming the offending path. A 500 from a subprocess is the one response a client cannot
act on.

**Test:** `test_a_completed_trial_verifies_and_is_closed` publishes a nested fixture.

## 7. A 500 from the git plumbing carries no actionable message

**Severity: diagnosis time, not correctness.**

Findings 5 and 6 both surfaced as bare 500s whose bodies named a subprocess exit code and nothing
about the request. `git mktree exited with code 128` does not say which entry was wrong, and the
first attempt at #5 said only `could not be resolved in this repository` without naming what it
looked in. Both were found by reading ADP's source rather than its responses, which is exactly the
dependency this file exists to remove.

**Fix ADP might consider:** map git plumbing failures onto 422 with the offending path or sha in the
body. A consumer can retry, correct or report a 422; there is nothing to do with a 500 except read
somebody else's source.

---

## Not an ADP finding, but recorded here because it was found the same way: Harbor 0.20.0's trace

Four of the seven defects that gate G1 turned up were assumptions about **Harbor**, not ADP, and
they share the shape of everything above: a plausible reading of another program's interface, pinned
by a fixture this project wrote from the same reading. `docs/blockers.md` lists all seven. The two
worth repeating because they corrupt *numbers* rather than crashing:

**`verifier_result` nests the reward.** Harbor writes `{"rewards": {"reward": 1.0}}`; the fixtures
carried a flat `{"reward": 1.0, "status": "passed"}`. Two modules read the flat key, so
"the verifier passed" always read as "the verifier did not run" — and `None` is deliberately not
`False` here, so nothing raised.

**Observation results carry no call id, and calls are batched.** `terminus-2` issues several shell
commands in one step and gets back **one** observation holding the whole terminal output, with no
`source_call_id` and no `tool_call_id` on it. Correlating by id finds nothing; "no result recorded"
means `error`; the first real trial therefore reported **16 tool calls and 16 tool failures** for a
task whose own verifier passed. Tool-error rate is a primary process metric for Study A, so this is
a study that cannot be read rather than a number slightly off.

The general rule this file now exists to enforce twice over: **a fixture written from documentation
tests your reading of the documentation.** Where the counterpart is a program rather than a
contract, at least one test has to talk to the program — `tests/test_harbor_cli.py` asserts the
adapter's flags against `harbor run --help`, and `tests/test_bridge.py` bridges a trajectory a real
agent actually wrote.
