"""FastAPI main server."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routes import market, strategy, trading, monitor
from src.api.chat import router as chat_router

app = FastAPI(
    title="Trading Bot API",
    description="AI-powered cryptocurrency trading bot",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(market.router, prefix="/api/market", tags=["Market"])
app.include_router(strategy.router, prefix="/api/strategy", tags=["Strategy"])
app.include_router(trading.router, prefix="/api/trading", tags=["Trading"])
app.include_router(monitor.router, prefix="/api/monitor", tags=["Monitor"])
app.include_router(chat_router, prefix="/api", tags=["Chat"])


@app.get("/health")
async def health():
    return {"status": "ok", "service": "trading-bot"}
