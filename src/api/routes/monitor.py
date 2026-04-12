"""Monitoring API routes."""

from __future__ import annotations

from fastapi import APIRouter

from src.storage.database import async_session
from src.storage.repo_trades import TradeRepo
from src.monitor.metrics import calculate_metrics

router = APIRouter()


@router.get("/status")
async def get_status():
    """System status overview."""
    async with async_session() as session:
        repo = TradeRepo(session)
        open_trades = await repo.get_open_trades()
        today_trades = await repo.get_today_trades()
        closed_today = [t for t in today_trades if t.status == "closed"]
        today_pnl = sum(t.pnl for t in closed_today if t.pnl)

        return {
            "open_positions": len(open_trades),
            "today_trades": len(today_trades),
            "today_pnl": round(today_pnl, 2),
        }


@router.get("/performance")
async def get_performance(limit: int = 100):
    """Performance metrics for recent trades."""
    async with async_session() as session:
        repo = TradeRepo(session)
        closed = await repo.get_recent_closed(limit=limit)
        pnl_list = [t.pnl for t in closed if t.pnl is not None]

        if not pnl_list:
            return {"message": "No closed trades yet"}

        hold_times = []
        for t in closed:
            if t.opened_at and t.closed_at:
                hold_times.append(t.closed_at - t.opened_at)

        metrics = calculate_metrics(pnl_list, hold_times or None)
        return {
            "total_trades": metrics.total_trades,
            "win_rate": round(metrics.win_rate, 2),
            "total_pnl": round(metrics.total_pnl, 2),
            "avg_pnl": round(metrics.avg_pnl, 2),
            "profit_factor": round(metrics.profit_factor, 2),
            "sharpe_ratio": round(metrics.sharpe_ratio, 2),
            "max_drawdown_pct": round(metrics.max_drawdown, 2),
            "max_consecutive_losses": metrics.max_consecutive_losses,
        }
