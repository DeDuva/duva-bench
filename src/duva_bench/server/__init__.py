"""The JSON API the web UX is a client of (M7)."""

from __future__ import annotations

__all__ = ["create_app", "serve"]


def __getattr__(name: str) -> object:
    # Lazy, so importing `duva_bench.server` does not require FastAPI to be
    # installed — a checkout that only reads results should not need it.
    if name == "create_app":
        from duva_bench.server.app import create_app

        return create_app
    if name == "serve":
        from duva_bench.server.run import serve

        return serve
    raise AttributeError(name)
