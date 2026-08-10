"""Fixtures for the live-ADP suite.

Every fixture here fails rather than skips when its input is missing. A skipped
contract test and a passing one exit the same way, and the whole reason this
directory is separate from `make test` is so that "we did not check" cannot be
mistaken for "we checked".
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest

from duva_bench.adp.client import AdpClient


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise pytest.UsageError(
            f"{name} is not set. The contract suite talks to a real ADP; see "
            "tests/contract/README.md for how to stand one up and mint two principals."
        )
    return value


@pytest.fixture(scope="session")
def base_url() -> str:
    return _required("DUVA_ADP_BASE_URL")


@pytest.fixture(scope="session")
def owner() -> str:
    return os.environ.get("DUVA_ADP_OWNER", "duva")


@pytest.fixture(scope="session")
def repo() -> str:
    return os.environ.get("DUVA_ADP_REPO", "bench-contract")


@pytest.fixture
def client(base_url: str) -> Iterator[AdpClient]:
    with AdpClient(
        base_url,
        runner_token=_required("DUVA_ADP_RUNNER_TOKEN"),
        grader_token=_required("DUVA_ADP_GRADER_TOKEN"),
    ) as adp:
        yield adp


@pytest.fixture
def intent_id(client: AdpClient, owner: str, repo: str) -> str:
    """An intent, minted the only way ADP allows (§3.3).

    Nothing in `/api/adp` creates one; an intent exists as a side effect of
    filing an issue on the compat plane. This fixture is where that dependency
    lives, so nobody later reads a compat-plane call on the hot path as
    precedent.
    """
    issue = client.mint_intent(owner, repo, title=f"duva-bench contract {uuid.uuid4().hex[:8]}")
    return issue.intent_id
