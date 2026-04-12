"""Web dashboard — serves the FastAPI app with uvicorn."""

from __future__ import annotations

import uvicorn

from config.settings import settings


def run_dashboard(host: str = "0.0.0.0", port: int = 8000) -> None:
    """Start the web dashboard server."""
    uvicorn.run(
        "src.api.server:app",
        host=host,
        port=port,
        reload=False,
        log_level=settings.log_level.lower(),
    )
