"""One trial, end to end (M3).

A trial is (task, arm, repetition). Running it means:

1. mint or reuse the task's ADP intent
2. open a run whose ``external_ref`` and labels say exactly which cell it is
3. hand the task to Harbor
4. bridge Harbor's trace into ADP events
5. close the run against a final git sha, or abandon it
6. run the evidence gate
7. write a local record holding pointers and a verdict — and nothing else

Step 7 is the one with a rule attached. ``trial.json`` carries the ADP run id,
the external ref, the verdict, and the digests. It carries **no scores and no
statistics**, because a result has to be reconstructible from ADP; a number
cached locally is a number that can disagree with the system of record, and then
nobody can say which one the experiment produced.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from duva_bench import ADAPTER_VERSION
from duva_bench.adp.artifacts import MAX_FILE_BYTES, publish_trial_artifacts
from duva_bench.adp.client import AdpClient, AdpError
from duva_bench.adp.gate import Verdict, verify_gate
from duva_bench.adp.recorder import Recorder
from duva_bench.adp.spool import Spool
from duva_bench.exec.bridge import AdpEvent, bridge
from duva_bench.exec.harbor import HarborExecutor, HarborFailed, HarborTrial, TrialExecutor
from duva_bench.state import StateDir
from duva_bench.study.models import Arm, Study, TaskRef

logger = logging.getLogger(__name__)

# The all-zero sha, kept only as the fallback for a grader that somehow runs
# without a published commit. It is **not** what runs close against: ADP rejects
# a sha it cannot resolve in the repository (422), so this value could never
# close a run. What closes a run is the commit made by
# `duva_bench.adp.artifacts.publish_trial_artifacts` out of the trial's own
# artifacts. See that module for why.
NULL_GIT_SHA = "0" * 40

Outcome = Literal["VERIFIED", "ERROR"]


@dataclass(frozen=True)
class Trial:
    """One cell of the factorial, at one repetition."""

    task_id: str
    arm_id: str
    repetition: int

    def external_ref(self, study: Study) -> str:
        """The run's identity, as M3 specifies it.

        This string is what makes a rerun rejoin instead of duplicating: ADP
        returns the existing open run for an ``external_ref`` it already has.
        Analysis never parses it — labels carry the same facts in a form
        nothing has to split on colons to read — but a human scanning a run
        list needs one glance to know which cell a row is.
        """
        return f"{study.slug}:{self.arm_id}:{self.task_id}:r{self.repetition}"

    def label(self, study: Study) -> str:
        """A filesystem-safe name for Harbor's job directory."""
        return f"{study.slug}__{self.arm_id}__{self.task_id}__r{self.repetition}"


