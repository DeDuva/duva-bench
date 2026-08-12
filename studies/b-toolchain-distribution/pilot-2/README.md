# Pilot 2's evidence, recovered

60 trials, `claude-haiku-4-5`, `terminus-2@0.20.0`, 4 tasks × 3 substrates × 5
repetitions, $12.486, study digest `sha256:ed1bb8235a36…`, run 2026-08-11.
**This is the run amendment §7.1 argues from**, and until 2026-08-11 none of the
numbers it argues from could be re-derived from anything in this repository.

## Why this directory exists

Three things were separately true and together made the run unverifiable:

1. `../report/report.json` is the **pre-fix** report — 120 of 120 axis scores are
   `null`, because the grader searched for `report.py` after packages had become
   `report/__init__.py`;
2. the ADP evals were left unscored on purpose rather than quietly re-posted, and
   that ADP instance is ephemeral;
3. the local artifacts the re-grade ran over were in `.duva-bench/` inside a git
   worktree on an **already-merged** branch — gitignored, and one
   `git worktree remove` from gone.

For a day this repository's ledger recorded them as lost, on the strength of a
search that did not go deep enough to find them. Both halves of that are worth
keeping: evidence that lives only in a gitignored scratch directory is evidence
with a countdown on it, and a claim that it is *gone* deserves the same scepticism
as a claim that it is fine.

## What is here

| | |
|---|---|
| `trajectories/` | 60 ATIF trajectories, one per trial. The escape metric is computed from these and nothing else. |
| `trials/` | 60 duva-bench trial records, carrying `harbor_verifier_passed` — which is the outcome axis. |
| `recover.py` | Recomputes the numbers from both. Writes `recovered.json`. |
| `recovered.json` | The output, committed so a reader need not run anything. |

**Not here:** the collected workspaces a grader reads (6.2 MB). Re-grading needs
them; nothing below does. All 60 were re-graded on 2026-08-11 and the graders
agreed with the verifier on every one, which is why `harbor_verifier_passed`
reproduces the acceptance means exactly.

## What it recovers

| arm | acceptance | escaped | escape calls | reached for |
|---|---|---|---|---|
| `oss` | 0.850 | **0/20** | 0 | — |
| `twin` | 0.950 | **6/20** | 29 | `pytest` |
| `proprietary` | 0.850 | **3/20** | 3 | `pytest` |

Identical to the table in the design document's §7.1 — which was counted **by
hand**, under a detector since rewritten (§7.1.1). That it reproduces exactly is
evidence the rewrite did not move the finding it was written to protect. The
rewritten detector also finds **zero** probes and no false positives: `pytest` is
the only foreign command invoked in any arm, so the whole effect is one habit
rather than a scatter.

Note `twin`'s 29 escape *calls* against `proprietary`'s 3. The twin arm did not
merely reach for `pytest`; it reached repeatedly, which is the flailing the cost
column was already showing.

### And the caveat the table does not carry

| task | oss | twin | proprietary |
|---|---|---|---|
| `add-median` | 0/5 | 1/5 | 0/5 |
| `fix-spread` | 0/5 | 0/5 | 2/5 |
| `strict-mode` | 0/5 | **4/5** | 0/5 |
| `use-validator` | 0/5 | 1/5 | 1/5 |

**Four of the twin arm's six escapes are one cell.** The statistics resample
tasks whole, so the effective *n* behind H5 is four tasks rather than twenty
trials — the same shape as pilot 1's cost ordering, which turned out to be one
task of four. Two tests in `tests/test_study_b_specs.py` pin both this and the
table above, so neither can quietly stop being true while the prose still says it.

## This is a recovery, not a report

A report is what `duva-bench report` builds by reading ADP, and pilot 2's ADP
record is unscored and gone. Nothing here substitutes for that. It exists so the
amendment's rationale cites numbers a reader can check.

The vocabulary matters when reading `recover.py`: pilot 2's twin was the
hand-written `kelvra`/`brivols`/`tomak` one. Both twins are seed-drawn now
(§7.1.2), and recomputing pilot 2 under today's names would find no escapes at
all and report it as a result.
