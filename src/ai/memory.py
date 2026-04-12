"""Trading memory — stores historical decisions and outcomes for AI context.

Provides the AI analyst with recent trade history so it can learn from
past successes and failures within the current session.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import structlog

from src.storage.repo_trades import TradeRepo

logger = structlog.get_logger()


@dataclass
class TradeMemoryEntry:
    """A simplified record of a past trade for AI context."""

    symbol: str
    direction: str
    strategy: str
    entry_price: float
    exit_price: float | None
    pnl: float | None
    status: str
    reasoning: str | None
    ai_reasoning: str | None


class TradingMemory:
    """Manages trade history context for AI decision-making."""

    def __init__(self, trade_repo: TradeRepo):
        self.trade_repo = trade_repo

    async def get_recent_context(self, symbol: str | None = None, limit: int = 10) -> str:
        """Build a text summary of recent trades for prompt injection."""
        closed = await self.trade_repo.get_recent_closed(limit=limit)
        open_trades = await self.trade_repo.get_open_trades()

        if not closed and not open_trades:
            return "无历史交易记录。"

        lines: list[str] = []

        # Open positions
        if open_trades:
            lines.append("### 当前持仓")
            for t in open_trades:
                lines.append(
                    f"- {t.symbol} {t.signal} @ {t.entry_price} | "
                    f"策略: {t.strategy_name} | 止损: {t.stop_loss} | 止盈: {t.take_profit}"
                )
            lines.append("")

        # Recent closed trades
        if closed:
            lines.append("### 最近平仓记录")
            wins = sum(1 for t in closed if t.pnl and t.pnl > 0)
            losses = sum(1 for t in closed if t.pnl and t.pnl <= 0)
            total_pnl = sum(t.pnl for t in closed if t.pnl)
            lines.append(f"胜: {wins} | 负: {losses} | 总PnL: {total_pnl:.2f}")

            for t in closed[:5]:
                pnl_str = f"+{t.pnl:.2f}" if t.pnl and t.pnl > 0 else f"{t.pnl:.2f}" if t.pnl else "N/A"
                lines.append(
                    f"- {t.symbol} {t.signal} | 入: {t.entry_price} → 出: {t.exit_price} | "
                    f"PnL: {pnl_str} | 策略: {t.strategy_name}"
                )

            # Detect patterns
            if losses >= 3 and wins == 0:
                lines.append("\n⚠️ 注意: 近期连续亏损，建议降低仓位或暂停交易。")
            if symbol:
                symbol_trades = [t for t in closed if t.symbol == symbol]
                if symbol_trades:
                    sym_pnl = sum(t.pnl for t in symbol_trades if t.pnl)
                    lines.append(f"\n该币种({symbol})近期PnL: {sym_pnl:.2f}")

        return "\n".join(lines)

    async def get_performance_summary(self) -> str:
        """Build a performance summary for portfolio review."""
        today_trades = await self.trade_repo.get_today_trades()
        closed = await self.trade_repo.get_recent_closed(limit=50)

        if not today_trades and not closed:
            return "无交易记录。"

        lines: list[str] = []

        if today_trades:
            today_closed = [t for t in today_trades if t.status == "closed"]
            today_pnl = sum(t.pnl for t in today_closed if t.pnl)
            lines.append(f"今日交易: {len(today_trades)} 笔 | 已平仓PnL: {today_pnl:.2f}")

        if closed:
            wins = sum(1 for t in closed if t.pnl and t.pnl > 0)
            total = len(closed)
            win_rate = (wins / total * 100) if total > 0 else 0
            avg_win = 0.0
            avg_loss = 0.0
            winning = [t.pnl for t in closed if t.pnl and t.pnl > 0]
            losing = [t.pnl for t in closed if t.pnl and t.pnl <= 0]
            if winning:
                avg_win = sum(winning) / len(winning)
            if losing:
                avg_loss = sum(losing) / len(losing)
            lines.append(
                f"近期胜率: {win_rate:.1f}% ({wins}/{total}) | "
                f"平均盈利: {avg_win:.2f} | 平均亏损: {avg_loss:.2f}"
            )

        return "\n".join(lines)
