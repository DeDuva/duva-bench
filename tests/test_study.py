"""M1: the study spec, its digest, and its pre-registration.

The done-condition the plan states is "digest equality is proven insensitive to
key order and sensitive to every field group", so the sensitivity test is
parameterized over the field groups rather than sampling a couple of them: a
field nobody wrote a case for is a field that can change without changing the
digest, which is the one failure this digest exists to prevent.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from duva_bench.study.digest import NonCanonicalValue, canonical_bytes, digest_payload, short
from duva_bench.study.load import StudyFileError, dump_study, load_study, parse_study
from duva_bench.study.models import PreRegistration, Study

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "smoke" / "study.yaml"


@pytest.fixture
def study() -> Study:
    return load_study(EXAMPLE)


# --- the canonical digest ---------------------------------------------------


def test_key_order_does_not_change_the_digest() -> None:
    left = {"a": 1, "b": {"c": 2, "d": [3, {"e": 4, "f": 5}]}}
    right = {"b": {"d": [3, {"f": 5, "e": 4}], "c": 2}, "a": 1}
    assert digest_payload(left) == digest_payload(right)


def test_a_float_anywhere_is_refused_by_name() -> None:
    with pytest.raises(NonCanonicalValue) as error:
        canonical_bytes({"arm": {"model": {"parameters": {"temperature": 0.2}}}})
    assert "arm.model.parameters.temperature" in str(error.value)


def test_a_float_inside_a_list_is_refused() -> None:
    with pytest.raises(NonCanonicalValue) as error:
        canonical_bytes({"weights": [1, 2.5]})
    assert "weights[1]" in str(error.value)


def test_the_digest_is_the_sha256_of_the_canonical_bytes() -> None:
    payload = {"b": 1, "a": "é"}
    expected = hashlib.sha256(canonical_bytes(payload)).hexdigest()
    assert digest_payload(payload) == f"sha256:{expected}"
    # UTF-8, not \u escapes: the digest must not depend on the encoder's policy.
    assert "é".encode() in canonical_bytes(payload)


def test_short_is_twelve_characters_of_the_hex() -> None:
    digest = digest_payload({"a": 1})
    assert short(digest) == digest.removeprefix("sha256:")[:12]
    assert len(short(digest)) == 12


# --- round trip -------------------------------------------------------------


def test_the_example_study_validates(study: Study) -> None:
    assert study.trial_count == 2 * 2 * 2
    assert [task.id for task in study.tasks] == ["json-normalizer", "retry-backoff"]
    assert [arm.id for arm in study.arms] == ["standard", "twin"]


def test_yaml_round_trips_with_a_stable_digest(study: Study) -> None:
    reparsed = parse_study(dump_study(study))
    assert reparsed == study
    assert reparsed.study_digest == study.study_digest


def test_reordering_the_file_does_not_change_the_digest(study: Study) -> None:
    document = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    shuffled = dict(reversed(list(document.items())))
    shuffled["arms"] = [dict(reversed(list(arm.items()))) for arm in shuffled["arms"]]
    assert parse_study(yaml.safe_dump(shuffled)).study_digest == study.study_digest


def test_each_grader_sha256_matches_the_file_it_names(study: Study) -> None:
    """A grader that drifted from its pin is a different instrument.

    Cheap here, and the only place it is cheap: at execution time the mismatch
    would surface after the money was spent.
    """
    for task in study.tasks:
        grader = EXAMPLE.parent / task.grader_path
        digest = hashlib.sha256(grader.read_bytes()).hexdigest()
        assert digest == task.grader_sha256, f"{task.grader_path} drifted from its pin"


# --- digest sensitivity, one case per field group ---------------------------


def _mutate(document: dict[str, Any], path: str, value: Any) -> dict[str, Any]:
    """Set ``path`` (dotted, with numeric segments indexing lists) to ``value``."""
    clone = json.loads(json.dumps(document))
    cursor: Any = clone
    parts = path.split(".")
    for part in parts[:-1]:
        cursor = cursor[int(part)] if part.isdigit() else cursor[part]
    last = parts[-1]
    if last.isdigit():
        cursor[int(last)] = value
    else:
        cursor[last] = value
    return clone


# Each case names a field group and the smallest edit that changes it. Some
# edits have to move two places at once — an arm id is referenced by
# `control_arm`, a toolset name by `twin_of`, and `repetitions` is declared both
# by the study and by its pre-registration — because a study where they
# disagree is refused before a digest is ever computed.
FIELD_GROUPS: list[tuple[str, list[tuple[str, Any]]]] = [
    ("title", [("title", "something else")]),
    ("adp", [("adp.repo", "other-repo")]),
    ("task id", [("tasks.0.id", "renamed-task")]),
    ("task source", [("tasks.0.path", "tasks/elsewhere")]),
    ("grader path", [("tasks.0.grader_path", "graders/other.py")]),
    ("grader sha256", [("tasks.0.grader_sha256", "0" * 64)]),
    (
        "arm id",
        [("arms.0.id", "renamed-arm"), ("pre_registration.control_arm", "renamed-arm")],
    ),
    ("model", [("arms.0.model.model", "some-other-model")]),
    ("model provider", [("arms.0.model.provider", "openai")]),
    ("model parameters", [("arms.0.model.parameters", {"temperature": "1"})]),
    ("harness agent", [("arms.0.harness.agent", "codex-cli")]),
    ("harness version", [("arms.0.harness.version", "9.9.9")]),
    (
        "toolset name",
        [("arms.0.toolset.name", "renamed-toolset"), ("arms.1.toolset.twin_of", "renamed-toolset")],
    ),
    ("tool definition digest", [("arms.0.toolset.tools.read_file", "sha256:" + "f" * 64)]),
    ("docs bundle grade", [("arms.0.toolset.docs_bundle.grade", "rich")]),
    ("twin seed", [("arms.1.toolset.twin_seed", "smoke-2")]),
    ("env pins", [("arms.0.env", {"LANG": "C"})]),
    ("repetitions", [("repetitions", 3), ("pre_registration.repetitions", 3)]),
    ("budget cap", [("budget_usd_cap", "6.00")]),
    ("concurrency", [("concurrency", 4)]),
    ("rate limits", [("provider_rate_limits", {"anthropic": 60})]),
    ("primary metric", [("pre_registration.primary_metric", "robustness")]),
    ("secondary metrics", [("pre_registration.secondary_metrics", ["robustness"])]),
    ("control arm", [("pre_registration.control_arm", "twin")]),
    ("exclusion rules", [("pre_registration.exclusion_rules", ["nothing is excluded"])]),
    ("metaprogramming", [("pre_registration.metaprogramming_allowed", False)]),
]


@pytest.mark.parametrize(
    ("group", "mutations"),
    FIELD_GROUPS,
    ids=[group for group, _ in FIELD_GROUPS],
)
def test_every_field_group_changes_the_digest(
    study: Study, group: str, mutations: list[tuple[str, Any]]
) -> None:
    document = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    for path, value in mutations:
        document = _mutate(document, path, value)
    mutated = parse_study(yaml.safe_dump(document))
    assert mutated.study_digest != study.study_digest, f"{group} does not affect the digest"


def test_the_repetitions_case_keeps_the_two_declarations_in_step() -> None:
    """`repetitions` appears twice, so its sensitivity case must move both."""
    document = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    document["repetitions"] = 3
    with pytest.raises(StudyFileError, match="One of them is the number"):
        parse_study(yaml.safe_dump(document))


# --- validation -------------------------------------------------------------


def test_an_unknown_key_is_refused() -> None:
    document = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    document["repetitons"] = 4  # codespell:ignore
    with pytest.raises(StudyFileError, match="repetitons"):
        parse_study(yaml.safe_dump(document))


def test_a_float_budget_is_refused_with_advice() -> None:
    document = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    document["budget_usd_cap"] = 5.0
    with pytest.raises(StudyFileError, match="write it as a string"):
        parse_study(yaml.safe_dump(document))


def test_a_task_needs_exactly_one_source() -> None:
    document = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    document["tasks"][0]["git"] = {"url": "https://example.invalid/x.git", "rev": "abc"}
    with pytest.raises(StudyFileError, match="exactly one of"):
        parse_study(yaml.safe_dump(document))


def test_duplicate_arm_ids_are_refused() -> None:
    document = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    document["arms"][1]["id"] = document["arms"][0]["id"]
    with pytest.raises(StudyFileError, match="share the id"):
        parse_study(yaml.safe_dump(document))


def test_a_control_arm_that_is_not_an_arm_is_refused() -> None:
    document = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    document["pre_registration"]["control_arm"] = "nonexistent"
    with pytest.raises(StudyFileError, match="control arm"):
        parse_study(yaml.safe_dump(document))


def test_a_twin_without_an_original_is_refused() -> None:
    document = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    document["arms"][1]["toolset"]["twin_of"] = "no-such-toolset"
    with pytest.raises(StudyFileError, match="twins toolset"):
        parse_study(yaml.safe_dump(document))


def test_a_twin_without_a_seed_is_refused() -> None:
    document = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    del document["arms"][1]["toolset"]["twin_seed"]
    with pytest.raises(StudyFileError, match="not reproducible"):
        parse_study(yaml.safe_dump(document))


def test_a_study_is_frozen(study: Study) -> None:
    with pytest.raises(Exception, match=r"frozen|immutable"):
        study.title = "renamed"  # type: ignore[misc]


# --- arms -------------------------------------------------------------------


def test_arm_labels_carry_names_and_digests(study: Study) -> None:
    labels = study.arm("twin").labels()
    assert labels["arm"] == "twin"
    assert labels["arm_digest"] == study.arm("twin").arm_digest
    assert labels["harness"] == "terminus-2@0.20.0"
    assert labels["docs"] == "none"
    assert all(isinstance(value, str) for value in labels.values())


def test_two_arms_differing_only_in_toolset_have_different_digests(study: Study) -> None:
    assert study.arm("standard").arm_digest != study.arm("twin").arm_digest


def test_an_arm_digest_does_not_depend_on_the_study_it_is_in(study: Study) -> None:
    """An arm is a thing in itself, so its digest travels between studies."""
    document = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    document["title"] = "a different study"
    other = parse_study(yaml.safe_dump(document))
    assert other.arm("standard").arm_digest == study.arm("standard").arm_digest


# --- pre-registration and amendments ----------------------------------------


def _registration(**overrides: Any) -> PreRegistration:
    base: dict[str, Any] = {
        "primary_metric": "acceptance",
        "repetitions": 2,
        "control_arm": "standard",
        "exclusion_rules": ("unverified runs are excluded",),
        "metaprogramming_allowed": False,
    }
    return PreRegistration.model_validate(base | overrides)


def test_an_unamended_registration_reads_the_same_both_ways() -> None:
    registration = _registration()
    assert not registration.amended
    assert registration.original_digest == registration.pre_registration_digest


def test_an_amendment_keeps_the_original_reading_computable() -> None:
    original = _registration()
    amended = _registration(
        primary_metric="robustness",
        amendments=(
            {
                "date": "2026-08-07",
                "field": "primary_metric",
                "previous": "acceptance",
                "rationale": "acceptance saturated at 1.0 in every cell",
            },
        ),
    )
    assert amended.amended
    assert amended.pre_registration_digest != original.pre_registration_digest
    # The point of the exercise: the pre-amendment reading survives the amendment.
    assert amended.original_digest == original.pre_registration_digest
    assert amended.original().primary_metric == "acceptance"


def test_two_amendments_to_one_field_unwind_to_the_first_value() -> None:
    amended = _registration(
        repetitions=5,
        amendments=(
            {"date": "2026-08-01", "field": "repetitions", "previous": 2, "rationale": "power"},
            {"date": "2026-08-05", "field": "repetitions", "previous": 3, "rationale": "more"},
        ),
    )
    assert amended.original().repetitions == 2


def test_an_amendment_to_something_that_is_not_an_analysis_choice_is_refused() -> None:
    with pytest.raises(ValueError, match="pre-registered analysis choices"):
        _registration(
            amendments=(
                {
                    "date": "2026-08-07",
                    "field": "amendments",
                    "previous": None,
                    "rationale": "recursive",
                },
            )
        )


def test_an_amendment_needs_a_rationale() -> None:
    with pytest.raises(ValueError):
        _registration(
            amendments=(
                {"date": "2026-08-07", "field": "primary_metric", "previous": "x", "rationale": ""},
            )
        )


# --- task substrates: one problem, posed several ways ------------------------


def _substrate_study() -> str:
    return """
