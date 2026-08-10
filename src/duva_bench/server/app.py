"""The JSON API (M7).

The web UX is a client of this API and never a second path into the system: the
routes below call the same functions the CLI calls — ``parse_study``,
``run_study``, ``build_report`` — and nothing here reimplements any of them. A
number the browser shows is a number ``duva-bench report`` would print.

Two boundaries this module is responsible for.

**Tokens stay here.** ADP credentials are read from the server's environment and
never leave it. The browser gets JSON that was fetched on its behalf; it does
not get a token, and there is no route that would hand it one.

**The ADP read-proxy is six literal paths.** Not a wildcard, not a prefix match:
an explicit table, mirroring squad-lab's stance. A wildcard proxy in front of a
system that holds a write token is a write endpoint that has not been noticed
yet — and the six paths below are read-only by construction, because that is the
whole set the UX needs.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from duva_bench.adp.client import AdpClient, AdpError
from duva_bench.env import MissingCredentials, adp_credentials
from duva_bench.exec.scheduler import plan_trials, run_study, study_status
from duva_bench.report.build import build_report, write_report
from duva_bench.server.frames import FrameCache, resume_point
from duva_bench.state import DEFAULT_ROOT, StateDir
from duva_bench.study.load import StudyFileError, parse_study
from duva_bench.study.models import Study

logger = logging.getLogger(__name__)

# Every ADP path the browser may read, spelled out. Adding one is a decision
# somebody makes on purpose; there is no pattern here that could grow a write
# endpoint by accident.
ADP_READ_PATHS: dict[str, str] = {
    "runs": "/api/adp/repos/{owner}/{repo}/runs",
    "runs_compare": "/api/adp/repos/{owner}/{repo}/runs/compare",
    "run": "/api/adp/repos/{owner}/{repo}/runs/{run_id}",
    "run_verify": "/api/adp/repos/{owner}/{repo}/runs/{run_id}/verify",
    "run_stats": "/api/adp/repos/{owner}/{repo}/runs/{run_id}/stats",
    "run_trajectory": "/api/adp/repos/{owner}/{repo}/runs/{run_id}/trajectory",
}

# How often the SSE stream looks for new lines. Frames are pushed as they land;
# this is the poll interval of the tail, not a batching delay.
POLL_SECONDS = 0.25
# A comment frame every so often, so a proxy between server and browser does not
# decide an idle stream is a dead one.
HEARTBEAT_SECONDS = 15.0


class StudyStore:
    """Uploaded studies, on disk, keyed by digest.

    A study is data, so "upload" means "write the bytes down and remember the
    digest of what was written". Nothing is normalized on the way in: the file
    a user uploaded is the file this serves back, because a server that
    reformats a study before digesting it is a server that changes what the
    digest attests.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, digest: str) -> Path:
        return self.root / f"{digest.removeprefix('sha256:')}.yaml"

    def save(self, source: str) -> Study:
        study = parse_study(source, origin="<upload>")
        self.path(study.study_digest).write_text(source, encoding="utf-8")
        return study

    def load(self, digest: str) -> Study:
        path = self.path(digest)
        if not path.exists():
            raise KeyError(digest)
        return parse_study(path.read_text(encoding="utf-8"), origin=str(path))

    def all(self) -> list[Study]:
        studies: list[Study] = []
        for path in sorted(self.root.glob("*.yaml")):
            try:
                studies.append(parse_study(path.read_text(encoding="utf-8"), origin=str(path)))
            except StudyFileError:
                logger.warning("ignoring unreadable study file %s", path)
        return studies


