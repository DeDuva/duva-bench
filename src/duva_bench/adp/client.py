"""Hand-written wrapper over the generated ADP client.

Only the surfaces execution-plan §2 lists are exposed, plus the one compat-plane
call that mints an intent. Keeping the wrapper narrow is deliberate: it is the
seam that absorbs an ADP rewrite, and a wrapper that re-exports everything
absorbs nothing.

Paths, methods and required fields are not written here — they come from
:mod:`duva_bench.adp._generated`, which comes from ADP's own document. What is
written here is transport policy: which identity signs which call, what an error
means, and which response shapes this client depends on.

**Two identities, not one.** A score is independent evidence only when the
identity that reported it is not the identity that did the work — ADP reports
this as ``separately_authorized``. Passing the same token for both collapses
that distinction into a self-report that still looks like a score, so the
constructor refuses it, and :func:`duva_bench.adp.preflight.preflight` asserts
the same thing again against a live server before any spend.
"""

from __future__ import annotations

from types import TracebackType
from typing import Any, Self

import httpx

from duva_bench.adp._generated import Operation, operation
from duva_bench.adp.models import (
    AppendReceipt,
    EvalRecord,
    GitObject,
    Issue,
    Run,
    RunComparison,
    RunStats,
    Session,
    Trajectory,
    VerifyResult,
)
from duva_bench.adp.version import VERSION_HEADER, assert_api_version

DEFAULT_TIMEOUT = 30.0

# ADP caps both list surfaces at 200 rows (execution-plan §3.6). Named here so
# that a caller reading a truncated page has something to compare against
# instead of quietly analyzing whatever fitted.
LIST_CAP = 200


class AdpError(RuntimeError):
    """An ADP call that did not succeed."""

    def __init__(self, message: str, *, status: int, body: Any = None) -> None:
        super().__init__(message)
        self.status = status
        self.body = body


class AppendRejected(AdpError):
    """A 409 from the events endpoint.

    Two different conditions share the status. ``expected_next_seq`` is set when
    the batch skipped the emitter's numbering, and it is the resume point a
    spool replays from; it is None when the session was closed, which no amount
    of replaying fixes.
    """

    def __init__(self, message: str, *, status: int, body: Any = None) -> None:
        super().__init__(message, status=status, body=body)
        self.expected_next_seq: int | None = None
        if isinstance(body, dict):
            value = body.get("expected_next_seq")
            self.expected_next_seq = value if isinstance(value, int) else None


