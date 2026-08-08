"""Serving the API (M7)."""

from __future__ import annotations

from pathlib import Path


def serve(*, host: str = "127.0.0.1", port: int = 8000, state_dir: Path | None = None) -> int:
    """Run the JSON API.

    uvicorn is imported here rather than at module scope so that `duva-bench
    --help` works in a checkout without the [server] extra — the same rule the
    CLI follows for Harbor.
    """
    try:
        import uvicorn
    except ModuleNotFoundError:
        raise SystemExit(
            "the API needs the server extra: pip install 'duva-bench[server]'"
        ) from None

    from duva_bench.server.app import create_app

    uvicorn.run(create_app(state_root=state_dir), host=host, port=port, log_level="info")
    return 0