title: substrate study
adp: {owner: duva, repo: bench, orchestrator: duva-bench}
tasks:
  - id: add-median
    substrates:
      oss: tasks/add-median-oss
      proprietary: tasks/add-median-proprietary
    grader_path: graders/add-median.py
    grader_sha256: "0000000000000000000000000000000000000000000000000000000000000001"
arms:
  - id: oss
    substrate: oss
    model: {provider: anthropic, model: m}
    harness: {agent: terminus-2, version: "0.20.0"}
    toolset: {name: shell}
  - id: proprietary
    substrate: proprietary
    model: {provider: anthropic, model: m}
    harness: {agent: terminus-2, version: "0.20.0"}
    toolset: {name: shell}
repetitions: 1
budget_usd_cap: "1.00"
concurrency: 1
pre_registration:
  primary_metric: acceptance
  repetitions: 1
  control_arm: oss
  exclusion_rules: ["none"]
  metaprogramming_allowed: true
"""


def test_two_arms_may_differ_only_in_the_substrate_they_run() -> None:
    """The factor the README always named and the spec never had.

    Until 2026-08-10 an arm could vary its model, harness, toolset and
    environment, and every arm ran byte-identical task files — so a study whose
    manipulation is *the toolchain a problem is posed in* could not be written
    down at all.
    """
    study = parse_study(_substrate_study())

    assert study.arm("oss").substrate == "oss"
    assert study.arm("proprietary").substrate == "proprietary"
    assert study.arm("oss").arm_digest != study.arm("proprietary").arm_digest
    assert study.arm("proprietary").labels()["substrate"] == "proprietary"


def test_an_arm_naming_no_substrate_for_a_task_that_has_them_is_refused(tmp_path: Path) -> None:
    """Picking one arbitrarily would make the headline contrast depend on dict order."""
    from duva_bench.exec.trial import _task_dir

    study = parse_study(_substrate_study())
    with pytest.raises(ValueError, match="names no substrate"):
        _task_dir(tmp_path, study.task("add-median"), substrate=None)

    with pytest.raises(ValueError, match="no substrate 'twin'"):
        _task_dir(tmp_path, study.task("add-median"), substrate="twin")


def test_a_task_cannot_be_posed_one_way_and_several_ways_at_once() -> None:
    raw = yaml.safe_load(_substrate_study())
    raw["tasks"][0]["path"] = "tasks/add-median"
    with pytest.raises(ValueError, match="one way or several"):
        parse_study(yaml.safe_dump(raw))


def test_a_study_without_substrates_still_needs_a_source() -> None:
    raw = yaml.safe_load(_substrate_study())
    del raw["tasks"][0]["substrates"]
    with pytest.raises(ValueError, match=r"needs \`path\`, \`git\`, or \`substrates\`"):
        parse_study(yaml.safe_dump(raw))
