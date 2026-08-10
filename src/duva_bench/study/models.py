"""The study spec (M1).

A study is data. Everything here is ``frozen=True, extra="forbid"``: frozen
because a spec that can be mutated after its digest is computed is a spec whose
digest attests nothing, and extra-forbidden because a mistyped key that silently
does nothing is the single cheapest way to run the wrong experiment and not find
out.

The digests are plain properties rather than pydantic computed fields on
purpose. A computed field would appear in ``model_dump()``, and the dump is what
the digest is computed over — a digest of a payload containing itself.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Annotated, Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from duva_bench.study.digest import digest_payload, reject_floats, short

SLUG = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")

DocsGrade = Literal["none", "reference", "rich"]

Slug = Annotated[str, Field(pattern=SLUG.pattern, min_length=1, max_length=64)]
Sha256 = Annotated[str, Field(pattern=SHA256.pattern)]


class Spec(BaseModel):
    """Base for every spec model: frozen, closed, and digestible."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    def digest_source(self) -> dict[str, Any]:
        """The JSON form this model's digest is computed over."""
        return self.model_dump(mode="json")

    @property
    def digest(self) -> str:
        return digest_payload(self.digest_source())


class GitSource(Spec):
    """A task fetched from git rather than carried in the repository."""

    url: str
    rev: str = Field(description="A commit sha or tag. A branch name is not a pin.")
    subdir: str | None = None


class TaskRef(Spec):
    """One task, and the grader that scores it.

    The grader's sha256 is part of the spec rather than read at execution time.
    A grader that changed between two arms is a different instrument, and an
    experiment that cannot tell says its arms were compared when they were not.
    """

    id: Slug
    path: str | None = None
    git: GitSource | None = None
    grader_path: str
    grader_sha256: Sha256
    # Free-form, digested. Where a task carries knobs the harness passes through.
    parameters: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _exactly_one_source(self) -> TaskRef:
        if (self.path is None) == (self.git is None):
            raise ValueError(f"task {self.id!r} needs exactly one of `path` or `git`")
        reject_floats(self.parameters, f"tasks.{self.id}.parameters")
        return self


class ModelSpec(Spec):
    """Provider, model, and whatever parameters the arm pins."""

    provider: Slug
    model: str
    parameters: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _parameters_are_digestible(self) -> ModelSpec:
        reject_floats(self.parameters, f"{self.provider}/{self.model} parameters")
        return self


class HarnessSpec(Spec):
    """A Harbor agent, pinned.

    ``version`` is not decoration. squad-lab's four incidents were harness
    defects read as model deficiencies; an unpinned harness is a factor that
    varies without being recorded, which is the whole failure in one line.
    """

    agent: str
    version: str


class DocsBundle(Spec):
    """How much documentation the arm's tools ship with (M4).

    ``none`` is the absence of documentation, not a missing value: an arm that
    deliberately withholds docs is a treatment, and rendering it as "unknown"
    would put it in the same bucket as one nobody configured.
    """

    grade: DocsGrade = "none"
    # Set once the bundle is materialized (M4); the spec digest covers the
    # grade, and this pins the bytes when they exist. Named `content_digest`
    # rather than `digest` because every spec here already has a `digest` — the
    # digest *of the bundle spec* — and two things called the same thing on one
    # object is a bug waiting for a hurried reader.
    content_digest: str | None = None


class ToolsetSpec(Spec):
    """A named toolset, identified per tool rather than by its name.

    ``tools`` maps tool name to the digest of that tool's definition. A toolset
    whose identity were its name alone would let a renamed parameter travel
    between arms unrecorded — which is exactly the manipulation M4's twins
    exist to make measurable.
    """

    name: Slug
    tools: dict[str, str] = Field(default_factory=dict)
    docs_bundle: DocsBundle = Field(default_factory=DocsBundle)
    # Set on a twin: the toolset it is isomorphic to, and the seed that produced
    # it. Together they make the twin reproducible from the spec alone, and they
    # are what lets analysis compute a hallucinated-call rate — a call to a name
    # in `twin_of`'s vocabulary is a call to a tool this arm does not have.
    twin_of: Slug | None = None
    twin_seed: str | None = None

    @model_validator(mode="after")
    def _twin_fields_travel_together(self) -> ToolsetSpec:
        if (self.twin_of is None) != (self.twin_seed is None):
            raise ValueError(
                f"toolset {self.name!r}: `twin_of` and `twin_seed` are only meaningful "
                "together — a twin with no seed is not reproducible"
            )
        return self


