"""Credentials, and where they are allowed to come from (execution-plan §0.7).

Secrets come **only** from the environment. Nothing here writes one to disk,
puts one in a log line, or lets one into an ADP payload — and the one place a
token could plausibly leak sideways, the grader subprocess, gets an environment
built by :func:`stripped_environment` rather than inherited.

The names are duva-bench's own (``DUVA_ADP_*``) rather than ADP's, because a
machine may hold tokens for several ADP consumers and "the ADP token" is not a
thing that machine has one of.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from duva_bench.adp.client import AdpClient

BASE_URL = "DUVA_ADP_BASE_URL"
RUNNER_TOKEN = "DUVA_ADP_RUNNER_TOKEN"
GRADER_TOKEN = "DUVA_ADP_GRADER_TOKEN"

# Anything matching these is stripped from a grader's environment. Prefixes
# rather than an exact list: a provider key this project has never heard of is
# still a provider key, and the failure mode of stripping one variable too many
# is a grader that says so, while the failure mode of keeping one is a grader
# that could call a model or write to ADP as the runner.
SECRET_PREFIXES: tuple[str, ...] = (
    "DUVA_ADP_",
    "ADP_",
    "ANTHROPIC_",
    "OPENAI_",
    "GOOGLE_",
    "GEMINI_",
    "AZURE_",
    "AWS_",
    "XAI_",
    "MISTRAL_",
    "COHERE_",
    "DEEPSEEK_",
    "TOGETHER_",
    "GROQ_",
    "OPENROUTER_",
    "HF_",
    "HUGGING_FACE_",
    "GITHUB_",
    "GH_",
)

SECRET_SUBSTRINGS: tuple[str, ...] = ("TOKEN", "SECRET", "PASSWORD", "API_KEY", "APIKEY")


class MissingCredentials(RuntimeError):
    """A required credential is not in the environment."""


@dataclass(frozen=True)
class AdpCredentials:
    """The three values needed to talk to ADP.

    Deliberately not printable: ``repr`` on a dataclass prints its fields, and
    a traceback that includes one is a traceback that has published a token.
    """

    base_url: str
    runner_token: str
    grader_token: str

    def __repr__(self) -> str:
        return f"AdpCredentials(base_url={self.base_url!r}, tokens=<redacted>)"

    def client(self, **kwargs: object) -> AdpClient:
        return AdpClient(
            self.base_url,
            runner_token=self.runner_token,
            grader_token=self.grader_token,
            **kwargs,  # type: ignore[arg-type]
        )


def adp_credentials(environ: Mapping[str, str] | None = None) -> AdpCredentials:
    """Read the credentials, naming every one that is missing at once.

    All three at once rather than one per run: finding out about the second
    missing variable after fixing the first is a worse experience for no reason.
    """
    source = os.environ if environ is None else environ
    missing = [name for name in (BASE_URL, RUNNER_TOKEN, GRADER_TOKEN) if not source.get(name)]
    if missing:
        raise MissingCredentials(
            f"{', '.join(missing)} not set. duva-bench reads ADP credentials from the "
            "environment only; see tests/contract/README.md for how tokens are minted, "
            "and note that the runner and grader tokens must belong to two different "
            "principals."
        )
    return AdpCredentials(
        base_url=source[BASE_URL],
        runner_token=source[RUNNER_TOKEN],
        grader_token=source[GRADER_TOKEN],
    )


def is_secret(name: str) -> bool:
    upper = name.upper()
    return upper.startswith(SECRET_PREFIXES) or any(marker in upper for marker in SECRET_SUBSTRINGS)


def stripped_environment(
    environ: Mapping[str, str] | None = None, *, keep: Iterable[str] = ()
) -> dict[str, str]:
    """An environment with every credential removed (M4's grader contract).

    A grader is an instrument, not a participant. It must not be able to call a
    model, and it must not be able to reach ADP under the runner's identity —
    the score it produces is posted by duva-bench, under the grader principal,
    after the grader has exited.
    """
    source = dict(os.environ if environ is None else environ)
    kept = set(keep)
    return {name: value for name, value in source.items() if name in kept or not is_secret(name)}
