"""Tests for backtest engine, metrics, and report generation."""

from __future__ import annotations

import random

import pytest

from src.backtest.engine import BacktestConfig, BacktestEngine, BacktestResult
from src.backtest.report import generate_text_report, generate_json_report
from src.monitor.metrics import PerformanceMetrics, calculate_metrics
from src.strategy.builtin.mean_reversion import MeanReversionStrategy


# ── Helpers ──────────────────────────────────────────────────────────────────

class FakeKline:
    def __init__(self, open_time, o, h, l, c, v):
        self.open_time = open_time
        self.open = o
        self.high = h
        self.low = l
        self.close = c
        self.volume = v


def _generate_klines(n: int = 100, base_price: float = 100.0, seed: int = 42) -> list[FakeKline]:
    random.seed(seed)
    klines = []
    price = base_price
    for i in range(n):
        change = random.uniform(-3, 3)
        o = price
        c = price + change
        h = max(o, c) + random.uniform(0, 2)
        l = min(o, c) - random.uniform(0, 2)
        v = random.uniform(100, 500)
        klines.append(FakeKline(1700000000000 + i * 3600000, o, h, max(0.01, l), c, v))
        price = max(c, 1.0)
    return klines


# ── Metrics Tests ────────────────────────────────────────────────────────────

def test_metrics_empty():
    m = calculate_metrics([])
    assert m.total_trades == 0
    assert m.win_rate == 0


def test_metrics_all_wins():
    pnls = [100, 200, 150, 300, 250]
    m = calculate_metrics(pnls)
    assert m.total_trades == 5
    assert m.win_rate == 100.0
    assert m.total_pnl == 1000
    assert m.losing_trades == 0
    assert m.max_consecutive_wins == 5
    assert m.max_consecutive_losses == 0


def test_metrics_mixed():
    pnls = [100, -50, 200, -80, -30, 150, 100, -20]
    m = calculate_metrics(pnls)
    assert m.total_trades == 8
    assert m.winning_trades == 4
    assert m.losing_trades == 4
    assert m.win_rate == 50.0
    assert m.total_pnl == 370
    assert m.avg_win > 0
    assert m.avg_loss < 0
    assert m.profit_factor > 1.0
    assert m.max_consecutive_losses == 2


def test_metrics_sharpe_nonzero():
    pnls = [10, -5, 15, -3, 20, -8, 12, 7, -2, 18]
    m = calculate_metrics(pnls)
    assert m.sharpe_ratio != 0


def test_metrics_max_drawdown():
    pnls = [100, 100, -200, -100, 50, 50]
    m = calculate_metrics(pnls)
    assert m.max_drawdown_amount > 0
    assert m.max_drawdown > 0


def test_metrics_hold_time():
    pnls = [100, 200]
    hold_times = [3_600_000, 7_200_000]  # 1h, 2h
    m = calculate_metrics(pnls, hold_times)
    assert m.avg_hold_time_hours == 1.5


def test_metrics_summary_string():
    pnls = [100, -50, 200]
    m = calculate_metrics(pnls)
    summary = m.summary()
    assert "总交易: 3" in summary
    assert "胜率:" in summary


# ── Backtest Engine Tests ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_backtest_runs():
    strategy = MeanReversionStrategy({
        "name": "test_mr",
        "exit": {"stop_loss": 3.0, "take_profit": 5.0},
        "position": {"risk_per_trade": 2.0},
    })
    config = BacktestConfig(initial_equity=10_000)
    engine = BacktestEngine([strategy], config)
    klines = _generate_klines(100)

    result = await engine.run(klines, symbol="TESTUSDT", interval="1h")

    assert isinstance(result, BacktestResult)
    assert result.total_bars == 100
    assert result.initial_equity == 10_000
    assert result.final_equity > 0
    assert result.metrics is not None


@pytest.mark.asyncio
async def test_backtest_insufficient_data():
    strategy = MeanReversionStrategy({
        "name": "test_mr",
        "exit": {"stop_loss": 2.0, "take_profit": 3.0},
    })
    engine = BacktestEngine([strategy])
    klines = _generate_klines(10)

    result = await engine.run(klines, symbol="TEST", lookback=50)
    assert result.final_equity == result.initial_equity  # no trades possible


@pytest.mark.asyncio
async def test_backtest_no_strategy():
    engine = BacktestEngine([])
    klines = _generate_klines(100)
    result = await engine.run(klines, symbol="TEST")
    assert len(result.trades) == 0


# ── Report Tests ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_text_report():
    strategy = MeanReversionStrategy({
        "name": "test_mr",
        "exit": {"stop_loss": 3.0, "take_profit": 5.0},
        "position": {"risk_per_trade": 2.0},
    })
    engine = BacktestEngine([strategy], BacktestConfig(initial_equity=10_000))
    klines = _generate_klines(100)
    result = await engine.run(klines, symbol="TESTUSDT")

    report = generate_text_report(result)
    assert "回测报告" in report
    assert "TESTUSDT" in report
    assert "初始资金" in report


@pytest.mark.asyncio
async def test_json_report():
    strategy = MeanReversionStrategy({
        "name": "test_mr",
        "exit": {"stop_loss": 3.0, "take_profit": 5.0},
        "position": {"risk_per_trade": 2.0},
    })
    engine = BacktestEngine([strategy], BacktestConfig(initial_equity=10_000))
    klines = _generate_klines(100)
    result = await engine.run(klines, symbol="TESTUSDT")

    report = generate_json_report(result)
    assert report["symbol"] == "TESTUSDT"
    assert "metrics" in report
    assert "trades" in report
    assert "equity_curve" in report
    assert isinstance(report["return_pct"], float)
