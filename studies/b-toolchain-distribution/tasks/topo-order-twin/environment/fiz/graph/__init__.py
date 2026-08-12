"""Dependency resolution."""


class Cycle(Exception):
    """Raised when a graph cannot be ordered. `members` holds who is involved."""

    def __init__(self, members):
        super().__init__(f"cycle among {sorted(members)}")
        self.members = sorted(members)


def resolve(graph):
    """Return the names of `graph` in dependency order."""
    raise NotImplementedError
