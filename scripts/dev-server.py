#!/usr/bin/env python3
"""Run the duva-bench API for the web UX and the Playwright walk.

Two modes, and the difference is only what is behind the server:

``DUVA_LIVE=1``
    The real thing. ADP credentials come from the environment, Harbor runs the
    trials. This is what a researcher runs.

default
    The in-memory ADP from ``tests/fakes.py`` and a recorded Harbor trial. No
    network, no container, no spend — which is what makes the UI walk runnable
    in CI, and what makes it *not* evidence that a real study works. That claim
    belongs to gate G1, and gate G1 is blocked (docs/blockers.md).

    Kept in `scripts/` rather than inside the package: a test double that ships
    to users is a test double somebody will point at production one afternoon.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

HOST = os.environ.get("DUVA_HOST", "127.0.0.1")
PORT = int(os.environ.get("DUVA_PORT", "8000"))


def state_root(*, live: bool) -> Path:
    """Where this server keeps its state.

    Live: a stable directory, because a real study has to survive a restart —
    that is the whole point of `progress.jsonl`.

    Doubled: a *fresh* directory per process. The double's ADP lives in memory
    and dies with the server, so persistent state would outlive the runs it
    points at, and the next start would find a study its ADP has never heard of
    and report it as having no results. Ephemeral state and an ephemeral ADP
    have to have the same lifetime.
    """
    if not live:
        return Path(tempfile.mkdtemp(prefix="duva-bench-dev-"))
    return Path(os.environ.get("DUVA_STATE", ROOT / ".duva-bench" / "dev"))


def live_app() -> object:
    from duva_bench.server.app import create_app

    return create_app(state_root=state_root(live=True))


def doubled_app() -> object:
    from tests.fakes import GRADER_TOKEN, RUNNER_TOKEN, FakeAdp

    from duva_bench.adp.client import AdpClient
    from duva_bench.exec.harbor import load_trial
    from duva_bench.exec.ledger import ProviderLimiter
    from duva_bench.exec.scheduler import run_study
    from duva_bench.server.app import create_app

    fixtures = ROOT / "tests" / "fixtures" / "harbor"
    example = ROOT / "examples" / "smoke"
    adp = FakeAdp()

    class RecordedExecutor:
        def execute(self, task, arm, *, task_dir, work_dir, label):  # type: ignore[no-untyped-def]
            if task.id == "retry-backoff":
                return load_trial(fixtures / "terminus-2-retry-backoff")
            if arm.id == "twin":
                return load_trial(fixtures / "terminus-2-json-normalizer-partial")
            return load_trial(fixtures / "terminus-2-json-normalizer")

    def client_factory() -> AdpClient:
        return AdpClient(
            "https://adp.invalid",
            runner_token=RUNNER_TOKEN,
            grader_token=GRADER_TOKEN,
            transport=adp.transport,
        )

    def runner(study, state):  # type: ignore[no-untyped-def]
        with client_factory() as client:
            return run_study(
                study,
                state=state,
                client=client,
                executor=RecordedExecutor(),
                study_dir=example,
                concurrency=1,
                limiter=ProviderLimiter(limits={}),
            )

    return create_app(
        state_root=state_root(live=False), client_factory=client_factory, runner=runner
    )


def main() -> int:
    import uvicorn

    live = os.environ.get("DUVA_LIVE") == "1"
    app = live_app() if live else doubled_app()
    print(
        f"duva-bench API on http://{HOST}:{PORT} "
        f"({'live ADP and Harbor' if live else 'in-memory ADP, recorded trials'})",
        flush=True,
    )
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
