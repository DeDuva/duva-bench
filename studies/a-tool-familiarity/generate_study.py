#!/usr/bin/env python3
"""Write Study A's study.yaml, with every digest computed rather than typed.

Sixteen arms with hand-written tool digests is sixteen chances to paste the
wrong sha, and a wrong tool digest is a hallucinated-call rate computed against
the wrong vocabulary — which would look like a spectacular finding.

Run after generate.py, which is what changes the grader hashes.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from duva_bench.arms.materialize import toolset_digests
from duva_bench.arms.twin import twin_toolset

ROOT = Path(__file__).resolve().parent

# One seed for every twin arm in the study: the four familiarity arms of a
# model x harness cell have to differ in exactly one thing, and two seeds would
# make them two instruments.
TWIN_SEED = "study-a-2026"

MODELS = {
    "sonnet": {"provider": "anthropic", "model": "claude-sonnet-4-5-20250929"},
    "haiku": {"provider": "anthropic", "model": "claude-haiku-4-5-20251001"},
}

HARNESSES = {
    "terminus": {"agent": "terminus-2", "version": "0.20.0"},
    "claudecode": {"agent": "claude-code", "version": "0.20.0"},
}

# The factor under test. Each entry is (toolset name, twin?, docs grade).
FAMILIARITY = {
    "standard": ("standard", False, "none"),
    "twin": ("standard-twin", True, "none"),
    "twin-ref": ("standard-twin", True, "reference"),
    "twin-rich": ("standard-twin", True, "rich"),
}

TASKS = [
    "config-merge",
    "semver-compare",
    "safe-path",
    "csv-dedupe",
    "rate-window",
    "log-summary",
]


def main() -> None:
    definition = json.loads((ROOT / "toolset.json").read_text(encoding="utf-8"))
    standard = toolset_digests(definition)
    twin = twin_toolset(definition, seed=TWIN_SEED)
    twinned = toolset_digests(twin.definition)

    arms = []
    for level, (toolset_name, is_twin, docs) in FAMILIARITY.items():
        for model_key, model in MODELS.items():
            for harness_key, harness in HARNESSES.items():
                toolset: dict[str, object] = {
                    "name": toolset_name,
                    # The vocabulary this arm actually has. Analysis computes the
                    # hallucinated-call rate against exactly these names.
                    "tools": twinned if is_twin else standard,
                    "docs_bundle": {"grade": docs},
                }
                if is_twin:
                    toolset["twin_of"] = "standard"
                    toolset["twin_seed"] = TWIN_SEED
                arms.append(
                    {
                        "id": f"{level}-{model_key}-{harness_key}",
                        "model": {**model, "parameters": {"temperature": "0"}},
                        "harness": harness,
                        "toolset": toolset,
                        "env": {"LANG": "C.UTF-8", "PYTHONHASHSEED": "0"},
                    }
                )

    tasks = []
    for task in TASKS:
        grader = ROOT / "graders" / f"{task}.py"
        tasks.append(
            {
                "id": task,
                "path": f"tasks/{task}",
                "grader_path": f"graders/{task}.py",
                "grader_sha256": hashlib.sha256(grader.read_bytes()).hexdigest(),
            }
        )

    document = {
        "title": "Study A — tool familiarity",
        "adp": {"owner": "duva", "repo": "bench-study-a", "orchestrator": "duva-bench"},
        "tasks": tasks,
        "arms": arms,
        "repetitions": 5,
        # 480 trials. The cap is deliberately generous and deliberately present:
        # its job is to stop a runaway, not to be the number the study lands on.
        "budget_usd_cap": "250.00",
        "concurrency": 8,
        "provider_rate_limits": {"anthropic": 20},
        "pre_registration": {
            "primary_metric": "process:hallucinated_call_rate",
            "secondary_metrics": [
                "acceptance",
                "process:tool_error_rate",
                "process:metaprogramming_rate",
            ],
            "repetitions": 5,
            "control_arm": "standard-sonnet-terminus",
            "exclusion_rules": [
                "A trial whose ADP /verify is not ok:true is ERROR: excluded from every statistic, counted separately, never a failure.",
                "A trial whose grader did not produce a result is unscored on that axis and enters no cell; it is never scored zero.",
                "A repetition verdict is a majority over the cell's repetitions with ERROR trials counting against, so an arm cannot improve its record by failing to produce evidence.",
                "No trial is excluded for its result. Only the two conditions above remove a trial from a statistic.",
            ],
            "metaprogramming_allowed": True,
        },
    }

    out = ROOT / "study.yaml"
    out.write_text(
        yaml.safe_dump(document, sort_keys=True, default_flow_style=False, allow_unicode=True),
        encoding="utf-8",
    )
    print(f"{out}: {len(arms)} arms x {len(tasks)} tasks x 5 reps = {len(arms) * len(tasks) * 5}")
    print("twin names:", json.dumps(twin.rename_map["tools"], indent=2, sort_keys=True))

    # The rename map is part of the instrument and is kept beside the study,
    # outside any task directory — an agent that could read it would be handed
    # the answer, and analysis needs it only afterwards.
    (ROOT / "twin-rename-map.json").write_text(
        json.dumps(
            {"seed": TWIN_SEED, "original_digest": twin.original_digest, **twin.rename_map},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (ROOT / "toolset-twin.json").write_text(
        json.dumps(twin.definition, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