class Arm(Spec):
    """One cell of the factorial: model × harness × toolset × docs × environment."""

    id: Slug
    model: ModelSpec
    harness: HarnessSpec
    toolset: ToolsetSpec
    # Environment pins. Values are strings because that is what an environment
    # holds; a number here would be a number that gets stringified somewhere
    # else and digested differently.
    env: dict[str, str] = Field(default_factory=dict)

    @property
    def docs_bundle(self) -> DocsBundle:
        return self.toolset.docs_bundle

    @property
    def arm_digest(self) -> str:
        """What this arm *is*, digested. Rides on every run as a label."""
        return self.digest

    def labels(self) -> dict[str, str]:
        """The ADP run labels for this arm (M3).

        Names and digests both: a human reading a run listing needs the names,
        and a consumer deciding whether two runs are comparable needs the
        digests. ADP labels are strings and immutable at open, so this is the
        whole of what a run says about itself.
        """
        return {
            "arm": self.id,
            "arm_digest": self.arm_digest,
            "model": f"{self.model.provider}/{self.model.model}",
            "model_digest": self.model.digest,
            "harness": f"{self.harness.agent}@{self.harness.version}",
            "harness_digest": self.harness.digest,
            "toolset": self.toolset.name,
            "toolset_digest": self.toolset.digest,
            "docs": self.toolset.docs_bundle.grade,
        }


class Amendment(Spec):
    """A change to a pre-registered analysis choice, made after the fact.

    Amendments are allowed. Silent ones are not: the pre-amendment value is
    carried here, so the original reading stays computable and a report can
    print both. That is the difference between an amended pre-registration and
    no pre-registration at all.
    """

    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    field: str
    previous: Any
    rationale: str = Field(min_length=1)


class PreRegistration(Spec):
    """The analysis block, digested before execution.

    Amendable fields are named in :data:`AMENDABLE`, and an amendment carries
    the value that was replaced. :meth:`original` unapplies them in reverse, so
    ``original_digest`` is the number a reader would have computed before the
    study ran.
    """

    primary_metric: str
    secondary_metrics: tuple[str, ...] = ()
    repetitions: int = Field(ge=1)
    # The arm every pairwise contrast is against (M6). Named here rather than on
    # the arm, because which arm is the control is an analysis decision and
    # analysis decisions are what a pre-registration is.
    control_arm: Slug | None = None
    exclusion_rules: tuple[str, ...] = ()
    metaprogramming_allowed: bool = False
    amendments: tuple[Amendment, ...] = ()

    AMENDABLE: ClassVar[frozenset[str]] = frozenset(
        {
            "primary_metric",
            "secondary_metrics",
            "repetitions",
            "control_arm",
            "exclusion_rules",
            "metaprogramming_allowed",
        }
    )

    @model_validator(mode="after")
    def _amendments_name_amendable_fields(self) -> PreRegistration:
        for amendment in self.amendments:
            if amendment.field not in self.AMENDABLE:
                raise ValueError(
                    f"amendment on {amendment.field!r}: only {sorted(self.AMENDABLE)} are "
                    "pre-registered analysis choices, so only those can be amended"
                )
        return self

    def original(self) -> PreRegistration:
        """This block as it read before any amendment.

        Unapplied newest-first, so a field amended twice lands on the value it
        held at pre-registration rather than at the second-to-last edit.
        """
        values = self.model_dump()
        for amendment in reversed(self.amendments):
            values[amendment.field] = amendment.previous
        values["amendments"] = ()
        return PreRegistration.model_validate(values)

    @property
    def pre_registration_digest(self) -> str:
        return self.digest

    @property
    def original_digest(self) -> str:
        return self.original().digest

    @property
    def amended(self) -> bool:
        return bool(self.amendments)


