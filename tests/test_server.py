"""M7: the JSON API.

The point of these tests is the two boundaries the server owns: that the browser
never receives a token, and that the ADP read-proxy is a fixed list of paths
rather than a hole. The rest is that the routes serve the same functions the CLI
does, so the web UX cannot become a second implementation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

fastapi = pytest.importorskip("fastapi", reason="the API needs the [server] extra")
from fastapi.testclient import TestClient  # noqa: E402

from duva_bench.adp.client import AdpClient  # noqa: E402
from duva_bench.exec.harbor import HarborTrial, load_trial  # noqa: E402
from duva_bench.exec.ledger import ProviderLimiter  # noqa: E402
from duva_bench.exec.scheduler import run_study  # noqa: E402
from duva_bench.server.app import ADP_READ_PATHS, create_app  # noqa: E402
from duva_bench.server.frames import FrameCache, read_frames, resume_point  # noqa: E402
from duva_bench.state import StateDir  # noqa: E402
from duva_bench.study.models import Arm, Study, TaskRef  # noqa: E402
from tests.fakes import GRADER_TOKEN, RUNNER_TOKEN, FakeAdp  # noqa: E402

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "smoke" / "study.yaml"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "harbor"
SOURCE = EXAMPLE.read_text(encoding="utf-8")


class SmokeExecutor:
    def execute(
        self, task: TaskRef, arm: Arm, *, task_dir: Path, work_dir: Path, label: str
    ) -> HarborTrial:
        if task.id == "retry-backoff":
            return load_trial(FIXTURES / "terminus-2-retry-backoff")
        if arm.id == "twin":
            return load_trial(FIXTURES / "terminus-2-json-normalizer-partial")
        return load_trial(FIXTURES / "terminus-2-json-normalizer")


@pytest.fixture
def adp() -> FakeAdp:
    return FakeAdp()


@pytest.fixture
def client(adp: FakeAdp, tmp_path: Path) -> Any:
    def factory() -> AdpClient:
        return AdpClient(
            "https://adp.invalid",
            runner_token=RUNNER_TOKEN,
            grader_token=GRADER_TOKEN,
            transport=adp.transport,
        )

    def runner(study: Study, state: StateDir) -> Any:
        with factory() as adp_client:
            return run_study(
                study,
                state=state,
                client=adp_client,
                executor=SmokeExecutor(),
                study_dir=EXAMPLE.parent,
                concurrency=1,
                limiter=ProviderLimiter(limits={}),
            )

    app = create_app(state_root=tmp_path, client_factory=factory, runner=runner)
    with TestClient(app) as test_client:
        yield test_client


# --- studies -----------------------------------------------------------------


def test_a_study_is_uploaded_validated_and_digested(client: Any) -> None:
    response = client.post("/api/studies", content=SOURCE)
    assert response.status_code == 201
    body = response.json()
    assert body["digest"].startswith("sha256:")
    assert body["trials"] == 8
    assert body["pre_registration"]["control_arm"] == "standard"


def test_an_invalid_study_is_refused_with_the_validators_own_message(client: Any) -> None:
    response = client.post("/api/studies", content="title: no tasks here\n")
    assert response.status_code == 422
    assert "tasks" in response.json()["detail"]


def test_validation_does_not_store_anything(client: Any) -> None:
    """What the editor calls on every keystroke must not fill a directory."""
    assert client.post("/api/studies/validate", content=SOURCE).json()["ok"] is True
    assert client.get("/api/studies").json() == []


def test_the_stored_source_is_the_bytes_that_were_uploaded(client: Any) -> None:
    """A server that reformats before digesting changes what the digest attests."""
    digest = client.post("/api/studies", content=SOURCE).json()["digest"]
    assert client.get(f"/api/studies/{digest}").json()["source"] == SOURCE


def test_an_unknown_digest_is_a_404(client: Any) -> None:
    assert client.get("/api/studies/sha256:deadbeef").status_code == 404


def test_the_planned_trials_are_served_for_the_grid(client: Any) -> None:
    digest = client.post("/api/studies", content=SOURCE).json()["digest"]
    trials = client.get(f"/api/studies/{digest}").json()["trials"]
    assert len(trials) == 8
    assert trials[0]["external_ref"].endswith(":standard:json-normalizer:r1")


# --- execution and status ----------------------------------------------------


def test_running_a_study_produces_a_report_through_the_api(adp: FakeAdp, client: Any) -> None:
    """One walk of the API: define, run, analyze."""
    digest = client.post("/api/studies", content=SOURCE).json()["digest"]

    started = client.post(f"/api/studies/{digest}/run").json()
    assert started["status"] == "started"
    assert started["planned"] == 8

    _drain(client, digest)

    status = client.get(f"/api/studies/{digest}/status").json()
    assert status["verified"] == 8
    assert status["remaining"] == []

    report = client.get(f"/api/studies/{digest}/report").json()
    assert report["evidence"]["verified"] == 8
    assert report["study"]["digest"] == digest
    assert "acceptance" in report["axes"]


def test_a_second_run_request_does_not_start_a_second_study(client: Any) -> None:
    digest = client.post("/api/studies", content=SOURCE).json()["digest"]
    client.post(f"/api/studies/{digest}/run")
    second = client.post(f"/api/studies/{digest}/run").json()
    assert second["status"] in ("already running", "started")
    _drain(client, digest)


def test_the_report_route_serves_what_the_cli_would_print(
    adp: FakeAdp, client: Any, tmp_path: Path
) -> None:
    digest = client.post("/api/studies", content=SOURCE).json()["digest"]
    client.post(f"/api/studies/{digest}/run")
    _drain(client, digest)

    served = client.get(f"/api/studies/{digest}/report").json()

    from duva_bench.report.build import build_report
    from duva_bench.study.load import parse_study

    study = parse_study(SOURCE)
    with AdpClient(
        "https://adp.invalid",
        runner_token=RUNNER_TOKEN,
        grader_token=GRADER_TOKEN,
        transport=adp.transport,
    ) as adp_client:
        direct = build_report(
            study, state=StateDir.for_study(study, tmp_path), client=adp_client
        ).as_dict()

    assert served == direct, "the API and the CLI disagree about the same study"


# --- the stream --------------------------------------------------------------


def test_the_stream_replays_from_last_event_id(client: Any, tmp_path: Path) -> None:
    digest = client.post("/api/studies", content=SOURCE).json()["digest"]
    client.post(f"/api/studies/{digest}/run")
    _drain(client, digest)

    with client.stream("GET", f"/api/studies/{digest}/stream") as response:
        first = _frames(response)
    assert len(first) >= 8

    # A browser that lost its connection after the third frame asks for the
    # rest, and gets exactly the rest.
    resume = first[2]["id"]
    with client.stream(
        "GET", f"/api/studies/{digest}/stream", headers={"Last-Event-ID": str(resume)}
    ) as response:
        resumed = _frames(response)

    assert [frame["id"] for frame in resumed] == [
        frame["id"] for frame in first if frame["id"] > resume
    ]


def test_restarting_the_server_mid_study_loses_no_frames(adp: FakeAdp, tmp_path: Path) -> None:
    """The M7 done-condition, run literally.

    Two app instances over one state directory, with the client resuming from
    the last id it saw. The frames survive because they are on disk and the id
    is a byte offset into that file — nothing about the resume lives in the
    process that died.
    """

    def factory() -> AdpClient:
        return AdpClient(
            "https://adp.invalid",
            runner_token=RUNNER_TOKEN,
            grader_token=GRADER_TOKEN,
            transport=adp.transport,
        )

    def runner(study: Study, state: StateDir) -> Any:
        with factory() as adp_client:
            return run_study(
                study,
                state=state,
                client=adp_client,
                executor=SmokeExecutor(),
                study_dir=EXAMPLE.parent,
                concurrency=1,
                limiter=ProviderLimiter(limits={}),
            )

    def app() -> Any:
        return create_app(state_root=tmp_path, client_factory=factory, runner=runner)

    with TestClient(app()) as first:
        digest = first.post("/api/studies", content=SOURCE).json()["digest"]
        first.post(f"/api/studies/{digest}/run")
        _drain(first, digest)
        with first.stream("GET", f"/api/studies/{digest}/stream") as response:
            before = _frames(response)

    seen = [frame for frame in before if frame.get("event") == "trial"]
    assert len(seen) == 8
    cut = seen[3]["id"]

    # The server is gone. A browser reconnects to a fresh one, from where it was.
    with (
        TestClient(app()) as second,
        second.stream(
            "GET", f"/api/studies/{digest}/stream", headers={"Last-Event-ID": str(cut)}
        ) as response,
    ):
        after = _frames(response)

    resumed = [frame for frame in after if frame.get("event") == "trial"]
    assert [frame["id"] for frame in resumed] == [
        frame["id"] for frame in seen if frame["id"] > cut
    ]
    assert len(resumed) == 4, "a frame was lost across the restart"


def test_a_stream_that_has_nothing_left_says_done(client: Any) -> None:
    digest = client.post("/api/studies", content=SOURCE).json()["digest"]
    client.post(f"/api/studies/{digest}/run")
    _drain(client, digest)
    with client.stream("GET", f"/api/studies/{digest}/stream") as response:
        assert any(frame["event"] == "done" for frame in _frames(response))


# --- frames, on their own ----------------------------------------------------


def test_frames_are_identified_by_byte_offset(tmp_path: Path) -> None:
    log = tmp_path / "progress.jsonl"
    log.write_text('{"a": 1}\n{"a": 2}\n', encoding="utf-8")
    frames = read_frames(log)
    assert [frame.data for frame in frames] == [{"a": 1}, {"a": 2}]
    assert frames[-1].id == log.stat().st_size


def test_a_torn_final_line_is_not_emitted_until_it_is_whole(tmp_path: Path) -> None:
    log = tmp_path / "progress.jsonl"
    log.write_text('{"a": 1}\n{"a": 2', encoding="utf-8")
    assert [frame.data for frame in read_frames(log)] == [{"a": 1}]

    log.write_text('{"a": 1}\n{"a": 2}\n', encoding="utf-8")
    assert len(read_frames(log)) == 2


def test_a_missing_or_broken_last_event_id_replays_everything() -> None:
    """Replaying too much is a duplicate row; too little is a row nobody sees."""
    assert resume_point(None) == 0
    assert resume_point("not-a-number") == 0
    assert resume_point("-5") == 0
    assert resume_point("42") == 42


def test_the_frame_cache_is_keyed_by_path_not_by_study(tmp_path: Path) -> None:
    """Two studies can share a digest; two files cannot share a path."""
    cache = FrameCache()
    first = tmp_path / "a" / "progress.jsonl"
    second = tmp_path / "b" / "progress.jsonl"
    for path, value in ((first, 1), (second, 2)):
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"trial": value}) + "\n", encoding="utf-8")

    assert cache.frames(first)[0].data == {"trial": 1}
    assert cache.frames(second)[0].data == {"trial": 2}


def test_the_frame_cache_notices_a_file_that_grew(tmp_path: Path) -> None:
    cache = FrameCache()
    log = tmp_path / "progress.jsonl"
    log.write_text('{"a": 1}\n', encoding="utf-8")
    assert len(cache.frames(log)) == 1

    with log.open("a", encoding="utf-8") as handle:
        handle.write('{"a": 2}\n')
    assert len(cache.frames(log)) == 2


# --- the ADP read-proxy ------------------------------------------------------


def test_the_proxy_serves_exactly_six_literal_paths() -> None:
    """Not a wildcard. A wildcard in front of a write token is a write endpoint."""
    assert len(ADP_READ_PATHS) == 6
    assert all(path.startswith("/api/adp/repos/") for path in ADP_READ_PATHS.values())
    assert all("*" not in path for path in ADP_READ_PATHS.values())


def test_the_proxy_refuses_a_path_it_does_not_hold(client: Any) -> None:
    response = client.get(
        "/api/adp/runs_close", params={"owner": "duva", "repo": "bench", "run_id": "x"}
    )
    assert response.status_code == 404
    assert "readable ADP paths" in response.json()["detail"]


def test_the_proxy_reads_a_run_on_the_browsers_behalf(adp: FakeAdp, client: Any) -> None:
    digest = client.post("/api/studies", content=SOURCE).json()["digest"]
    client.post(f"/api/studies/{digest}/run")
    _drain(client, digest)

    run_id = next(iter(adp.runs))
    verified = client.get(
        "/api/adp/run_verify", params={"owner": "duva", "repo": "bench-smoke", "run_id": run_id}
    )
    assert verified.status_code == 200
    assert verified.json()["ok"] is True


def test_no_response_from_the_api_carries_a_token(adp: FakeAdp, client: Any) -> None:
    """The browser never holds a credential, and this is the assertion of it."""
    digest = client.post("/api/studies", content=SOURCE).json()["digest"]
    client.post(f"/api/studies/{digest}/run")
    _drain(client, digest)
    run_id = next(iter(adp.runs))

    bodies = [
        client.get("/api/studies").text,
        client.get(f"/api/studies/{digest}").text,
        client.get(f"/api/studies/{digest}/status").text,
        client.get(f"/api/studies/{digest}/report").text,
        client.get("/api/health").text,
        client.get(
            "/api/adp/run_stats", params={"owner": "duva", "repo": "bench-smoke", "run_id": run_id}
        ).text,
    ]
    for body in bodies:
        assert RUNNER_TOKEN not in body
        assert GRADER_TOKEN not in body
        assert "Authorization" not in body


def test_health_says_what_is_missing_rather_than_failing(client: Any) -> None:
    body = client.get("/api/health").json()
    assert body["ok"] is True
    assert "adp_configured" in body


# --- helpers -----------------------------------------------------------------


def _drain(client: Any, digest: str, *, attempts: int = 200) -> None:
    """Wait for the background run to finish, the way a poller would."""
    import time

    for _ in range(attempts):
        status = client.get(f"/api/studies/{digest}/status").json()
        if not status["running"] and not status["remaining"]:
            return
        time.sleep(0.05)
    raise AssertionError("the study did not finish")


def _frames(response: Any) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    current: dict[str, Any] = {}
    for line in response.iter_lines():
        if not line:
            if current:
                frames.append(current)
                current = {}
            continue
        if line.startswith(":"):
            continue
        key, _, value = line.partition(": ")
        if key == "id":
            current["id"] = int(value)
        elif key == "event":
            current["event"] = value
        elif key == "data":
            current["data"] = json.loads(value)
        if current.get("event") == "done":
            frames.append(current)
            break
    return frames
