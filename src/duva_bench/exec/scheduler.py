"""The factorial scheduler (M5).

Runs tasks × arms × repetitions, bounded, paced, capped, and resumable.

**Resume is the property everything else is arranged around.** A study is hours
of paid work; a laptop that sleeps, a container that is evicted, or a Ctrl-C at
the wrong moment must not mean starting over, and must *especially* not mean
running some trials twice. Two mechanisms, in this order:

1. ``progress.jsonl`` — append-only, one line per completed trial, flushed and
   fsynced per line. Cheap, local, and the first thing a rerun reads.
2. ADP itself — for every trial the log does not vouch for, the run list for the
   task's intent is checked for a closed run with this trial's ``external_ref``.
   The local log can be lost or stale; ADP is the system of record, and a resume
   that trusted only the local file would re-run trials that already exist.

Ordering is stable — tasks in spec order, then arms, then repetitions — so two
runs of the same study plan the same trials in the same sequence, and a partial
study is a prefix rather than a random subset.
"""

from __future__ import annotations

import logging
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from duva_bench import ADAPTER_VERSION
from duva_bench.adp.client import AdpClient, AdpError
from duva_bench.adp.models import Run
from duva_bench.exec.harbor import TrialExecutor
from duva_bench.exec.ledger import BudgetExceeded, CostLedger, ProviderLimiter
from duva_bench.exec.trial import Trial, TrialRecord, ensure_intent, run_trial
from duva_bench.state import StateDir
from duva_bench.study.models import Study

logger = logging.getLogger(__name__)


def plan_trials(study: Study) -> tuple[Trial, ...]:
    """Every cell of the factorial, in a stable order.

    Task-major, then arm, then repetition. Any order would be correct; a *fixed*
    order is what makes a partially-completed study a prefix, which is what
    makes "how far did it get" a question with an answer.
    """
    return tuple(
        Trial(task_id=task.id, arm_id=arm.id, repetition=repetition)
        for task in study.tasks
        for arm in study.arms
        for repetition in range(1, study.repetitions + 1)
    )


@dataclass
class StudyOutcome:
    """What a study run did."""

    planned: int = 0
    skipped: int = 0
    completed: list[TrialRecord] = field(default_factory=list)
    errors: list[TrialRecord] = field(default_factory=list)
    failures: dict[str, str] = field(default_factory=dict)
    budget_stopped: str | None = None
    ledger: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """True when every planned trial has a verified run.

        ERROR trials count against it. A study that finished with unverifiable
        evidence has not finished in the sense that matters.
        """
        return (
            not self.failures
            and not self.errors
            and self.budget_stopped is None
            and self.skipped + len(self.completed) == self.planned
        )

    def summary(self) -> dict[str, Any]:
        return {
            "planned": self.planned,
            "skipped": self.skipped,
            "completed": len(self.completed),
            "errors": len(self.errors),
            "failed_to_run": self.failures,
            "budget_stopped": self.budget_stopped,
            "ledger": self.ledger,
            "ok": self.ok,
        }


def completed_refs(state: StateDir) -> set[str]:
    """External refs the local progress log says are done and verified."""
    return {
        str(entry["external_ref"])
        for entry in state.progress_entries()
        if entry.get("external_ref") and entry.get("verdict") == "VERIFIED"
    }


def adp_completed_refs(client: AdpClient, study: Study, state: StateDir) -> set[str]:
    """External refs ADP holds a closed run for, per intent.

    Per intent because ``GET /runs`` caps at 200 rows (§3.6): asking once for
    "every run in the experiment" would silently answer with a page. Intents this
    study has never minted are skipped rather than created — checking what has
    been done must not create anything.

    **The local state directory is a cache here, not the source.** This used to
    read intents only from ``.duva-bench/`` and give up on a miss.
    :func:`run_study` happened to be immune, because it calls `ensure_intent`
    for every task first and that repopulates the cache — but
    :func:`study_status` does not, so `duva-bench status --check-adp` on a
    checkout whose state directory was lost reported a finished study as
    entirely unstarted while claiming it had consulted ADP. A wrong answer
    labelled as authoritative is worse than the local-only answer beside it,
    which at least says `adp_consulted: false`.

    The whole design says a result is reconstructible from ADP rather than from
    local state, so a cache miss falls back to looking the intent up by title,
    exactly as `ensure_intent` does.
    """
    known = state.known_intents()
    refs: set[str] = set()
    for task in study.tasks:
        intent_id = known.get(task.id)
        if intent_id is None:
            intent_id = _intent_from_adp(client, study, task.id)
        if intent_id is None:
            continue
        try:
            runs = client.list_runs(
                study.adp.owner, study.adp.repo, intent_id=intent_id, status="closed"
            )
        except AdpError as error:  # a read failure is not evidence of absence
            logger.warning("could not list runs for task %s: %s", task.id, error)
            continue
        refs |= {run.external_ref for run in runs if run.external_ref and _current_instrument(run)}
    return refs


