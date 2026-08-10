"""An in-memory ADP, served over ``httpx.MockTransport``.

Not a mock in the "assert it was called" sense. It implements the parts of ADP's
contract this project depends on — intent minting, run rejoin by
``external_ref``, emitter contiguity with ``expected_next_seq``,
``client_event_id`` dedupe, reporter-identity separation, and verification —
because those are behaviours, and a test double that returns canned dictionaries
proves the caller compiles rather than that it is right.

It deliberately reproduces two things that are easy to get wrong and expensive
to get wrong late:

* the **naming split** — run rows, events and evals in ``snake_case``,
  ``/runs/compare`` and ``/runs/{id}/stats`` in ``camelCase``
* the **payload NOT NULL bug** (execution-plan §3.1): an event without a
  ``payload`` is answered with a 500, exactly as the real server does, so the
  client's workaround is exercised rather than assumed

What it is not is a substitute for ``tests/contract/``. This file encodes what
we *believe* ADP does; only the live suite can tell us whether that is still
true.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import uuid
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

from duva_bench.adp._generated import SPEC_VERSION
from duva_bench.adp.version import VERSION_HEADER

RUNNER_TOKEN = "runner-token"
GRADER_TOKEN = "grader-token"


@dataclass
class FakeEvent:
    session_id: str
    seq: int
    kind: str
    payload: Any
    type: str | None = None
    status: str | None = None
    model: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost_micro_usd: int | None = None
    duration_ms: int | None = None
    git_sha: str | None = None
    client_event_id: str | None = None
    producer_seq: int | None = None
    producer_id: str | None = None

    def serialize(self) -> dict[str, Any]:
        return {
            "id": f"event-{self.session_id}-{self.seq}",
            "session_id": self.session_id,
            "seq": self.seq,
            "kind": self.kind,
            "type": self.type,
            "payload": self.payload,
            "status": self.status,
            "model": self.model,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "cost_micro_usd": self.cost_micro_usd,
            "duration_ms": self.duration_ms,
            "git_sha": self.git_sha,
            "client_event_id": self.client_event_id,
            "producer_seq": self.producer_seq,
            "producer_id": self.producer_id,
            "occurred_at": "2026-08-07T00:00:00.000Z",
            "hash": f"sha256:{self.seq:064x}",
            "prev_hash": None,
        }


@dataclass
class FakeRun:
    id: str
    intent_id: str
    orchestrator: str
    external_ref: str | None
    labels: dict[str, str]
    opened_by: str
    status: str = "open"
    final_git_sha: str | None = None
    created_at: str = "2026-08-07T00:00:00.000Z"
    closed_at: str | None = None
    # Set by `tamper()`: what a broken hash chain looks like from outside.
    chain_broken_at: int | None = None

    def serialize(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "intent_id": self.intent_id,
            "orchestrator": self.orchestrator,
            "external_ref": self.external_ref,
            "labels": self.labels,
            "status": self.status,
            "final_git_sha": self.final_git_sha,
            "trajectory_digest": f"sha256:{'a' * 64}" if self.status == "closed" else None,
            "envelope": {"payloadType": "application/vnd.in-toto+json"} if self.closed_at else None,
            "created_at": self.created_at,
            "closed_at": self.closed_at,
        }


@dataclass
class FakeEval:
    id: str
    run_id: str
    name: str
    score: float | None
    passed: bool
    spec_digest: str | None
    reporter_principal: str
    separately_authorized: bool
    created_at: str
    summary: str | None = None


@dataclass
class FakeAdp:
    """A tiny ADP. Construct one, hand ``transport`` to :class:`AdpClient`."""

    principals: dict[str, str] = field(
        default_factory=lambda: {RUNNER_TOKEN: "duva-runner", GRADER_TOKEN: "duva-grader"}
    )
    api_version: str = SPEC_VERSION

    intents: dict[str, str] = field(default_factory=dict)  # title -> intent id
    issues: list[dict[str, Any]] = field(default_factory=list)
    runs: dict[str, FakeRun] = field(default_factory=dict)
    sessions: dict[str, str] = field(default_factory=dict)  # session id -> run id
    events: dict[str, list[FakeEvent]] = field(default_factory=dict)  # session id -> events
    seen_client_ids: dict[str, set[str]] = field(default_factory=dict)
    evals: list[FakeEval] = field(default_factory=list)
    # Git data. `commits` is the set of shas this repository can resolve, and
    # `_close` refuses anything outside it — the real server does exactly that,
    # and a double that accepted any 40-hex string is what let a trial runner
    # closing against the all-zero sha stay green through 325 tests while being
    # unable to close a single real run.
    blobs: dict[str, str] = field(default_factory=dict)
    trees: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    commits: dict[str, dict[str, Any]] = field(default_factory=dict)
    refs: dict[str, str] = field(default_factory=dict)

    requests: list[httpx.Request] = field(default_factory=list)
    # Set to a status code to make the next call fail, for retry paths.
    fail_next_append_with: int | None = None
    _counter: itertools.count[int] = field(default_factory=lambda: itertools.count(1))

    # --- helpers for tests ----------------------------------------------------

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def seed_commit(self, message: str = "seeded") -> str:
        """Register a resolvable commit and return its sha.

        For tests about something other than publishing: closing a run needs a
        commit the repository can resolve, so a test that just wants a *closed*
        run needs one commit and no opinion about its contents.
        """
        tree = _sha1_like("tree", message)
        self.trees[tree] = []
        sha = _sha1_like("commit", tree + message)
        self.commits[sha] = {"tree": tree, "message": message}
        return sha

    def tamper(self, run_id: str, *, at_seq: int = 2) -> None:
        """Edit a stored event, the way an attacker or a bug would."""
        self.runs[run_id].chain_broken_at = at_seq

    def run_by_external_ref(self, external_ref: str) -> FakeRun | None:
        for run in self.runs.values():
            if run.external_ref == external_ref:
                return run
        return None

    def events_for_run(self, run_id: str) -> list[FakeEvent]:
        collected: list[FakeEvent] = []
        for session_id, run in self.sessions.items():
            if run == run_id:
                collected.extend(self.events.get(session_id, []))
        return collected

    # --- the transport --------------------------------------------------------

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        principal = self._principal(request)
        path = urlparse(str(request.url)).path
        query = {k: v[0] for k, v in parse_qs(urlparse(str(request.url)).query).items()}
        body = json.loads(request.content) if request.content else {}
        segments = [segment for segment in path.split("/") if segment]

        if principal is None:
            # The version header on a 401 is what makes pinning possible before
            # a token has been proven good.
            return self._json(401, {"message": "Unauthorized"})

        try:
            return self._route(request.method, segments, query, body, principal)
        except _NotFound as missing:
            return self._json(404, {"message": str(missing)})

    def _route(
        self,
        method: str,
        segments: list[str],
        query: dict[str, str],
        body: dict[str, Any],
        principal: str,
    ) -> httpx.Response:
        # /api/v3/repos/{owner}/{repo}/issues
        if segments[:2] == ["api", "v3"] and segments[-1] == "issues":
            if method == "POST":
                return self._create_issue(body)
            return self._json(200, self.issues)

        # /api/v3/repos/{owner}/{repo}/git/{blobs,trees,commits,refs}
        if segments[:2] == ["api", "v3"] and "git" in segments and method == "POST":
            return self._git_write(segments[segments.index("git") + 1], body)

        if segments[:2] != ["api", "adp"]:
            raise _NotFound(f"/{'/'.join(segments)}")

        tail = segments[5:]  # after api/adp/repos/{owner}/{repo}

        if tail[:1] == ["runs"]:
            if len(tail) == 1:
                return (
                    self._create_run(body, principal)
                    if method == "POST"
                    else self._list_runs(query)
                )
            if tail[1] == "compare":
                return self._compare(query)
            run_id = tail[1]
            if run_id not in self.runs:
                raise _NotFound(f"run {run_id}")
            action = tail[2] if len(tail) > 2 else None
            if action is None:
                return self._json(200, self.runs[run_id].serialize())
            if action == "close":
                return self._close(run_id, body)
            if action == "abandon":
                return self._abandon(run_id, body)
            if action == "evals":
                if method == "POST":
                    return self._record_eval(run_id, body, principal)
                return self._json(200, {"evals": [self._eval_json(e) for e in self.evals]})
            if action == "verify":
                return self._verify(run_id)
            if action == "stats":
                return self._stats(run_id)
            if action == "trajectory":
                return self._trajectory(run_id, query)

        if tail[:1] == ["sessions"]:
            if len(tail) == 1:
                return self._create_session(body)
            session_id = tail[1]
            if len(tail) > 2 and tail[2] == "events" and method == "POST":
                return self._append(session_id, body)

        raise _NotFound(f"/{'/'.join(segments)}")

    # --- handlers -------------------------------------------------------------

    def _create_issue(self, body: dict[str, Any]) -> httpx.Response:
        title = str(body.get("title", ""))
        # ADP mints a *new* intent per issue even for a repeated title. That is
        # why duva-bench looks one up before filing.
        intent_id = str(uuid.uuid4())
        self.intents[title] = intent_id
        issue = {
            "id": str(uuid.uuid4()),
            "number": len(self.issues) + 1,
            "title": title,
            "body": body.get("body", ""),
            "state": "open",
            "intent_id": intent_id,
            "html_url": f"/duva/bench/issues/{len(self.issues) + 1}",
        }
        self.issues.append(issue)
        return self._json(201, issue)

    def _create_run(self, body: dict[str, Any], principal: str) -> httpx.Response:
        external_ref = body.get("external_ref")
        if external_ref is not None:
            existing = self.run_by_external_ref(str(external_ref))
            if existing is not None:
                if existing.status != "open":
                    return self._json(409, {"message": "run is closed or abandoned"})
                # 200, not 201: an orchestrator restarting after a crash rejoins
                # rather than forking the trajectory in two.
                return self._json(200, existing.serialize())

        run = FakeRun(
            id=str(uuid.uuid4()),
            intent_id=str(body["intent_id"]),
            orchestrator=str(body["orchestrator"]),
            external_ref=external_ref,
            labels=dict(body.get("labels") or {}),
            opened_by=principal,
        )
        self.runs[run.id] = run
        return self._json(201, run.serialize())

    def _list_runs(self, query: dict[str, str]) -> httpx.Response:
        rows = [
            run.serialize()
            for run in self.runs.values()
            if query.get("intent_id") in (None, run.intent_id)
            and query.get("status") in (None, run.status)
        ]
        return self._json(200, {"runs": rows[: min(int(query.get("limit", 50) or 50), 200)]})

    def _create_session(self, body: dict[str, Any]) -> httpx.Response:
        session_id = str(uuid.uuid4())
        self.sessions[session_id] = str(body.get("run_id", ""))
        self.events[session_id] = []
        self.seen_client_ids[session_id] = set()
        return self._json(
            201,
            {"id": session_id, "harness": body.get("harness"), "run_id": body.get("run_id")},
        )

    def _append(self, session_id: str, body: dict[str, Any]) -> httpx.Response:
        if session_id not in self.events:
            raise _NotFound(f"session {session_id}")
        if self.fail_next_append_with is not None:
            status, self.fail_next_append_with = self.fail_next_append_with, None
            return self._json(status, {"message": "injected failure"})

        incoming = list(body.get("events") or [])
        producer_id = body.get("producer_id")
        stored = self.events[session_id]
        tracked = [event for event in stored if event.producer_seq is not None]
        next_seq = (max((e.producer_seq or 0) for e in tracked) + 1) if tracked else 1

        appended: list[FakeEvent] = []
        duplicates: list[str] = []
        for raw in incoming:
            if "payload" not in raw:
                # The bug the client works around: `payload` is documented
                # optional and NOT NULL in the database.
                return self._json(
                    500,
                    {
                        "message": 'null value in column "payload" of relation '
                        '"session_events" violates not-null constraint'
                    },
                )

            client_event_id = raw.get("client_event_id")
            if client_event_id and client_event_id in self.seen_client_ids[session_id]:
                duplicates.append(str(client_event_id))
                continue

            seq = raw.get("producer_seq")
            if seq is not None:
                if int(seq) != next_seq:
                    # Rejected whole, with the resume point named.
                    return self._json(
                        409,
                        {
                            "message": "non-contiguous producer_seq",
                            "expected_next_seq": next_seq,
                        },
                    )
                next_seq += 1

            event = FakeEvent(
                session_id=session_id,
                seq=len(stored) + len(appended) + 1,
                kind=str(raw.get("kind")),
                payload=raw.get("payload"),
                type=raw.get("type"),
                status=raw.get("status"),
                model=raw.get("model"),
                tokens_in=raw.get("tokens_in"),
                tokens_out=raw.get("tokens_out"),
                cost_micro_usd=raw.get("cost_micro_usd"),
                duration_ms=raw.get("duration_ms"),
                git_sha=raw.get("git_sha"),
                client_event_id=client_event_id,
                producer_seq=seq,
                producer_id=producer_id,
            )
            appended.append(event)
            if client_event_id:
                self.seen_client_ids[session_id].add(str(client_event_id))

        stored.extend(appended)
        accepted = [e.producer_seq for e in stored if e.producer_seq is not None]
        return self._json(
            201,
            {
                "session_id": session_id,
                "appended": len(appended),
                "duplicates": duplicates,
                "count": len(stored),
                "head": f"sha256:{len(stored):064x}",
                # None when nothing carried a producer_seq: untracked, not
                # incomplete.
                "accepted_through": max(accepted) if accepted else None,
                "events": [event.serialize() for event in appended],
            },
        )

    def _git_write(self, kind: str, body: dict[str, Any]) -> httpx.Response:
        """Blobs, trees, commits and refs, addressed the way git addresses them.

        Content-addressed rather than counter-addressed, so that writing the
        same artifact twice yields the same sha and a test can assert on it.
        """
        if kind == "refs":
            ref, sha = str(body["ref"]), str(body["sha"])
            if sha not in self.commits:
                return self._json(422, {"message": f"commit '{sha}' could not be resolved"})
            self.refs[ref] = sha
            return self._json(201, {"ref": ref, "object": {"sha": sha, "type": "commit"}})

        if kind == "blobs":
            content = str(body.get("content", ""))
            sha = _sha1_like("blob", content)
            self.blobs[sha] = content
            return self._json(201, {"sha": sha})

        if kind == "trees":
            entries = list(body.get("tree", []))
            sha = _sha1_like("tree", repr(sorted(str(e) for e in entries)))
            self.trees[sha] = entries
            return self._json(201, {"sha": sha})

        if kind == "commits":
            tree = str(body.get("tree", ""))
            if tree not in self.trees:
                return self._json(422, {"message": f"tree '{tree}' could not be resolved"})
            sha = _sha1_like("commit", tree + str(body.get("message", "")))
            self.commits[sha] = {"tree": tree, "message": body.get("message")}
            return self._json(201, {"sha": sha})

        raise _NotFound(f"git/{kind}")

    def _close(self, run_id: str, body: dict[str, Any]) -> httpx.Response:
        run = self.runs[run_id]
        if run.status == "abandoned":
            return self._json(409, {"message": "cannot close an abandoned run"})
        final = str(body["final_git_sha"])
        # The rule the real server enforces, and the reason this double has it:
        # ADP will not attest a commit it cannot show anyone later.
        if final not in self.commits:
            return self._json(
                422, {"message": f"commit '{final}' could not be resolved in this repository"}
            )
        run.status = "closed"
        run.final_git_sha = str(body["final_git_sha"])
        run.closed_at = "2026-08-07T01:00:00.000Z"
        return self._json(200, run.serialize())

    def _abandon(self, run_id: str, body: dict[str, Any]) -> httpx.Response:
        run = self.runs[run_id]
        if run.status == "closed":
            return self._json(409, {"message": "cannot abandon a closed run"})
        run.status = "abandoned"
        run.closed_at = "2026-08-07T01:00:00.000Z"
        return self._json(200, run.serialize())

    def _record_eval(self, run_id: str, body: dict[str, Any], principal: str) -> httpx.Response:
        run = self.runs[run_id]
        git_sha = body.get("git_sha") or run.final_git_sha
        if not git_sha:
            return self._json(422, {"message": "no final_git_sha and no git_sha supplied"})

        spec_digest = body.get("spec_digest")
        if spec_digest is None and body.get("spec") is not None:
            spec_digest = _digest(body["spec"])

        record = FakeEval(
            id=str(uuid.uuid4()),
            run_id=run_id,
            name=str(body["name"]),
            score=body.get("score"),
            passed=bool(body["passed"]),
            spec_digest=spec_digest,
            reporter_principal=principal,
            # The property the whole design turns on: a score is evidence only
            # when the identity reporting it is not the one that did the work.
            separately_authorized=principal != run.opened_by,
            created_at=f"2026-08-07T02:{next(self._counter):02d}:00.000Z",
            summary=body.get("summary"),
        )
        self.evals.append(record)
        return self._json(201, self._eval_json(record))

    def _verify(self, run_id: str) -> httpx.Response:
        run = self.runs[run_id]
        broken = run.chain_broken_at
        session_ids = [sid for sid, rid in self.sessions.items() if rid == run_id]
        return self._json(
            200,
            {
                "run_id": run_id,
                "ok": broken is None,
                "chains_ok": broken is None,
                "emitters_ok": True,
                "envelope_verified": True if run.closed_at else None,
                "trajectory_digest_matches": True if run.closed_at else None,
                "recomputed_trajectory_digest": f"sha256:{'a' * 64}",
                "attested_trajectory_digest": f"sha256:{'a' * 64}",
                "final_git_sha": run.final_git_sha,
                "attested_subject_sha": run.final_git_sha,
                "sessions": [
                    {
                        "session_id": session_id,
                        "ok": broken is None,
                        "event_count": len(self.events.get(session_id, [])),
                        "head": f"sha256:{len(self.events.get(session_id, [])):064x}",
                        "broke_at_seq": broken,
                        "reason": "hash mismatch" if broken else None,
                        "emitter_tracked": True,
                        "emitter_complete": True,
                        "emitter_first_gap": None,
                    }
                    for session_id in session_ids
                ],
                "evals": [
                    {
                        "id": record.id,
                        "name": record.name,
                        "reporter_principal": record.reporter_principal,
                        "separately_authorized": record.separately_authorized,
                    }
                    for record in self.evals
                    if record.run_id == run_id
                ],
            },
        )

    def _compare(self, query: dict[str, str]) -> httpx.Response:
        intent_id = query.get("intent_id")
        rows: list[dict[str, Any]] = []
        for run in self.runs.values():
            if intent_id is not None and run.intent_id != intent_id:
                continue
            events = self.events_for_run(run.id)
            latest: dict[str, FakeEval] = {}
            for record in self.evals:
                if record.run_id == run.id and query.get("eval", record.name) == record.name:
                    latest[record.name] = record
            ordered = sorted(latest.values(), key=lambda e: e.name)
            rows.append(
                {
                    # camelCase, exactly as ADP serializes this endpoint.
                    "runId": run.id,
                    "externalRef": run.external_ref,
                    "orchestrator": run.orchestrator,
                    "status": run.status,
                    "labels": run.labels,
                    "finalGitSha": run.final_git_sha,
                    "trajectoryDigest": run.serialize()["trajectory_digest"],
                    "eval": _comparison_eval(ordered[-1]) if ordered else None,
                    "evals": [_comparison_eval(record) for record in ordered],
                    "events": len(events),
                    "tokensIn": sum(e.tokens_in or 0 for e in events),
                    "tokensOut": sum(e.tokens_out or 0 for e in events),
                    "costMicroUsd": sum(e.cost_micro_usd or 0 for e in events),
                    "durationMs": sum(e.duration_ms or 0 for e in events),
                    "toolCalls": sum(1 for e in events if e.kind == "tool_call"),
                    "toolFailures": sum(
                        1
                        for e in events
                        if e.kind == "tool_call" and e.status in ("failure", "error", "rejected")
                    ),
                    "createdAt": run.created_at,
                    "closedAt": run.closed_at,
                }
            )
        return self._json(200, {"intent_id": intent_id, "runs": rows[:200]})

    def _stats(self, run_id: str) -> httpx.Response:
        events = self.events_for_run(run_id)
        kinds = sorted({event.kind for event in events})
        return self._json(
            200,
            {
                "runId": run_id,
                "sessions": sum(1 for rid in self.sessions.values() if rid == run_id),
                "events": len(events),
                "byKind": [
                    {
                        "kind": kind,
                        "count": sum(1 for e in events if e.kind == kind),
                        "tokensIn": sum(e.tokens_in or 0 for e in events if e.kind == kind),
                        "tokensOut": sum(e.tokens_out or 0 for e in events if e.kind == kind),
                        "costMicroUsd": sum(
                            e.cost_micro_usd or 0 for e in events if e.kind == kind
                        ),
                        "durationMs": sum(e.duration_ms or 0 for e in events if e.kind == kind),
                        "failures": sum(
                            1 for e in events if e.kind == kind and e.status in ("failure", "error")
                        ),
                    }
                    for kind in kinds
                ],
                "tokensIn": sum(e.tokens_in or 0 for e in events),
                "tokensOut": sum(e.tokens_out or 0 for e in events),
                "costMicroUsd": sum(e.cost_micro_usd or 0 for e in events),
                "durationMs": sum(e.duration_ms or 0 for e in events),
                "tools": [
                    {
                        "name": name,
                        "count": sum(1 for e in events if e.kind == "tool_call" and e.type == name),
                        "failures": sum(
                            1
                            for e in events
                            if e.kind == "tool_call"
                            and e.type == name
                            and e.status in ("failure", "error", "rejected")
                        ),
                    }
                    for name in sorted({e.type or "" for e in events if e.kind == "tool_call"})
                ],
                "models": [],
                "handoffs": [],
                "commits": [e.git_sha for e in events if e.kind == "commit" and e.git_sha],
            },
        )

    def _trajectory(self, run_id: str, query: dict[str, str]) -> httpx.Response:
        events = self.events_for_run(run_id)
        kinds = query.get("kinds")
        if kinds:
            wanted = set(kinds.split(","))
            events = [event for event in events if event.kind in wanted]
        offset = int(query.get("offset", 0) or 0)
        limit = int(query.get("limit", 200) or 200)
        window = events[offset : offset + limit]
        return self._json(
            200,
            {
                "run_id": run_id,
                "total": len(events),
                "events": [event.serialize() for event in window],
            },
        )

    # --- plumbing -------------------------------------------------------------

    def _eval_json(self, record: FakeEval) -> dict[str, Any]:
        return {
            "id": record.id,
            "run_id": record.run_id,
            "name": record.name,
            "git_sha": self.runs[record.run_id].final_git_sha,
            "spec_digest": record.spec_digest,
            "score": record.score,
            "passed": record.passed,
            "reporter_principal": record.reporter_principal,
            "separately_authorized": record.separately_authorized,
            "created_at": record.created_at,
        }

    def _principal(self, request: httpx.Request) -> str | None:
        header = request.headers.get("Authorization", "")
        token = header.removeprefix("Bearer ").strip()
        return self.principals.get(token)

    def _json(self, status: int, payload: Any) -> httpx.Response:
        return httpx.Response(
            status,
            json=payload,
            # Served on every response, including 401s — which is what lets a
            # client pin the contract before it holds a working token.
            headers={VERSION_HEADER: self.api_version},
        )


class _NotFound(Exception):
    pass


def _comparison_eval(record: FakeEval) -> dict[str, Any]:
    return {
        "name": record.name,
        "score": record.score,
        "passed": record.passed,
        "specDigest": record.spec_digest,
        "gateStatus": "success" if record.passed else "failure",
        "createdAt": record.created_at,
    }


def _sha1_like(kind: str, payload: str) -> str:
    """A 40-hex sha for a fake object. Not git\'s algorithm, just its shape."""
    return hashlib.sha1(f"{kind}\0{payload}".encode()).hexdigest()


def _digest(spec: Any) -> str:
    import hashlib

    return hashlib.sha256(
        json.dumps(spec, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
