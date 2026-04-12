"""Performance metrics — PnL, win rate, Sharpe ratio, drawdown, etc."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class PerformanceMetrics:
    """Computed performance statistics."""

    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    total_pnl: float = 0.0
    avg_pnl: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    largest_win: float = 0.0
    largest_loss: float = 0.0
    profit_factor: float = 0.0       # gross_profit / gross_loss
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    max_drawdown: float = 0.0        # as percentage
    max_drawdown_amount: float = 0.0
    max_consecutive_wins: int = 0
    max_consecutive_losses: int = 0
    avg_hold_time_hours: float = 0.0
    expectancy: float = 0.0          # avg_win * win_rate - avg_loss * loss_rate

    def summary(self) -> str:
        """Human-readable summary."""
        return (
            f"总交易: {self.total_trades} | 胜率: {self.win_rate:.1f}%\n"
            f"总PnL: {self.total_pnl:+.2f} | 平均: {self.avg_pnl:+.2f}\n"
            f"平均盈利: {self.avg_win:+.2f} | 平均亏损: {self.avg_loss:.2f}\n"
            f"最大盈利: {self.largest_win:+.2f} | 最大亏损: {self.largest_loss:.2f}\n"
            f"盈亏比: {self.profit_factor:.2f} | 期望值: {self.expectancy:+.4f}\n"
            f"Sharpe: {self.sharpe_ratio:.2f} | Sortino: {self.sortino_ratio:.2f}\n"
            f"最大回撤: {self.max_drawdown:.2f}% (${self.max_drawdown_amount:,.2f})\n"
            f"最长连胜: {self.max_consecutive_wins} | 最长连亏: {self.max_consecutive_losses}\n"
            f"平均持仓: {self.avg_hold_time_hours:.1f}h"
        )


def calculate_metrics(
    pnl_list: list[float],
    hold_times_ms: list[int] | None = None,
    risk_free_rate: float = 0.0,
) -> PerformanceMetrics:
    """Calculate performance metrics from a list of trade PnLs.

    Args:
        pnl_list: list of PnL values for each closed trade.
        hold_times_ms: optional list of hold durations in milliseconds.
        risk_free_rate: annualized risk-free rate (default 0).
    """
    m = PerformanceMetrics()
    if not pnl_list:
        return m

    arr = np.array(pnl_list, dtype=float)
    m.total_trades = len(arr)
    m.total_pnl = float(np.sum(arr))
    m.avg_pnl = float(np.mean(arr))

    wins = arr[arr > 0]
    losses = arr[arr <= 0]

    m.winning_trades = len(wins)
    m.losing_trades = len(losses)
    m.win_rate = m.winning_trades / m.total_trades * 100 if m.total_trades > 0 else 0

    if len(wins) > 0:
        m.avg_win = float(np.mean(wins))
        m.largest_win = float(np.max(wins))
    if len(losses) > 0:
        m.avg_loss = float(np.mean(losses))
        m.largest_loss = float(np.min(losses))

    # Profit factor
    gross_profit = float(np.sum(wins)) if len(wins) > 0 else 0
    gross_loss = abs(float(np.sum(losses))) if len(losses) > 0 else 0
    m.profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf") if gross_profit > 0 else 0

    # Expectancy
    loss_rate = m.losing_trades / m.total_trades if m.total_trades > 0 else 0
    win_rate_frac = m.win_rate / 100
    m.expectancy = m.avg_win * win_rate_frac + m.avg_loss * loss_rate

    # Sharpe ratio (annualized, assuming ~365 trades/year as proxy)
    if len(arr) > 1:
        std = float(np.std(arr, ddof=1))
        if std > 0:
            m.sharpe_ratio = (m.avg_pnl - risk_free_rate) / std * np.sqrt(min(len(arr), 365))

    # Sortino ratio (only downside deviation)
    if len(arr) > 1:
        downside = arr[arr < 0]
        if len(downside) > 0:
            downside_std = float(np.std(downside, ddof=1))
            if downside_std > 0:
                m.sortino_ratio = (m.avg_pnl - risk_free_rate) / downside_std * np.sqrt(min(len(arr), 365))

    # Max drawdown
    cumulative = np.cumsum(arr)
    running_max = np.maximum.accumulate(cumulative)
    drawdowns = running_max - cumulative
    if len(drawdowns) > 0:
        m.max_drawdown_amount = float(np.max(drawdowns))
        peak = float(running_max[np.argmax(drawdowns)])
        if peak > 0:
            m.max_drawdown = m.max_drawdown_amount / peak * 100

    # Consecutive streaks
    m.max_consecutive_wins = _max_streak(pnl_list, positive=True)
    m.max_consecutive_losses = _max_streak(pnl_list, positive=False)

    # Average hold time
    if hold_times_ms:
        m.avg_hold_time_hours = sum(hold_times_ms) / len(hold_times_ms) / 3_600_000

    return m


def _max_streak(pnl_list: list[float], positive: bool) -> int:
    """Count the longest consecutive win or loss streak."""
    max_streak = 0
    current = 0
    for p in pnl_list:
        if (positive and p > 0) or (not positive and p <= 0):
            current += 1
            max_streak = max(max_streak, current)
        else:
            current = 0
    return max_streak
