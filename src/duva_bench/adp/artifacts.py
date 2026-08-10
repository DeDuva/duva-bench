"""Publishing a trial's work product into ADP, so its run has a commit.

ADP will not close a run against a ``final_git_sha`` it cannot resolve in the
repository — it refuses to attest a commit nobody can fetch later, for the same
reason a checkpoint resolves its sha at write time. That is a good rule and it
collides with how this project executes: a Harbor trial runs in a container that
is destroyed at the end, and what it leaves behind is a directory of collected
artifacts, not a commit.

The first version of the trial runner closed every run against the all-zero sha,
reasoning that it was "the null commit" and honest about producing nothing. ADP
rejects it with 422, so **no trial could close at all** — and the only remaining
path, abandoning the run, produces a run with no signed attestation whatsoever
(``envelope_verified`` and ``trajectory_digest_matches`` both come back
not-applicable). Passing an evidence gate that way would mean the arm labels
were never bound to the trajectory digest by anything, which is the entire
proposition of recording to ADP.

So the artifacts become a commit. This is not a workaround dressed as a feature:
the thing a reviewer most wants when a trial is surprising is *what the agent
actually produced*, and until now that was thrown away with the container. Now
the attestation's subject is exactly that, fetchable by sha forever.

What is deliberately **not** here: reading git back out. duva-bench writes these
objects and never uses ADP as a filesystem. Analysis reads runs, evals and
trajectories, as execution-plan §M6 says.
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeAlias

if TYPE_CHECKING:  # pragma: no cover - import cycle only matters to type checkers
    from duva_bench.adp.client import AdpClient

# Git blob mode for a plain file. Harbor's artifacts are data, and marking one
# executable would be a claim about it this code cannot support.
BLOB_MODE = "100644"

# Anything larger is recorded by name, size and digest rather than by content.
# The cap exists because a trial can collect a multi-gigabyte core dump, and a
# study that silently pushes one into the evidence repository per trial stops
# being runnable long before anybody notices why.
MAX_FILE_BYTES = 1 * 1024 * 1024

# The path inside the commit where everything Harbor collected is placed, kept
# under one prefix so the manifest is never confused for an artifact.
ARTIFACT_PREFIX = "artifacts"
MANIFEST_PATH = "trial.json"

_UNSAFE_REF_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


class PublishFailed(RuntimeError):
    """The artifacts could not be written, so the run has nothing to close on."""


@dataclass(frozen=True)
class PublishedArtifacts:
    """What was written, and what was left out of it."""

    commit_sha: str
    ref: str
    file_count: int
    skipped: tuple[str, ...]


def ref_for(external_ref: str) -> str:
    """A git ref name for a trial.

    One ref per trial rather than a moving branch. A study runs its factorial
    concurrently (M5), and every trial advancing the same branch would be a
    write race whose loser silently attests the wrong subject. Refs outside
    ``refs/heads/`` are also invisible to anyone browsing the repository's
    branches, which is right: these commits are evidence, not development.
    """
    safe = _UNSAFE_REF_CHARS.sub("-", external_ref).strip("-")
    return f"refs/duva-bench/trials/{safe or 'trial'}"


def _entry(path: str, sha: str) -> dict[str, Any]:
    return {"path": path, "mode": BLOB_MODE, "type": "blob", "sha": sha}


# A directory in a git tree.
TREE_MODE = "040000"

# One level of the tree being assembled: a name maps either to a blob sha or to
# another level.
_Node: TypeAlias = dict[str, "str | _Node"]


def _insert(root: _Node, path: str, blob_sha: str) -> None:
    """Place ``blob_sha`` at ``path``, creating intermediate levels."""
    *directories, name = path.split("/")
    node = root
    for directory in directories:
        child = node.get(directory)
        if not isinstance(child, dict):
            child = {}
            node[directory] = child
        node = child
    node[name] = blob_sha


def _write_tree(client: AdpClient, owner: str, repo: str, node: _Node) -> str:
    """Write ``node`` bottom-up and return the sha of the tree at its root.

    ADP builds trees with ``git mktree``, which takes **one level at a time**:
    an entry path is a single name, never ``a/b/c``. GitHub's API accepts nested
    paths and splits them for you, and the first version of this code assumed
    the same — every trial died with ``git mktree exited with code 128`` as soon
    as an artifact sat in a subdirectory, which for a Harbor trial is all of
    them (``agent/trajectory.json``, ``verifier/test-stdout.txt``).
    """
    entries: list[dict[str, Any]] = []
    for name, value in sorted(node.items()):
        if isinstance(value, str):
            entries.append(_entry(name, value))
        else:
            entries.append(
                {
                    "path": name,
                    "mode": TREE_MODE,
                    "type": "tree",
                    "sha": _write_tree(client, owner, repo, value),
                }
            )
    return client.create_tree(owner, repo, entries=entries)


def publish_trial_artifacts(
    client: AdpClient,
    owner: str,
    repo: str,
    *,
    directory: Path | None,
    manifest: dict[str, Any],
    external_ref: str,
    message: str,
) -> PublishedArtifacts:
    """Write ``directory`` into ``owner/repo`` as one commit; return its sha.

    The commit always contains ``trial.json`` even when the trial collected
    nothing, because a tree has to be non-empty to become a commit and because
    "this trial produced no artifacts" is itself a finding worth attesting to.

    ``manifest`` must never carry a secret: it goes into a repository that
    outlives the study, and execution-plan §0.7 puts tokens in the environment
    and nowhere else.
    """
    root: _Node = {}
    file_count = 0
    skipped: list[str] = []
    inventory: list[dict[str, Any]] = []

    for file in sorted(_files(directory)):
        assert directory is not None  # _files yields nothing without a directory
        relative = file.relative_to(directory).as_posix()
        size = file.stat().st_size
        if size > MAX_FILE_BYTES:
            # Recorded, not silently dropped: an artifact missing from the
            # commit with nothing saying so is indistinguishable from a trial
            # that never wrote it.
            skipped.append(relative)
            inventory.append({"path": relative, "bytes": size, "included": False})
            continue
        try:
            blob = client.create_blob(
                owner,
                repo,
                content=base64.b64encode(file.read_bytes()).decode("ascii"),
                encoding="base64",
            )
        except Exception as exc:  # re-raised with the path that failed
            raise PublishFailed(f"could not write {relative}: {exc}") from exc
        _insert(root, f"{ARTIFACT_PREFIX}/{relative}", blob)
        file_count += 1
        inventory.append({"path": relative, "bytes": size, "included": True})

    full_manifest = dict(manifest)
    full_manifest["artifacts"] = inventory
    manifest_blob = client.create_blob(
        owner,
        repo,
        content=json.dumps(full_manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    _insert(root, MANIFEST_PATH, manifest_blob)

    tree = _write_tree(client, owner, repo, root)
    # No parent. These commits are siblings, not a history: trial N+1 does not
    # build on trial N, and chaining them would invent an ordering the
    # experiment does not have.
    commit = client.create_commit(owner, repo, message=message, tree=tree, parents=[])
    ref = ref_for(external_ref)
    client.create_ref(owner, repo, ref=ref, sha=commit)
    return PublishedArtifacts(
        commit_sha=commit,
        ref=ref,
        file_count=file_count,
        skipped=tuple(skipped),
    )


def _files(directory: Path | None) -> list[Path]:
    if directory is None or not directory.is_dir():
        return []
    return [p for p in directory.rglob("*") if p.is_file() and not p.is_symlink()]
