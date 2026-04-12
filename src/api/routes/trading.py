"""Trading operations API routes."""

from __future__ import annotations

from fastapi import APIRouter

from src.storage.database import async_session
from src.storage.repo_trades import TradeRepo
from src.storage.repo_signals import SignalRepo

router = APIRouter()


@router.get("/positions")
async def get_open_positions():
    async with async_session() as session:
        repo = TradeRepo(session)
        trades = await repo.get_open_trades()
        return [
            {
                "id": t.id,
                "symbol": t.symbol,
                "market": t.market,
                "side": t.side,
                "signal": t.signal,
                "strategy": t.strategy_name,
                "entry_price": t.entry_price,
                "quantity": t.quantity,
                "stop_loss": t.stop_loss,
                "take_profit": t.take_profit,
                "opened_at": t.opened_at,
            }
            for t in trades
        ]


@router.get("/history")
async def get_trade_history(limit: int = 50):
    async with async_session() as session:
        repo = TradeRepo(session)
        trades = await repo.get_recent_closed(limit=limit)
        return [
            {
                "id": t.id,
                "symbol": t.symbol,
                "signal": t.signal,
                "strategy": t.strategy_name,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "pnl": t.pnl,
                "opened_at": t.opened_at,
                "closed_at": t.closed_at,
            }
            for t in trades
        ]


@router.get("/signals")
async def get_recent_signals(symbol: str | None = None, limit: int = 50):
    async with async_session() as session:
        repo = SignalRepo(session)
        signals = await repo.get_recent(symbol=symbol, limit=limit)
        return [
            {
                "id": s.id,
                "symbol": s.symbol,
                "strategy": s.strategy_name,
                "signal": s.signal,
                "confidence": s.confidence,
                "entry_price": s.entry_price,
                "ai_approved": s.ai_approved,
                "executed": s.executed,
                "timestamp": s.timestamp,
            }
            for s in signals
        ]
