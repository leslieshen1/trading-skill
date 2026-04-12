"""Strategy management API routes."""

from __future__ import annotations

from fastapi import APIRouter

from src.strategy.loader import load_strategies

router = APIRouter()


@router.get("/list")
async def list_strategies():
    strategies = load_strategies()
    return [
        {
            "name": s.name,
            "enabled": s.enabled,
            "type": type(s).__name__,
            "config": {
                k: v for k, v in s.config.items()
                if k in ("description", "market", "entry", "exit", "position", "ai")
            },
        }
        for s in strategies
    ]