class TrialRecord(BaseModel):
    """The local record of a trial: pointers and a verdict.

    Frozen and closed like the study spec, for the same reason — and short, by
    design. Anything a reader wants beyond this is in ADP.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    study_digest: str
    task_id: str
    arm_id: str
    arm_digest: str
    repetition: int
    external_ref: str
    intent_id: str
    run_id: str | None
    verdict: Outcome
    failures: tuple[str, ...] = ()
    # Harbor's own verifier, kept because it is evidence about the environment
    # rather than a score: None when it did not run.
    harbor_verifier_passed: bool | None = None
    # Which axes were scored — the *names*, never the numbers. The numbers live
    # in ADP under the grader identity, and a local copy would be a second
    # source of truth for the one thing this design exists to make singular.
    scored_axes: tuple[str, ...] = ()
    grader_error: str | None = None
    events_recorded: int = 0
    final_git_sha: str | None = None
    # The git ref the trial's artifacts were published under, so a reader can
    # fetch what the agent actually produced rather than infer it.
    artifact_ref: str | None = None
    trial_dir: str | None = None
    harbor_command: tuple[str, ...] = ()
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.verdict == "VERIFIED"


def intent_title(study: Study, task_id: str) -> str:
    """The title convention that makes intent minting idempotent.

    ADP mints a new intent for every issue filed, even with a repeated title, so
    idempotence has to come from looking first. Keyed by study digest as well as
    task id: two studies scoring the same task are two experiments, and sharing
    an intent would put their runs on one ``/runs/compare`` page where nothing
    could tell them apart.
    """
    return f"duva:{study.slug}:{task_id}"


def ensure_intent(client: AdpClient, study: Study, task_id: str, state: StateDir) -> str:
    """The intent for this task in this study, minted at most once."""
    cached = state.known_intents().get(task_id)
    if cached:
        return cached

    title = intent_title(study, task_id)
    existing = client.find_intent(study.adp.owner, study.adp.repo, title=title)
    issue = existing or client.mint_intent(
        study.adp.owner,
        study.adp.repo,
        title=title,
        body=(
            f"Intent for task {task_id!r} in duva-bench study {study.title!r} "
            f"({study.study_digest}). Filed by duva-bench because ADP has no native "
            "intent endpoint; every run for this task in this study hangs off it."
        ),
    )
    state.remember_intent(task_id, issue.intent_id)
    return issue.intent_id


MAX_ATTEMPTS = 20


def _open_run(
    client: AdpClient,
    study: Study,
    *,
    intent_id: str,
    external_ref: str,
    labels: dict[str, str],
) -> tuple[Any, str]:
    """Open the run for this cell, retrying under a new attempt when it must.

    ADP gives an ``external_ref`` one run for ever: a second `POST /runs` with a
    ref whose run is closed or abandoned is a 409, and there is no reopening.
    That is right for a *result* — a closed run is evidence and must not be
    rewritten — and it makes a cell whose attempt died for an infrastructure
    reason permanently unfillable. Over 480 trials, a single evicted container
    would leave a hole nothing could repair by rerunning.

    So a retry is a new **attempt** of the same cell: `…:r1` becomes `…:r1/a2`,
    `…/a3`, and so on. Nothing downstream parses the ref — `Trial.external_ref`
    says so, and analysis groups by the `task`, `arm` and `repetition` labels —
    so the cell is still one cell to every reader that matters, while the failed
    attempt stays on the record instead of being overwritten by the retry.

    **Only an abandoned run earns a retry.** A *closed* run is a finished trial
    and a piece of evidence; quietly opening a second one beside it would put
    two results in a cell the study says has one, which is the duplicate M5
    exists to prevent. That case re-raises, and the caller — the scheduler's
    skip list, or a human who asked for it by hand — is told.

    The attempt is not silent: it is returned so the trial record carries the ref
    that was actually used, and a run list still shows both.
    """
    attempt = 1
    ref = external_ref
    while True:
        try:
            return client.create_run(
                study.adp.owner,
                study.adp.repo,
                intent_id=intent_id,
                orchestrator=study.adp.orchestrator,
                external_ref=ref,
                labels={**labels, "attempt": str(attempt)},
            ), ref
        except AdpError as conflict:
            if conflict.status != 409 or attempt >= MAX_ATTEMPTS:
                raise
            if not _may_retry(client, study, intent_id=intent_id, external_ref=ref):
                raise
            attempt += 1
            ref = f"{external_ref}/a{attempt}"
            logger.info(
                "%s was abandoned; retrying this cell as attempt %d (%s)",
                external_ref,
                attempt,
                ref,
            )


def _may_retry(client: AdpClient, study: Study, *, intent_id: str, external_ref: str) -> bool:
    """Whether the run occupying ``external_ref`` leaves this cell unfilled.

    Two cases earn a retry, and they are the same case seen twice: the ref is
    taken by a run that is not a result of *this* experiment.

    * **Abandoned** — the attempt produced nothing.
    * **Closed by a different adapter version** — it produced something, from an
      instrument this checkout no longer is. Reusing it would put two
      instruments in one study; refusing to retry would make the cell
      permanently unfillable after any adapter change.

    A read failure answers ``False``: not knowing why a ref is taken is not a
    licence to open a second run beside whatever is already there.
    """
    from duva_bench import ADAPTER_VERSION

    for status in ("abandoned", "closed"):
        try:
            runs = client.list_runs(
                study.adp.owner, study.adp.repo, intent_id=intent_id, status=status
            )
        except AdpError as error:
            logger.warning("could not check why %s is taken: %s", external_ref, error)
            return False
        for run in runs:
            if run.external_ref != external_ref:
                continue
            if status == "abandoned":
                return True
            return run.labels.get("adapter") != f"duva-bench/{ADAPTER_VERSION}"
    return False


def run_trial(
    study: Study,
    trial: Trial,
    *,
    state: StateDir,
    client: AdpClient | None = None,
    executor: TrialExecutor | None = None,
    study_dir: Path | None = None,
) -> TrialRecord:
    """Run one trial and return its record.

    ``client`` and ``executor`` are injected rather than constructed here so the
    suite can drive the whole path against an in-memory ADP and a recorded
    Harbor trial. The defaults are the real thing.
    """
    from duva_bench.env import adp_credentials

    task = study.task(trial.task_id)
    arm = study.arm(trial.arm_id)
    state.ensure()

    owned_client = client is None
    client = client or adp_credentials().client()
    executor = executor or HarborExecutor()
    root = Path(study_dir) if study_dir is not None else Path.cwd()

    external_ref = trial.external_ref(study)
    intent_id = ensure_intent(client, study, trial.task_id, state)

    run, external_ref = _open_run(
        client,
        study,
        intent_id=intent_id,
        external_ref=external_ref,
        labels={
            # What produced this trial, not just what it ran. See
            # duva_bench.ADAPTER_VERSION for why this is a label and not part of
            # the arm's digest.
            "adapter": f"duva-bench/{ADAPTER_VERSION}",
            "study": study.study_digest,
            "study_title": study.title,
            "task": task.id,
            "repetition": str(trial.repetition),
            **arm.labels(),
        },
    )
    session = client.create_session(
        study.adp.owner,
        study.adp.repo,
        harness=f"{arm.harness.agent}@{arm.harness.version}",
        run_id=run.id,
    )

    record_kwargs: dict[str, Any] = {
        "study_digest": study.study_digest,
        "task_id": task.id,
        "arm_id": arm.id,
        "arm_digest": arm.arm_digest,
        "repetition": trial.repetition,
        "external_ref": external_ref,
        "intent_id": intent_id,
        "run_id": run.id,
    }

    try:
        harbor_trial: HarborTrial | None = None
        error: str | None = None
        try:
            harbor_trial = executor.execute(
                task,
                arm,
                task_dir=_arm_task_dir(study, task, arm, root=root, state=state),
                work_dir=state.root / "work" / trial.label(study),
                label=trial.label(study),
            )
        except (HarborFailed, OSError) as failure:
            # The trial did not produce a trajectory. That is a real outcome and
            # it is recorded as one: the run is abandoned with the reason, and
            # the verdict comes from the gate like any other trial's.
            error = str(failure)
            logger.warning("harbor failed for %s: %s", external_ref, failure)

        events = (
            bridge(
                harbor_trial.trajectory,
                harbor_trial.results,
                final_git_sha=None,
            )
            if harbor_trial is not None
            else [
                _harbor_failure_event(error or "Harbor produced no trial"),
            ]
        )

        spool = Spool(state.spool(external_ref))
        with Recorder(client, study.adp.owner, study.adp.repo, session.id, spool) as recorder:
            for event in events:
                recorder.record(event.kind, **event.as_fields())
            recorder.flush(timeout=120)

        produced_work = harbor_trial is not None and not harbor_trial.failed_with_exception
        final_git_sha: str | None = None
        if produced_work and harbor_trial is not None:
            # ADP closes a run against a commit it can resolve, and a container
            # that no longer exists is not one. Publishing what the trial
            # collected gives the attestation a subject that can be fetched by
            # sha for as long as the repository lives. See adp/artifacts.py.
            published = publish_trial_artifacts(
                client,
                study.adp.owner,
                study.adp.repo,
                directory=harbor_trial.graded_dir,
                manifest={
                    "study_digest": study.study_digest,
                    "arm_id": arm.id,
                    "arm_digest": arm.arm_digest,
                    "task_id": task.id,
                    "repetition": trial.repetition,
                    "external_ref": external_ref,
                    "harbor_command": list(harbor_trial.command),
                    "harbor_exit_code": harbor_trial.exit_code,
                    "verifier_passed": harbor_trial.verifier_passed,
                },
                external_ref=external_ref,
                message=f"duva-bench trial {external_ref}",
            )
            final_git_sha = published.commit_sha
            record_kwargs["artifact_ref"] = published.ref
            if published.skipped:
                logger.warning(
                    "%s: %d artifact(s) exceeded %d bytes and were recorded by name only: %s",
                    external_ref,
                    len(published.skipped),
                    MAX_FILE_BYTES,
                    ", ".join(published.skipped),
                )
            client.close_run(study.adp.owner, study.adp.repo, run.id, final_git_sha=final_git_sha)
        else:
            client.abandon_run(
                study.adp.owner,
                study.adp.repo,
                run.id,
                reason=error or "the agent produced no result",
            )

        # Grading comes after the run is closed and before the gate, in that
        # order and for two reasons: an eval needs the commit the run was closed
        # against, and the gate's answer includes whether the score was reported
        # by somebody other than the runner.
        scored_axes: tuple[str, ...] = ()
        grader_error: str | None = None
        if produced_work and harbor_trial is not None:
            scored_axes, grader_error = _grade(
                study,
                task,
                harbor_trial,
                client=client,
                run_id=run.id,
                root=root,
                # The commit the run was closed against, so the score is bound
                # to the same subject the attestation names. ADP will take the
                # run's own final_git_sha if this is omitted; passing it makes
                # the binding explicit rather than incidental.
                git_sha=final_git_sha or NULL_GIT_SHA,
            )

        verdict: Verdict = verify_gate(client, study.adp.owner, study.adp.repo, run.id)
        record = TrialRecord(
            **record_kwargs,
            verdict=verdict.status,
            failures=verdict.failures,
            scored_axes=scored_axes,
            grader_error=grader_error,
            harbor_verifier_passed=(
                harbor_trial.verifier_passed if harbor_trial is not None else None
            ),
            events_recorded=recorder.stats.appended,
            final_git_sha=final_git_sha,
            trial_dir=str(harbor_trial.trial_dir) if harbor_trial is not None else None,
            harbor_command=harbor_trial.command if harbor_trial is not None else (),
            error=error,
        )
    finally:
        if owned_client:
            client.close()

    state.write_json(state.trial_record(external_ref), record.model_dump(mode="json"))
    return record


def _grade(
    study: Study,
    task: TaskRef,
    harbor_trial: HarborTrial,
    *,
    client: AdpClient,
    run_id: str,
    root: Path,
    git_sha: str,
) -> tuple[tuple[str, ...], str | None]:
    """Run the task's grader and post one eval per axis.

    Returns the axis names that were recorded and the grader's error, if any.
    **No scores come back**: they belong in ADP, under the grader identity, and
    a copy here would be a second source of truth for the one number the whole
    design is about.
    """
    from duva_bench.grading.runner import GraderError, GraderRunner, report_axes

    grader = (root / task.grader_path).resolve()
    runner = GraderRunner()
    try:
        result = runner.run(grader, harbor_trial.graded_dir, expected_sha256=task.grader_sha256)
    except GraderError as failure:
        # A grader that will not run leaves the trial unscored. Not zero, and
        # not an ERROR either: the trajectory is still evidence about what the
        # arm did; what is missing is the measurement.
        logger.warning("grader for %s did not run: %s", task.id, failure)
        return (), str(failure)

    if not result.scored:
        logger.warning("grader for %s produced no result: %s", task.id, result.error)
        return (), result.error

    posted = report_axes(
        client,
        study.adp.owner,
        study.adp.repo,
        run_id,
        result,
        git_sha=git_sha,
    )
    return tuple(posted), None


def _harbor_failure_event(reason: str) -> AdpEvent:
    return AdpEvent(
        kind="custom",
        type="duva_bench.executor_failure",
        status="error",
        payload={"reason": reason},
    )


def _arm_task_dir(study: Study, task: TaskRef, arm: Arm, *, root: Path, state: StateDir) -> Path:
    """The task directory this arm actually runs, materialized if it differs.

    An arm that manipulates neither tools nor documentation runs the task as its
    author wrote it — copying it would add a failure mode and change nothing.
    Otherwise the arm gets its own copy with its toolset installed and its
    documentation injected, because that is the only way those factors reach the
    container at all: they were digested and labelled and never applied until
    2026-08-10, so arms differing only in them were one arm with several names.
    """
    from duva_bench.arms.materialize import materialize
    from duva_bench.arms.twin import load_definition

    source = _task_dir(root, task)
    manipulates_docs = arm.toolset.docs_bundle.grade != "none"
    if arm.toolset.definition_path is None and not manipulates_docs:
        return source

    definition: dict[str, Any] = {"name": arm.toolset.name, "tools": []}
    if arm.toolset.definition_path is not None:
        definition = load_definition(root / arm.toolset.definition_path)

    destination = state.root / "variants" / f"{task.id}__{arm.id}"
    materialized = materialize(
        task, arm, source=source, destination=destination, toolset_definition=definition
    )
    # Beside the variant, never inside it. An agent that could read the rename
    # map would have been handed the vocabulary it is being tested without.
    materialized.write_rename_map(state.root / "rename-maps" / f"{task.id}__{arm.id}.json")
    return materialized.path


def _task_dir(root: Path, task: TaskRef) -> Path:
    """Where the task lives on disk.

    Relative paths in a study file are relative to the study file, not to the
    caller's working directory: a study is a document that travels.
    """
    if task.path is None:
        raise NotImplementedError(
            f"task {task.id!r} is sourced from git, which M3 does not fetch. Vendor the "
            "task or add a fetch step; a study that silently ran a different revision "
            "than the one it pinned would be worse than this error."
        )
    return (root / task.path).resolve()