def create_app(
    *,
    state_root: Path | None = None,
    client_factory: Callable[[], AdpClient] | None = None,
    runner: Callable[[Study, StateDir], Any] | None = None,
) -> FastAPI:
    """Build the app.

    ``client_factory`` and ``runner`` are injected so the suite can drive every
    route against an in-memory ADP without a network or a container. The
    defaults are the real ones.
    """
    root = Path(state_root) if state_root is not None else DEFAULT_ROOT
    store = StudyStore(root / "studies")
    frames = FrameCache()
    running: dict[str, asyncio.Task[Any]] = {}

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        # A study left running when the server stops is a study nobody is
        # recording the end of. Cancelling here means the next start resumes it
        # from progress.jsonl rather than racing a zombie.
        for task in running.values():
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    app = FastAPI(
        title="duva-bench",
        summary="Define, execute and analyze controlled experiments over coding agents.",
        version="0",
        lifespan=lifespan,
    )

    def state_for(study: Study) -> StateDir:
        return StateDir.for_study(study, root).ensure()

    def study_or_404(digest: str) -> Study:
        try:
            return store.load(digest)
        except KeyError:
            raise HTTPException(404, f"no study with digest {digest}") from None

    def adp() -> AdpClient:
        if client_factory is not None:
            return client_factory()
        try:
            return adp_credentials().client()
        except MissingCredentials as missing:
            # 503, not 500: the server is configured wrong, and saying which
            # variable is missing costs nothing and saves an afternoon.
            raise HTTPException(503, str(missing)) from None

    # --- studies -------------------------------------------------------------

    @app.post("/api/studies")
    def upload_study(source: str = Body(..., media_type="text/plain")) -> JSONResponse:
        """Validate and store a study. The digest is the id."""
        try:
            study = store.save(source)
        except StudyFileError as invalid:
            # 422 with the validator's own message: a study file is a user's
            # document, and "invalid" without a line is not an answer.
            raise HTTPException(422, str(invalid)) from None
        return JSONResponse(_study_summary(study), status_code=201)

    @app.get("/api/studies")
    def list_studies() -> list[dict[str, Any]]:
        return [_study_summary(study) for study in store.all()]

    @app.get("/api/studies/{digest}")
    def get_study(digest: str) -> dict[str, Any]:
        study = study_or_404(digest)
        return {
            **_study_summary(study),
            "document": study.model_dump(mode="json"),
            "source": store.path(study.study_digest).read_text(encoding="utf-8"),
            "trials": [
                {
                    "task": trial.task_id,
                    "arm": trial.arm_id,
                    "repetition": trial.repetition,
                    "external_ref": trial.external_ref(study),
                }
                for trial in plan_trials(study)
            ],
        }

    @app.post("/api/studies/validate")
    def validate_study(source: str = Body(..., media_type="text/plain")) -> dict[str, Any]:
        """Validate without storing — what the editor calls on every keystroke."""
        try:
            study = parse_study(source, origin="<editor>")
        except StudyFileError as invalid:
            return {"ok": False, "error": str(invalid)}
        return {"ok": True, **_study_summary(study)}

    # --- execution -----------------------------------------------------------

    @app.post("/api/studies/{digest}/run")
    async def start_run(digest: str) -> dict[str, Any]:
        study = study_or_404(digest)
        if digest in running and not running[digest].done():
            # Not an error: a second browser pressing run is a second browser
            # pressing run, and the study is already going.
            return {"status": "already running", "digest": digest}

        state = state_for(study)

        def execute() -> Any:
            if runner is not None:
                return runner(study, state)
            with adp() as client:
                return run_study(study, state=state, client=client)

        running[digest] = asyncio.create_task(asyncio.to_thread(execute))
        return {"status": "started", "digest": digest, "planned": study.trial_count}

    @app.get("/api/studies/{digest}/status")
    def get_status(digest: str) -> dict[str, Any]:
        study = study_or_404(digest)
        task = running.get(digest)
        return {
            **study_status(study, state=state_for(study)),
            "running": bool(task and not task.done()),
        }

    @app.get("/api/studies/{digest}/stream")
    async def stream(request: Request, digest: str) -> StreamingResponse:
        """Server-sent events over ``progress.jsonl``, resumable by offset.

        ``Last-Event-ID`` is honoured, so a browser that lost its connection
        picks up where it left off instead of missing the trials that finished
        while it was away.
        """
        study = study_or_404(digest)
        state = state_for(study)
        after = resume_point(request.headers.get("last-event-id"))

        async def events() -> AsyncIterator[str]:
            cursor = after
            idle = 0.0
            while True:
                if await request.is_disconnected():
                    return
                for frame in frames.frames(state.progress, after=cursor):
                    cursor = frame.id
                    idle = 0.0
                    yield frame.as_sse()

                task = running.get(digest)
                if (task is None or task.done()) and not frames.frames(
                    state.progress, after=cursor
                ):
                    status = study_status(study, state=state)
                    if not status["remaining"]:
                        yield f"id: {cursor}\nevent: done\ndata: {json.dumps(status)}\n\n"
                        return

                await asyncio.sleep(POLL_SECONDS)
                idle += POLL_SECONDS
                if idle >= HEARTBEAT_SECONDS:
                    idle = 0.0
                    # A comment frame. Proxies drop streams that go quiet, and a
                    # dropped stream is a grid that silently stops updating.
                    yield ": keep-alive\n\n"

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # --- results -------------------------------------------------------------

    @app.get("/api/studies/{digest}/report")
    def get_report(digest: str, write: bool = Query(False)) -> dict[str, Any]:
        study = study_or_404(digest)
        state = state_for(study)
        with adp() as client:
            report = build_report(study, state=state, client=client)
        if write:
            write_report(report, root / "reports" / study.slug)
        return report.as_dict()

    # --- the ADP read-proxy --------------------------------------------------

    @app.get("/api/adp/{name}")
    def adp_read(
        name: str,
        owner: str = Query(...),
        repo: str = Query(...),
        run_id: str | None = Query(None),
        intent_id: str | None = Query(None),
        limit: int | None = Query(None),
    ) -> Any:
        """Read one of six ADP paths on the browser's behalf.

        The browser never holds a token, and this is not a general proxy: the
        path comes from :data:`ADP_READ_PATHS` by name, so a caller cannot ask
        for a path this table does not contain.
        """
        template = ADP_READ_PATHS.get(name)
        if template is None:
            raise HTTPException(
                404,
                f"{name!r} is not one of the readable ADP paths: {sorted(ADP_READ_PATHS)}",
            )
        if "{run_id}" in template and not run_id:
            raise HTTPException(422, f"{name} needs a run_id")

        query: dict[str, str] = {}
        if intent_id:
            query["intent_id"] = intent_id
        if limit:
            query["limit"] = str(limit)

        with adp() as client:
            url = template.format(owner=owner, repo=repo, run_id=run_id or "")
            try:
                response = client._http.get(  # the read-proxy is this seam
                    f"{client.base_url}{url}",
                    params=query,
                    headers={"Authorization": f"Bearer {client._runner_token}"},
                )
            except OSError as failure:
                raise HTTPException(502, f"ADP is unreachable: {failure}") from None
        if response.status_code >= 400:
            raise HTTPException(response.status_code, response.text[:2000])
        return response.json()

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        """Whether this server can do its job, and what it cannot do without."""
        configured = True
        detail: str | None = None
        try:
            adp_credentials()
        except MissingCredentials as missing:
            configured = False
            detail = str(missing)
        return {"ok": True, "adp_configured": configured, "detail": detail}

    return app


def _study_summary(study: Study) -> dict[str, Any]:
    return {
        "digest": study.study_digest,
        "slug": study.slug,
        "title": study.title,
        "tasks": [task.id for task in study.tasks],
        "arms": [arm.id for arm in study.arms],
        "repetitions": study.repetitions,
        "trials": study.trial_count,
        "budget_usd_cap": str(study.budget_usd_cap),
        "pre_registration": {
            "digest": study.pre_registration.pre_registration_digest,
            "original_digest": study.pre_registration.original_digest,
            "amended": study.pre_registration.amended,
            "primary_metric": study.pre_registration.primary_metric,
            "control_arm": study.pre_registration.control_arm,
        },
    }


__all__ = ["ADP_READ_PATHS", "AdpError", "StudyStore", "create_app"]
