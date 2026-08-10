"""M2: the spool and the recorder.

The plan's done-condition is "spool replay, dedupe, gap rejection" plus a
recorder that survives a SIGKILL. The kill test really does send SIGKILL to a
real child process, because the failure it guards against — an event that was
returned to the caller and never made it out of memory — is invisible to a test
that simulates a crash by calling a method.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from duva_bench.adp.client import AdpClient, AppendRejected
from duva_bench.adp.recorder import Recorder, RecorderStopped
from duva_bench.adp.spool import Spool, SpoolCorrupt
from tests.fakes import GRADER_TOKEN, RUNNER_TOKEN, FakeAdp


@pytest.fixture
def adp() -> FakeAdp:
    return FakeAdp()


@pytest.fixture
def client(adp: FakeAdp) -> AdpClient:
    return AdpClient(
        "https://adp.invalid",
        runner_token=RUNNER_TOKEN,
        grader_token=GRADER_TOKEN,
        transport=adp.transport,
    )


def _session(client: AdpClient) -> str:
    return client.create_session("duva", "bench", harness="duva-bench").id


# --- the spool --------------------------------------------------------------


def test_sequence_numbers_start_at_one_and_are_contiguous(tmp_path: Path) -> None:
    spool = Spool(tmp_path)
    assert [spool.append({"kind": "message"}) for _ in range(3)] == [1, 2, 3]


def test_a_client_event_id_is_derived_not_random(tmp_path: Path) -> None:
    """A random id would make replay append twice instead of deduplicating."""
    spool = Spool(tmp_path, producer_id="p")
    spool.append({"kind": "message"})
    assert spool.pending()[0]["client_event_id"] == "p:1"


def test_a_restart_keeps_the_producer_identity_and_the_count(tmp_path: Path) -> None:
    first = Spool(tmp_path, producer_id="p")
    first.append({"kind": "message"})
    second = Spool(tmp_path)
    assert second.producer_id == "p"
    assert second.next_seq == 2


def test_resuming_under_a_different_identity_is_refused(tmp_path: Path) -> None:
    Spool(tmp_path, producer_id="p").append({"kind": "message"})
    with pytest.raises(SpoolCorrupt, match="belongs to producer"):
        Spool(tmp_path, producer_id="q")


def test_trimming_drops_acknowledged_events_only(tmp_path: Path) -> None:
    spool = Spool(tmp_path)
    for _ in range(5):
        spool.append({"kind": "message"})
    spool.trim(3)
    assert [event["producer_seq"] for event in spool.pending()] == [4, 5]
    assert spool.accepted_through == 3


def test_trimming_backwards_is_refused(tmp_path: Path) -> None:
    spool = Spool(tmp_path)
    spool.append({"kind": "message"})
    spool.trim(1)
    with pytest.raises(SpoolCorrupt, match="cannot supply events it has dropped"):
        spool.trim(0)


def test_a_resume_point_below_the_trim_mark_is_not_recoverable(tmp_path: Path) -> None:
    spool = Spool(tmp_path)
    for _ in range(3):
        spool.append({"kind": "message"})
    spool.trim(3)
    assert spool.can_resume_from(4) is True
    assert spool.can_resume_from(2) is False


def test_a_half_written_final_line_is_dropped_not_fatal(tmp_path: Path) -> None:
    spool = Spool(tmp_path)
    spool.append({"kind": "message"})
    with (tmp_path / "events.jsonl").open("a", encoding="utf-8") as handle:
        handle.write('{"kind": "mess')
    assert len(Spool(tmp_path).pending()) == 1


def test_corruption_anywhere_but_the_last_line_is_fatal(tmp_path: Path) -> None:
    spool = Spool(tmp_path)
    spool.append({"kind": "message"})
    spool.append({"kind": "message"})
    lines = (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()
    (tmp_path / "events.jsonl").write_text("{not json\n" + lines[1] + "\n", encoding="utf-8")
    with pytest.raises(SpoolCorrupt, match="is not valid JSON"):
        Spool(tmp_path).pending()


# --- the recorder -----------------------------------------------------------


def test_recorded_events_reach_adp_in_order(
    adp: FakeAdp, client: AdpClient, tmp_path: Path
) -> None:
    session_id = _session(client)
    recorder = Recorder(client, "duva", "bench", session_id, Spool(tmp_path))
    with recorder:
        for index in range(5):
            recorder.record("tool_call", type=f"tool-{index}", payload={"i": index})

    stored = adp.events[session_id]
    assert [event.producer_seq for event in stored] == [1, 2, 3, 4, 5]
    assert recorder.stats.appended == 5


def test_a_gap_rejection_replays_from_where_adp_asks(
    adp: FakeAdp, client: AdpClient, tmp_path: Path
) -> None:
    """ADP holds 1-2 already; this recorder thinks it is starting at 1."""
    session_id = _session(client)
    client.append_events(
        "duva",
        "bench",
        session_id,
        [
            {"kind": "message", "payload": {}, "producer_seq": 1, "client_event_id": "other:1"},
            {"kind": "message", "payload": {}, "producer_seq": 2, "client_event_id": "other:2"},
        ],
    )

    spool = Spool(tmp_path, producer_id="p")
    recorder = Recorder(client, "duva", "bench", session_id, spool)
    for index in range(3):
        recorder.record("message", payload={"i": index})
    recorder.flush(timeout=5)

    # It replays from ADP's `expected_next_seq` rather than guessing, so the
    # chain ends contiguous rather than with a hole nobody notices.
    assert recorder.stats.resumes == 1
    assert [event.producer_seq for event in adp.events[session_id]] == [1, 2, 3]


def test_a_409_with_no_resume_point_stops_the_recorder(
    client: AdpClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No `expected_next_seq` means the session is closed; retrying never helps."""
    session_id = _session(client)
    spool = Spool(tmp_path)
    recorder = Recorder(client, "duva", "bench", session_id, spool)
    recorder.record("message", payload={})

    def closed(*args: object, **kwargs: object) -> object:
        raise AppendRejected("closed", status=409, body={"message": "session closed"})

    monkeypatch.setattr(client, "append_events", closed)
    with pytest.raises(RecorderStopped, match="session is closed"):
        recorder.flush(timeout=2)


