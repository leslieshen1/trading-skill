"""Backtest report generator — text and JSON output."""

from __future__ import annotations

import json
from datetime import datetime

from src.backtest.engine import BacktestResult


def generate_text_report(result: BacktestResult) -> str:
    """Generate a human-readable backtest report."""
    lines: list[str] = []
    lines.append("=" * 60)
    lines.append("                    回测报告")
    lines.append("=" * 60)
    lines.append(f"交易对:       {result.symbol}")
    lines.append(f"K线周期:     {result.interval}")
    lines.append(f"总K线数:     {result.total_bars}")
    if result.start_time:
        lines.append(f"开始时间:     {_ts_to_str(result.start_time)}")
        lines.append(f"结束时间:     {_ts_to_str(result.end_time)}")
    lines.append("")
    lines.append(f"初始资金:     ${result.initial_equity:,.2f}")
    lines.append(f"最终资金:     ${result.final_equity:,.2f}")
    lines.append(f"总收益:       ${result.final_equity - result.initial_equity:+,.2f}")
    lines.append(f"收益率:       {result.return_pct:+.2f}%")
    lines.append("")

    if result.metrics:
        lines.append("-" * 40)
        lines.append("  绩效指标")
        lines.append("-" * 40)
        lines.append(result.metrics.summary())
        lines.append("")

    if result.trades:
        lines.append("-" * 40)
        lines.append("  交易明细 (最近20笔)")
        lines.append("-" * 40)
        lines.append(f"{'方向':>6} | {'入场':>12} | {'出场':>12} | {'PnL':>10} | {'原因':>12} | 策略")
        lines.append("-" * 80)
        for t in result.trades[-20:]:
            pnl_str = f"{t.pnl:+.2f}"
            lines.append(
                f"{t.direction:>6} | {t.entry_price:>12.4f} | {t.exit_price:>12.4f} | "
                f"{pnl_str:>10} | {t.exit_reason:>12} | {t.strategy}"
            )

        # Strategy breakdown
        strategies = set(t.strategy for t in result.trades)
        if len(strategies) > 1:
            lines.append("")
            lines.append("-" * 40)
            lines.append("  按策略统计")
            lines.append("-" * 40)
            for strat in sorted(strategies):
                strat_trades = [t for t in result.trades if t.strategy == strat]
                strat_pnl = sum(t.pnl for t in strat_trades)
                strat_wins = sum(1 for t in strat_trades if t.pnl > 0)
                strat_wr = strat_wins / len(strat_trades) * 100 if strat_trades else 0
                lines.append(
                    f"  {strat}: {len(strat_trades)} 笔 | "
                    f"PnL: {strat_pnl:+.2f} | 胜率: {strat_wr:.1f}%"
                )

    lines.append("")
    lines.append("=" * 60)
    return "\n".join(lines)


def generate_json_report(result: BacktestResult) -> dict:
    """Generate a JSON-serializable backtest report."""
    trades_data = [
        {
            "symbol": t.symbol,
            "direction": t.direction,
            "entry_price": t.entry_price,
            "exit_price": t.exit_price,
            "quantity": t.quantity,
            "pnl": t.pnl,
            "pnl_pct": t.pnl_pct,
            "commission": t.commission,
            "strategy": t.strategy,
            "exit_reason": t.exit_reason,
        }
        for t in result.trades
    ]

    metrics_data = {}
    if result.metrics:
        m = result.metrics
        metrics_data = {
            "total_trades": m.total_trades,
            "win_rate": round(m.win_rate, 2),
            "total_pnl": round(m.total_pnl, 2),
            "profit_factor": round(m.profit_factor, 2),
            "sharpe_ratio": round(m.sharpe_ratio, 2),
            "sortino_ratio": round(m.sortino_ratio, 2),
            "max_drawdown_pct": round(m.max_drawdown, 2),
            "max_consecutive_losses": m.max_consecutive_losses,
            "expectancy": round(m.expectancy, 4),
        }

    return {
        "symbol": result.symbol,
        "interval": result.interval,
        "total_bars": result.total_bars,
        "initial_equity": result.initial_equity,
        "final_equity": result.final_equity,
        "return_pct": round(result.return_pct, 2),
        "metrics": metrics_data,
        "trades": trades_data,
        "equity_curve": result.equity_curve,
    }


def _ts_to_str(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d %H:%M")