class AdpTarget(Spec):
    """Where runs are recorded.

    Not in the plan's field list for ``Study``, and added as the smallest thing
    that lets M3 open a run: every ADP path is scoped to ``{owner}/{repo}``, so
    without these a study cannot be executed at all. The base URL and both
    tokens stay in the environment (execution-plan §0.7) — only the coordinates
    of the repository are part of the spec, because those are part of *which
    experiment this is*.
    """

    owner: str
    repo: str
    # ADP's `orchestrator` field: opaque to ADP, and this is what identifies the
    # thing that opened the run.
    orchestrator: str = "duva-bench"


class Study(Spec):
    """A whole experiment, as a file."""

    title: str = Field(min_length=1)
    adp: AdpTarget
    tasks: tuple[TaskRef, ...] = Field(min_length=1)
    arms: tuple[Arm, ...] = Field(min_length=1)
    repetitions: int = Field(ge=1)
    # Money as a string in the file: `25.00` read as a float would make the
    # digest depend on the YAML parser. Decimal keeps the written value.
    budget_usd_cap: Decimal = Field(gt=0)
    concurrency: int = Field(ge=1)
    # Requests per minute per provider, enforced by M5's scheduler. Absent means
    # unlimited, which is the right default for a local model and the wrong one
    # for a paid API — so a study that needs it says so.
    provider_rate_limits: dict[Slug, int] = Field(default_factory=dict)
    pre_registration: PreRegistration

    @model_validator(mode="before")
    @classmethod
    def _budget_is_not_a_float(cls, data: Any) -> Any:
        if isinstance(data, dict) and isinstance(data.get("budget_usd_cap"), float):
            raise ValueError(
                "budget_usd_cap was read as a float, whose decimal form depends on the "
                'parser; write it as a string ("25.00") so the study digest is stable'
            )
        return data

    @model_validator(mode="after")
    def _internally_consistent(self) -> Study:
        _reject_duplicates("task", [task.id for task in self.tasks])
        _reject_duplicates("arm", [arm.id for arm in self.arms])

        if self.pre_registration.repetitions != self.repetitions:
            raise ValueError(
                f"the study runs {self.repetitions} repetitions and the pre-registration "
                f"declares {self.pre_registration.repetitions}. One of them is the number "
                "the analysis was designed around, and nothing here can tell which."
            )

        control = self.pre_registration.control_arm
        if control is not None and control not in {arm.id for arm in self.arms}:
            raise ValueError(
                f"the pre-registered control arm {control!r} is not one of this study's "
                "arms, so every pairwise contrast would be against nothing"
            )

        for arm in self.arms:
            twin_of = arm.toolset.twin_of
            known = {other.toolset.name for other in self.arms}
            if twin_of is not None and twin_of not in known:
                raise ValueError(
                    f"arm {arm.id!r} twins toolset {twin_of!r}, which no arm in this study "
                    "uses — a twin with no original is not a contrast"
                )
        return self

    # --- identity -------------------------------------------------------------

    @property
    def study_digest(self) -> str:
        return self.digest

    @property
    def slug(self) -> str:
        """Short digest, as used in ``external_ref`` and intent titles."""
        return short(self.study_digest)

    # --- lookups --------------------------------------------------------------

    def task(self, task_id: str) -> TaskRef:
        for task in self.tasks:
            if task.id == task_id:
                return task
        raise KeyError(f"no task {task_id!r} in this study; it has {[t.id for t in self.tasks]}")

    def arm(self, arm_id: str) -> Arm:
        for arm in self.arms:
            if arm.id == arm_id:
                return arm
        raise KeyError(f"no arm {arm_id!r} in this study; it has {[a.id for a in self.arms]}")

    @property
    def trial_count(self) -> int:
        return len(self.tasks) * len(self.arms) * self.repetitions


def _reject_duplicates(what: str, ids: list[str]) -> None:
    seen: set[str] = set()
    for identifier in ids:
        if identifier in seen:
            raise ValueError(
                f"two {what}s share the id {identifier!r}; ids are how results are joined "
                "back to the spec, so a duplicate silently merges two cells"
            )
        seen.add(identifier)