class AdpClient:
    """Client for ADP's native plane, plus the one compat call that mints intents."""

    def __init__(
        self,
        base_url: str,
        *,
        runner_token: str,
        grader_token: str,
        timeout: float = DEFAULT_TIMEOUT,
        transport: httpx.BaseTransport | None = None,
        allow_compatible_version: bool = False,
    ) -> None:
        if not runner_token or not grader_token:
            raise ValueError("both a runner token and a grader token are required")
        if runner_token == grader_token:
            raise ValueError(
                "the runner and grader tokens are the same principal, so every score would "
                "be a self-report and separately_authorized would be false. Issue a second "
                "token before recording anything."
            )

        self.base_url = base_url.rstrip("/")
        self._runner_token = runner_token
        self._grader_token = grader_token
        self._allow_compatible_version = allow_compatible_version
        self._http = httpx.Client(timeout=timeout, transport=transport)

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    # --- contract pinning -----------------------------------------------------

    def assert_contract(self) -> str:
        """Check the served contract before anything else happens.

        Deliberately tolerant of the response body: ADP sets the header on 401s
        and 404s too, so this works before a token has been proven good, which
        is the case worth catching — a client pointed at the wrong instance.
        """
        response = self._http.get(f"{self.base_url}/api/adp/repos/_/_/runs")
        served: str | None = response.headers.get(VERSION_HEADER)
        assert_api_version(served, allow_compatible=self._allow_compatible_version)
        assert served is not None  # assert_api_version rejects None
        return served

    # --- intents (compat plane, §3.3) -----------------------------------------

    def mint_intent(self, owner: str, repo: str, *, title: str, body: str = "") -> Issue:
        """File an issue, and read the intent ADP minted as a side effect.

        The native plane cannot open a run without an ``intent_id`` and nothing
        in ``/api/adp`` creates one. This is not a shortcut around the native
        plane; it is the only door. Nothing on the recording hot path touches
        the compat plane.
        """
        payload = self._call(
            operation("compat_post_repos_by_owner_by_repo_issues"),
            {"owner": owner, "repo": repo},
            body={"title": title, "body": body},
        )
        return Issue.model_validate(payload)

    def find_intent(self, owner: str, repo: str, *, title: str) -> Issue | None:
        """The existing issue with this exact title, if there is one.

        Intent minting has to be idempotent per task per study: rerunning a
        study must rejoin its intents rather than mint a second set, which would
        split one task's runs across two ``/runs/compare`` pages that can never
        be compared.
        """
        payload = self._call(
            operation("compat_get_repos_by_owner_by_repo_issues"),
            {"owner": owner, "repo": repo},
        )
        rows = (
            payload.get("body") if isinstance(payload.get("body"), list) else payload.get("issues")
        )
        if not isinstance(rows, list):
            return None
        for row in rows:
            if isinstance(row, dict) and row.get("title") == title and row.get("intent_id"):
                return Issue.model_validate(row)
        return None

    # --- git data (compat plane) ----------------------------------------------
    #
    # Four writes, used for exactly one thing: giving a run a commit to close
    # against. ADP will not close a run against a sha it cannot resolve in the
    # repository, and a Harbor trial produces container artifacts rather than a
    # commit — so duva-bench writes the artifacts in and closes against that.
    # `adp/artifacts.py` is the only caller; nothing reads git back out.

    def create_blob(self, owner: str, repo: str, *, content: str, encoding: str = "utf-8") -> str:
        """POST .../git/blobs — returns the blob sha."""
        return (
            GitObject.model_validate(
                self._call(
                    operation("compat_post_repos_by_owner_by_repo_git_blobs"),
                    {"owner": owner, "repo": repo},
                    body={"content": content, "encoding": encoding},
                )
            )
        ).sha

    def create_tree(self, owner: str, repo: str, *, entries: list[dict[str, Any]]) -> str:
        """POST .../git/trees — returns the tree sha."""
        return (
            GitObject.model_validate(
                self._call(
                    operation("compat_post_repos_by_owner_by_repo_git_trees"),
                    {"owner": owner, "repo": repo},
                    body={"tree": entries},
                )
            )
        ).sha

    def create_commit(
        self, owner: str, repo: str, *, message: str, tree: str, parents: list[str] | None = None
    ) -> str:
        """POST .../git/commits — returns the commit sha."""
        return (
            GitObject.model_validate(
                self._call(
                    operation("compat_post_repos_by_owner_by_repo_git_commits"),
                    {"owner": owner, "repo": repo},
                    body={"message": message, "tree": tree, "parents": parents or []},
                )
            )
        ).sha

    def create_ref(self, owner: str, repo: str, *, ref: str, sha: str) -> None:
        """POST .../git/refs — makes a commit reachable, so it survives gc.

        A commit with no ref is dangling. ADP resolves it today and a future
        `git gc` need not, and a run whose attested subject has been collected
        is a run whose evidence evaporated.
        """
        self._call(
            operation("compat_post_repos_by_owner_by_repo_git_refs"),
            {"owner": owner, "repo": repo},
            body={"ref": ref, "sha": sha},
        )

    # --- runs and sessions ----------------------------------------------------

    def create_run(
        self,
        owner: str,
        repo: str,
        *,
        intent_id: str,
        orchestrator: str,
        external_ref: str | None = None,
        labels: dict[str, str] | None = None,
    ) -> Run:
        """POST .../runs — 201 for a new run, 200 for rejoining an existing one.

        ADP returns the existing run when ``external_ref`` names one that is
        still open, which is what makes M5's resume idempotent rather than
        merely tolerable.
        """
        body: dict[str, Any] = {"intent_id": intent_id, "orchestrator": orchestrator}
        if external_ref is not None:
            body["external_ref"] = external_ref
        if labels:
            body["labels"] = labels
        return Run.model_validate(
            self._call(
                operation("post_repos_by_owner_by_repo_runs"),
                {"owner": owner, "repo": repo},
                body=body,
            )
        )

    def create_session(self, owner: str, repo: str, *, harness: str, **fields: Any) -> Session:
        """POST .../sessions"""
        return Session.model_validate(
            self._call(
                operation("post_repos_by_owner_by_repo_sessions"),
                {"owner": owner, "repo": repo},
                body={"harness": harness, **fields},
            )
        )

    def append_events(
        self,
        owner: str,
        repo: str,
        session_id: str,
        events: list[dict[str, Any]],
        *,
        producer_id: str | None = None,
    ) -> AppendReceipt:
        """POST .../sessions/{id}/events — batched, carrying ``producer_seq``.

        Raises :class:`AppendRejected` on a 409, carrying ``expected_next_seq``
        when ADP supplied one, so the spool replays from there rather than
        guessing.
        """
        # ADP's spec marks `payload` optional — only `kind` is required — but
        # the column behind it is NOT NULL, so an event without one is a 500
        # rather than a 201 or a 422. Defaulting it here is a workaround for a
        # server bug (execution-plan §3.1), not a modelling choice: a recorder
        # must not be able to take down its own run by emitting an event the
        # contract says is legal.
        normalized = [event if "payload" in event else {**event, "payload": {}} for event in events]

        body: dict[str, Any] = {"events": normalized}
        if producer_id is not None:
            body["producer_id"] = producer_id

        return AppendReceipt.model_validate(
            self._call(
                operation("post_repos_by_owner_by_repo_sessions_by_id_events"),
                {"owner": owner, "repo": repo, "id": session_id},
                body=body,
            )
        )

    def close_run(self, owner: str, repo: str, run_id: str, *, final_git_sha: str) -> Run:
        """POST .../runs/{runId}/close"""
        return Run.model_validate(
            self._call(
                operation("post_repos_by_owner_by_repo_runs_by_run_id_close"),
                {"owner": owner, "repo": repo, "runId": run_id},
                body={"final_git_sha": final_git_sha},
            )
        )

    def abandon_run(self, owner: str, repo: str, run_id: str, *, reason: str) -> Run:
        """POST .../runs/{runId}/abandon — for a trial that produced no commit.

        The trajectory is kept. A study that deletes its failures reports a
        different experiment than the one it ran.
        """
        return Run.model_validate(
            self._call(
                operation("post_repos_by_owner_by_repo_runs_by_run_id_abandon"),
                {"owner": owner, "repo": repo, "runId": run_id},
                body={"reason": reason},
            )
        )

    # --- scoring, under the grader identity -----------------------------------

    def report_eval(self, owner: str, repo: str, run_id: str, **fields: Any) -> EvalRecord:
        """POST .../runs/{runId}/evals — sent with the *grader* token."""
        return EvalRecord.model_validate(
            self._call(
                operation("post_repos_by_owner_by_repo_runs_by_run_id_evals"),
                {"owner": owner, "repo": repo, "runId": run_id},
                body=fields,
                token=self._grader_token,
            )
        )

    # --- reads ----------------------------------------------------------------

    def verify_run(self, owner: str, repo: str, run_id: str) -> VerifyResult:
        """GET .../runs/{runId}/verify — the evidence-gating primitive."""
        return VerifyResult.model_validate(
            self._call(
                operation("get_repos_by_owner_by_repo_runs_by_run_id_verify"),
                {"owner": owner, "repo": repo, "runId": run_id},
            )
        )

    def compare_runs(
        self,
        owner: str,
        repo: str,
        *,
        intent_id: str,
        eval_name: str | None = None,
        limit: int = LIST_CAP,
    ) -> tuple[RunComparison, ...]:
        """GET .../runs/compare?intent_id= — one row per run against one intent.

        Always per intent. ADP caps this at 200 rows (§3.6), so "every run in
        the experiment" is not a question this endpoint can answer; asking it
        per task is what keeps the answer complete.
        """
        query = {"intent_id": intent_id, "limit": str(min(limit, LIST_CAP))}
        if eval_name is not None:
            query["eval"] = eval_name
        payload = self._call(
            operation("get_repos_by_owner_by_repo_runs_compare"),
            {"owner": owner, "repo": repo},
            query=query,
        )
        rows = payload.get("runs") or []
        return tuple(RunComparison.model_validate(row) for row in rows)

    def list_runs(
        self,
        owner: str,
        repo: str,
        *,
        intent_id: str | None = None,
        status: str | None = None,
        limit: int = LIST_CAP,
    ) -> tuple[Run, ...]:
        """GET .../runs — newest first, capped at 200."""
        query: dict[str, str] = {"limit": str(min(limit, LIST_CAP))}
        if intent_id is not None:
            query["intent_id"] = intent_id
        if status is not None:
            query["status"] = status
        payload = self._call(
            operation("get_repos_by_owner_by_repo_runs"),
            {"owner": owner, "repo": repo},
            query=query,
        )
        return tuple(Run.model_validate(row) for row in payload.get("runs") or [])

    def run_stats(self, owner: str, repo: str, run_id: str) -> RunStats:
        """GET .../runs/{runId}/stats"""
        return RunStats.model_validate(
            self._call(
                operation("get_repos_by_owner_by_repo_runs_by_run_id_stats"),
                {"owner": owner, "repo": repo, "runId": run_id},
            )
        )

    def trajectory(
        self,
        owner: str,
        repo: str,
        run_id: str,
        *,
        kinds: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> Trajectory:
        """GET .../runs/{runId}/trajectory — paged, merged across sessions."""
        query = {"limit": str(limit), "offset": str(offset)}
        if kinds is not None:
            query["kinds"] = kinds
        return Trajectory.model_validate(
            self._call(
                operation("get_repos_by_owner_by_repo_runs_by_run_id_trajectory"),
                {"owner": owner, "repo": repo, "runId": run_id},
                query=query,
            )
        )

    def full_trajectory(
        self, owner: str, repo: str, run_id: str, *, kinds: str | None = None, page: int = 200
    ) -> Trajectory:
        """Every event of a run, paged until ADP's ``total`` is satisfied.

        Process metrics are rates over a whole trajectory. Computing one over
        whatever fitted in the first page would produce a number that looks like
        a measurement and is a function of the page size.
        """
        first = self.trajectory(owner, repo, run_id, kinds=kinds, limit=page, offset=0)
        events = list(first.events)
        while len(events) < first.total:
            batch = self.trajectory(
                owner, repo, run_id, kinds=kinds, limit=page, offset=len(events)
            )
            if not batch.events:
                break
            events.extend(batch.events)
        return Trajectory(run_id=run_id, total=first.total, events=tuple(events))

    # --- transport ------------------------------------------------------------

    def _call(
        self,
        op: Operation,
        params: dict[str, str],
        *,
        body: dict[str, Any] | None = None,
        query: dict[str, str] | None = None,
        token: str | None = None,
    ) -> dict[str, Any]:
        if body is not None:
            missing = [name for name in op.required_fields if name not in body]
            if missing:
                # The contract says these are required. Checking here turns a
                # 422 halfway through a recording into a programming error at
                # the call site.
                raise ValueError(f"{op.key} requires {missing}")

        response = self._http.request(
            op.method,
            op.url(self.base_url, **params),
            json=body,
            params=query,
            headers={"Authorization": f"Bearer {token or self._runner_token}"},
        )

        payload: Any = None
        if response.content:
            try:
                payload = response.json()
            except ValueError:
                payload = response.text

        if response.is_success:
            return payload if isinstance(payload, dict) else {"body": payload}

        message = f"{op.method} {op.path} -> {response.status_code}"
        if response.status_code == 409 and op.key.endswith("events"):
            raise AppendRejected(message, status=response.status_code, body=payload)
        raise AdpError(message, status=response.status_code, body=payload)