def test_a_transport_failure_is_retried_and_its_duplicates_are_expected(
    adp: FakeAdp, client: AdpClient, tmp_path: Path
) -> None:
    """A resend whose first outcome was unknown is not a bug signal."""
    session_id = _session(client)
    recorder = Recorder(client, "duva", "bench", session_id, Spool(tmp_path), poll_interval=0.01)
    recorder.record("message", payload={})
    adp.fail_next_append_with = 503

    recorder.flush(timeout=5)

    assert recorder.stats.retries == 1
    assert recorder.stats.unexpected_duplicates == 0
    assert len(adp.events[session_id]) == 1


def test_a_duplicate_with_no_retry_to_explain_it_is_reported(
    adp: FakeAdp, client: AdpClient, tmp_path: Path
) -> None:
    seen: list[tuple[str, ...]] = []
    session_id = _session(client)
    spool = Spool(tmp_path, producer_id="p")
    recorder = Recorder(
        client,
        "duva",
        "bench",
        session_id,
        spool,
        on_unexpected_duplicates=seen.append,
    )
    # ADP already holds this exact client_event_id, and nothing this recorder
    # did explains that.
    client.append_events(
        "duva",
        "bench",
        session_id,
        [{"kind": "message", "payload": {}, "producer_seq": 1, "client_event_id": "p:1"}],
    )
    recorder.record("message", payload={})
    recorder.flush(timeout=5)

    assert recorder.stats.unexpected_duplicates == 1
    assert seen == [("p:1",)]


def test_a_non_contiguous_batch_is_caught_locally(client: AdpClient, tmp_path: Path) -> None:
    session_id = _session(client)
    spool = Spool(tmp_path)
    spool.append({"kind": "message", "payload": {}})
    # A hand-written hole: what a bug in this client would produce.
    with (tmp_path / "events.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"kind": "message", "payload": {}, "producer_seq": 5}) + "\n")

    recorder = Recorder(client, "duva", "bench", session_id, Spool(tmp_path))
    with pytest.raises(RecorderStopped, match="not contiguous"):
        recorder.flush(timeout=2)


def test_recording_after_a_fatal_failure_raises_rather_than_spooling_into_a_void(
    client: AdpClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_id = _session(client)
    recorder = Recorder(client, "duva", "bench", session_id, Spool(tmp_path))
    recorder.record("message", payload={})

    def closed(*args: object, **kwargs: object) -> object:
        raise AppendRejected("closed", status=409, body={})

    monkeypatch.setattr(client, "append_events", closed)
    with pytest.raises(RecorderStopped):
        recorder.flush(timeout=2)
    with pytest.raises(RecorderStopped):
        recorder.record("message", payload={})


# --- the kill test ----------------------------------------------------------


KILLED_WRITER = """
import os
import signal
import sys

sys.path.insert(0, {src!r})
from duva_bench.adp.spool import Spool

spool = Spool({root!r}, producer_id="killed-producer")
for index in range(6):
    spool.append({{"kind": "tool_call", "payload": {{"i": index}}}})
    if index == 3:
        sys.stdout.flush()
        os.kill(os.getpid(), signal.SIGKILL)
"""


def test_a_sigkilled_recorder_leaves_a_resumable_gap_free_chain(
    adp: FakeAdp, client: AdpClient, tmp_path: Path
) -> None:
    """The done-condition, run for real.

    A child process spools events and is SIGKILLed mid-write. A fresh recorder
    picks the spool up, and what ADP ends up holding is contiguous from 1 with
    no hole and no duplicate — which is the whole claim the chain makes.
    """
    source = str(Path(__file__).resolve().parents[1] / "src")
    script = KILLED_WRITER.format(src=source, root=str(tmp_path))
    completed = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script)], capture_output=True, timeout=60
    )
    assert completed.returncode == -signal.SIGKILL, "the child was supposed to die by SIGKILL"
    assert os.path.exists(tmp_path / "events.jsonl")

    resumed = Spool(tmp_path)
    assert resumed.producer_id == "killed-producer"
    survived = [event["producer_seq"] for event in resumed.pending()]
    assert survived == list(range(1, len(survived) + 1)), "the spool itself has a hole"
    assert len(survived) >= 4, "events acknowledged to the caller were lost"

    session_id = _session(client)
    with Recorder(client, "duva", "bench", session_id, resumed) as recorder:
        recorder.flush(timeout=10)

    stored = [event.producer_seq for event in adp.events[session_id]]
    assert stored == survived
    assert len(set(stored)) == len(stored), "an event was appended twice"
    assert recorder.stats.unexpected_duplicates == 0