def _current_instrument(run: Run) -> bool:
    """Whether this run was produced by the adapter now installed.

    A closed run satisfies a cell only if the thing that produced it is the
    thing that would produce it again. Gate G1 fixed seven defects in the
    adapter and the bridge in one day — one of them recorded every tool call as
    a failure — and without this check a study would skip those cells for ever,
    quietly reporting a mix of two instruments as one experiment.

    A run with no `adapter` label predates the label entirely, which is the same
    answer: not this instrument. It gets re-run under a new attempt rather than
    reused, and the old run stays on the record.
    """
    return run.labels.get("adapter") == f"duva-bench/{ADAPTER_VERSION}"


def _intent_from_adp(client: AdpClient, study: Study, task_id: str) -> str | None:
    """The task's intent, found by title. Never mints one.

    `find_intent` and not `mint_intent`: asking what has already been done must
    not create anything, or `status` on a fresh checkout would quietly file an
    issue per task.
    """
    from duva_bench.exec.trial import intent_title

    try:
        issue = client.find_intent(
            study.adp.owner, study.adp.repo, title=intent_title(study, task_id)
        )
    except AdpError as error:  # a read failure is not evidence of absence
        logger.warning("could not look up the intent for task %s: %s", task_id, error)
        return None
    return issue.intent_id if issue else None


def run_study(
    study: Study,
    *,
    state: StateDir,
    client: AdpClient | None = None,
    executor: TrialExecutor | None = None,
    concurrency: int | None = None,
    study_dir: Path | None = None,
    limiter: ProviderLimiter | None = None,
) -> StudyOutcome:
    """Run every trial the study still needs."""
    from duva_bench.env import adp_credentials

    state.ensure()
    owned_client = client is None
    client = client or adp_credentials().client()
    limiter = limiter or ProviderLimiter(limits=dict(study.provider_rate_limits))
    ledger = CostLedger(cap_usd=study.budget_usd_cap)
    workers = max(1, concurrency or study.concurrency)

    outcome = StudyOutcome()
    try:
        planned = plan_trials(study)
        outcome.planned = len(planned)

        # Intents first, serially. Minting is a write, and doing it inside the
        # worker pool would race two threads into filing two issues for one task
        # — which ADP would honour, leaving the task's runs split across two
        # intents that can never be compared.
        for task in study.tasks:
            ensure_intent(client, study, task.id, state)

        done = completed_refs(state) | adp_completed_refs(client, study, state)
        pending = [trial for trial in planned if trial.external_ref(study) not in done]
        outcome.skipped = len(planned) - len(pending)

        _seed_ledger(client, study, state, ledger, done)

        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="duva-trial") as pool:
            futures: dict[Future[TrialRecord], Trial] = {}
            for trial in pending:
                try:
                    # Before the trial, not after: a cap checked afterwards is a
                    # cap the study exceeds by one trial.
                    ledger.check()
                except BudgetExceeded as stop:
                    outcome.budget_stopped = str(stop)
                    logger.warning("%s", stop)
                    break

                futures[
                    pool.submit(
                        _run_one,
                        study,
                        trial,
                        state=state,
                        client=client,
                        executor=executor,
                        study_dir=study_dir,
                        limiter=limiter,
                    )
                ] = trial

                # Drain eagerly at the concurrency limit so the ledger has
                # something to say before the next submission. Submitting the
                # whole list first would make the cap advisory.
                if len(futures) >= workers:
                    _drain(futures, study, state, client, ledger, outcome, wait_for_all=False)

            _drain(futures, study, state, client, ledger, outcome, wait_for_all=True)
    finally:
        outcome.ledger = ledger.summary()
        if owned_client:
            client.close()

    return outcome


def _run_one(
    study: Study,
    trial: Trial,
    *,
    state: StateDir,
    client: AdpClient,
    executor: TrialExecutor | None,
    study_dir: Path | None,
    limiter: ProviderLimiter,
) -> TrialRecord:
    limiter.acquire(study.arm(trial.arm_id).model.provider)
    return run_trial(
        study,
        trial,
        state=state,
        client=client,
        executor=executor,
        study_dir=study_dir,
    )


