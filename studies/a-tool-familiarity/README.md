# Study A — tool familiarity

**Question.** When a coding agent does worse with an unfamiliar toolset, how much of that is the
tools being unfamiliar rather than the tools being worse — and does documentation close the gap?

The instrument is the **semantic twin** (`src/duva_bench/arms/twin.py`): a toolset isomorphic to the
standard one, with every tool and parameter renamed to a pronounceable non-dictionary name of the
same length, and the *same handlers underneath*. An agent that does better with `read_file` than
with an identically-behaved `veshanu` did not do better at the task. It did better at a name it has
seen a million times in training. That difference is what this study measures, and the twin is the
only way to hold everything else still while varying it.

## Status: **defined, not executed**

The study file below validates and digests. Nothing in it has been run: executing it needs a
container runtime, two real provider keys and a live ADP, none of which the environment this was
built in has. Gate **G3 is blocked** — see [`docs/blockers.md`](../../docs/blockers.md).

There is deliberately no `report/` directory. An empty one would look like a study that produced
nothing; a populated one would have to be populated with something invented.

## Identity

| | |
|---|---|
| study digest | `sha256:5c83036cad205d76ffc7e021eabc36fd7c074d4d53d028bd4b83f7af0c668084` |
| pre-registration digest | `sha256:9525d432ec76e7faae84182b7cbf6fffc36afe9910b605c1cdd268804fa48622` |
| twin seed | `study-a-2026` |

The twin's vocabulary, for a reader who wants to see what "unfamiliar" means here:

| standard | twin |
|---|---|
| `apply_patch` | `bifefivizug` |
| `list_dir` | `babizafa` |
| `read_file` | `kanotuhim` |
| `run_command` | `siduvozepir` |
| `search_text` | `gofalidozuj` |
| `write_file` | `lolovutuzu` |

Regenerate everything — tasks, graders, `study.yaml`, the twin, the rename map — with:

```sh
python3 studies/a-tool-familiarity/generate.py
python3 studies/a-tool-familiarity/generate_study.py
```

Every digest in `study.yaml` is computed rather than typed. Sixteen arms of hand-written tool
digests would be sixteen chances to paste the wrong one, and a wrong tool digest means a
hallucinated-call rate computed against the wrong vocabulary — which would look like a spectacular
finding.

## The design

Four **familiarity levels**, which is the factor under test:

| arm suffix | toolset | docs | what it isolates |
|---|---|---|---|
| `standard` | the standard toolset | none | the baseline, and the control |
| `twin` | a semantic twin | none | familiarity alone — same behaviour, unknown names |
| `twin-ref` | the same twin | `reference` | how much an API reference recovers |
| `twin-rich` | the same twin | `rich` | how much worked examples add on top of the reference |

Crossed with **2 models × 2 harnesses**, because the interesting question is not "is there an
effect" but "does the effect depend on the model" — an effect that appears for one model and not
another is a finding about that model, and a study with one model could not tell.

That is 4 × 2 × 2 = **16 arms**, over **6 tasks**, at **5 repetitions**: 480 trials.

The docs grades are cumulative (`rich` = `reference` + examples) so the difference between
`twin-ref` and `twin-rich` is "examples were added" rather than "some prose changed".

Every twin arm uses **the same seed**, so the four familiarity arms of one model × harness cell
differ in exactly one thing. Two seeds would mean two instruments.

## Pre-registration

Primary metric: **hallucinated-call rate** — calls to a tool name the arm does not have. It is
computable only because the twin's rename map is kept out of the container: for a twinned arm, a
call in the *original* vocabulary is a call to a tool that does not exist.

Secondary: pass rate (`acceptance`), tool-error rate, and cost per solved task.

**Metaprogramming is recorded, not forbidden.** An agent that cannot use an unfamiliar tool may
simply write a script and run it — which looks like success and is a different behaviour. Forbidding
it would measure compliance; recording it measures what agents do, and the escape rate is reported
next to the pass rate rather than folded into it.

## Running it

```sh
duva-bench validate studies/a-tool-familiarity/study.yaml
duva-bench preflight studies/a-tool-familiarity/study.yaml
duva-bench run studies/a-tool-familiarity/study.yaml
duva-bench report studies/a-tool-familiarity/study.yaml
```

`run` is resumable and the budget cap is checked before every trial; a study this size will be
interrupted at least once, and that is expected rather than exceptional.

## What has to be true before the write-up is worth reading

Gate G3, from the plan, restated as a checklist:

- [ ] the report prints the pre-registration unchanged, or with explicit amendments and rationales
- [ ] every included run verifies (`/verify` `ok: true`); ERROR trials are counted and excluded
- [ ] **the noise floor is stated before any contrast** — a 4-point difference means nothing until
      the reader knows repeated runs of one cell vary by 6
- [ ] the familiarity × model and familiarity × docs interactions are reported **whatever their
      sign**, including the outcome where documentation does not help at all

## What this design cannot answer as it stands

Two limits, stated here rather than discovered in the write-up.

**The contrast column is against one control.** `report.json` contrasts every arm against
`standard-sonnet-terminus`, so the headline column mixes factors for the twelve arms that differ
from it in more than familiarity. The familiarity effect *within* a model × harness cell is read off
the per-cell tables, which carry every cell separately. A stratified contrast column is a change to
`duva_bench/report/build.py`, not to this study.

**Both models are Anthropic's.** That holds the provider constant, which is one fewer thing varying
and one fewer thing learned. A second provider is the obvious follow-up, and it is a change of two
lines in `generate_study.py`.