def _drain(
    futures: dict[Future[TrialRecord], Trial],
    study: Study,
    state: StateDir,
    client: AdpClient,
    ledger: CostLedger,
    outcome: StudyOutcome,
    *,
    wait_for_all: bool,
) -> None:
    """Collect finished trials, record their spend, and log their progress."""
    finished = [future for future in futures if wait_for_all or future.done()]
    if not wait_for_all and not finished:
        # Nothing is done yet and the pool is full: wait for the first one
        # rather than spinning.
        finished = [next(iter(futures))]

    for future in finished:
        trial = futures.pop(future)
        external_ref = trial.external_ref(study)
        try:
            record = future.result()
        # One trial failing must not end the study; the failure is recorded
        # and the remaining trials still run.
        except Exception as failure:
            logger.exception("trial %s failed to run", external_ref)
            outcome.failures[external_ref] = f"{type(failure).__name__}: {failure}"
            state.append_progress(
                {
                    "external_ref": external_ref,
                    "verdict": "ERROR",
                    "error": str(failure),
                    "task": trial.task_id,
                    "arm": trial.arm_id,
                    "repetition": trial.repetition,
                }
            )
            continue

        ledger.record(_trial_cost(client, study, record))
        (outcome.completed if record.ok else outcome.errors).append(record)
        state.append_progress(
            {
                "external_ref": record.external_ref,
                "verdict": record.verdict,
                "run_id": record.run_id,
                "task": record.task_id,
                "arm": record.arm_id,
                "repetition": record.repetition,
                "events": record.events_recorded,
            }
        )


def _trial_cost(client: AdpClient, study: Study, record: TrialRecord) -> int | None:
    """What ADP says this run cost, or None when it says nothing.

    None, not zero: see :class:`~duva_bench.exec.ledger.CostLedger`.
    """
    if record.run_id is None:
        return None
    try:
        stats = client.run_stats(study.adp.owner, study.adp.repo, record.run_id)
    except AdpError as error:
        logger.warning("could not read stats for %s: %s", record.run_id, error)
        return None
    return stats.cost_micro_usd or None


def study_status(
    study: Study,
    *,
    state: StateDir,
    client: AdpClient | None = None,
) -> dict[str, Any]:
    """How far a study has got, without running anything.

    Answers from the local log alone when no client is supplied — the common
    case, and the one that has to work on a machine with no credentials.
    """
    planned = plan_trials(study)
    entries = state.progress_entries()
    by_ref = {str(entry.get("external_ref")): entry for entry in entries}

    verified = [ref for ref, entry in by_ref.items() if entry.get("verdict") == "VERIFIED"]
    errored = [ref for ref, entry in by_ref.items() if entry.get("verdict") == "ERROR"]

    remote: set[str] = set()
    if client is not None:
        remote = adp_completed_refs(client, study, state)

    done = set(verified) | remote
    # Intersected with the plan, not counted raw. ADP holds every run ever
    # closed against this study's intents, including repetitions beyond the
    # study's own and one-off `duva-bench trial` invocations — so the raw count
    # produced `planned: 8, verified: 4, remaining: 7`, which is not a state any
    # study can be in and tells a reader nothing except that something is wrong.
    planned_refs = {trial.external_ref(study) for trial in planned}
    done_in_plan = done & planned_refs
    return {
        "study": study.title,
        "study_digest": study.study_digest,
        "planned": len(planned),
        "verified": len(done_in_plan),
        "errors": len(errored),
        "remaining": [
            trial.external_ref(study)
            for trial in planned
            if trial.external_ref(study) not in done_in_plan
        ],
        "adp_consulted": client is not None,
    }


def _seed_ledger(
    client: AdpClient, study: Study, state: StateDir, ledger: CostLedger, done: set[str]
) -> None:
    """Charge already-completed trials against the cap before resuming.

    A resume that started from zero would let a study spend its cap once per
    interruption, which is the one way a cap can be worse than no cap: it would
    read as enforced.
    """
    known = state.known_intents()
    for task in study.tasks:
        intent_id = known.get(task.id)
        if intent_id is None:
            continue
        try:
            runs = client.list_runs(study.adp.owner, study.adp.repo, intent_id=intent_id)
        except AdpError as error:
            logger.warning("could not seed the ledger for task %s: %s", task.id, error)
            continue
        for run in runs:
            if run.external_ref in done:
                try:
                    stats = client.run_stats(study.adp.owner, study.adp.repo, run.id)
                except AdpError:
                    ledger.record(None)
                    continue
                ledger.record(stats.cost_micro_usd or None)
