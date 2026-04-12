"""Tests for strategy base class, built-in strategies, and the loader."""

from __future__ import annotations

import pytest

from src.scanner.screener import CandidateToken
from src.strategy.base import BaseStrategy, Signal, TradeSignal


def _make_candidate(**kwargs) -> CandidateToken:
    defaults = dict(
        symbol="ETHUSDT",
        market="futures_um",
        price=3000.0,
        change_24h=5.0,
        volume_24h=500.0,
        quote_volume_24h=50_000_000.0,
        rsi_14=55.0,
        macd_signal="neutral",
        ema_trend="above",
        volume_ratio=3.0,
        atr_percent=2.5,
        tags=["volume_spike"],
    )
    defaults.update(kwargs)
    return CandidateToken(**defaults)


# ── Base Strategy Tests ──────────────────────────────────────────────────────

def test_check_conditions_all_pass():
    class Dummy(BaseStrategy):
        async def evaluate(self, c, k):
            return None

    s = Dummy({"name": "test"})
    c = _make_candidate()
    conditions = [
        {"indicator": "change_24h", "operator": ">", "value": 3.0},
        {"indicator": "rsi_14", "operator": "between", "value": [40, 70]},
        {"indicator": "volume_ratio", "operator": ">", "value": 2.0},
        {"indicator": "ema_trend", "operator": "==", "value": "above"},
    ]
    assert s.check_conditions(c, conditions) is True


def test_check_conditions_fail():
    class Dummy(BaseStrategy):
        async def evaluate(self, c, k):
            return None

    s = Dummy({"name": "test"})
    c = _make_candidate(rsi_14=80.0)
    conditions = [
        {"indicator": "rsi_14", "operator": "between", "value": [40, 70]},
    ]
    assert s.check_conditions(c, conditions) is False


def test_check_conditions_missing_indicator():
    class Dummy(BaseStrategy):
        async def evaluate(self, c, k):
            return None

    s = Dummy({"name": "test"})
    c = _make_candidate(adx_14=None)
    conditions = [
        {"indicator": "adx_14", "operator": ">", "value": 25},
    ]
    assert s.check_conditions(c, conditions) is False


def test_compute_stop_take_long():
    class Dummy(BaseStrategy):
        async def evaluate(self, c, k):
            return None

    s = Dummy({"name": "test"})
    sl, tp = s.compute_stop_take(100.0, "long", 2.0, 5.0)
    assert sl == 98.0
    assert tp == 105.0


def test_compute_stop_take_short():
    class Dummy(BaseStrategy):
        async def evaluate(self, c, k):
            return None

    s = Dummy({"name": "test"})
    sl, tp = s.compute_stop_take(100.0, "short", 2.0, 5.0)
    assert sl == 102.0
    assert tp == 95.0


# ── Momentum Strategy Tests ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_momentum_triggers():
    from src.strategy.builtin.momentum import MomentumStrategy

    config = {
        "name": "test_momentum",
        "entry": {
            "conditions": [
                {"indicator": "change_24h", "operator": ">", "value": 3.0},
                {"indicator": "rsi_14", "operator": "between", "value": [40, 70]},
                {"indicator": "volume_ratio", "operator": ">", "value": 2.0},
                {"indicator": "ema_trend", "operator": "==", "value": "above"},
            ],
            "direction": "long",
        },
        "exit": {"stop_loss": 2.0, "take_profit": 5.0},
        "position": {"risk_per_trade": 1.0},
    }
    s = MomentumStrategy(config)
    c = _make_candidate()
    signal = await s.evaluate(c, [])
    assert signal is not None
    assert signal.signal == Signal.LONG
    assert signal.confidence > 0.5


@pytest.mark.asyncio
async def test_momentum_no_trigger():
    from src.strategy.builtin.momentum import MomentumStrategy

    config = {
        "name": "test_momentum",
        "entry": {
            "conditions": [
                {"indicator": "change_24h", "operator": ">", "value": 10.0},
            ],
            "direction": "long",
        },
        "exit": {"stop_loss": 2.0, "take_profit": 5.0},
    }
    s = MomentumStrategy(config)
    c = _make_candidate(change_24h=2.0)
    signal = await s.evaluate(c, [])
    assert signal is None


# ── Funding Arb Strategy Tests ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_funding_arb_short():
    from src.strategy.builtin.funding_arb import FundingArbStrategy

    config = {
        "name": "test_funding",
        "entry": {
            "conditions": [
                {"indicator": "funding_rate", "operator": ">", "value": 0.1},
                {"indicator": "rsi_14", "operator": ">", "value": 70},
            ],
            "direction": "short",
            "alt_conditions": [
                {"indicator": "funding_rate", "operator": "<", "value": -0.1},
                {"indicator": "rsi_14", "operator": "<", "value": 30},
            ],
            "alt_direction": "long",
        },
        "exit": {"stop_loss": 1.5, "take_profit": 3.0},
        "position": {"risk_per_trade": 0.5},
    }
    s = FundingArbStrategy(config)
    c = _make_candidate(funding_rate=0.15, rsi_14=75.0)
    signal = await s.evaluate(c, [])
    assert signal is not None
    assert signal.signal == Signal.SHORT


@pytest.mark.asyncio
async def test_funding_arb_long_alt():
    from src.strategy.builtin.funding_arb import FundingArbStrategy

    config = {
        "name": "test_funding",
        "entry": {
            "conditions": [
                {"indicator": "funding_rate", "operator": ">", "value": 0.1},
                {"indicator": "rsi_14", "operator": ">", "value": 70},
            ],
            "direction": "short",
            "alt_conditions": [
                {"indicator": "funding_rate", "operator": "<", "value": -0.1},
                {"indicator": "rsi_14", "operator": "<", "value": 30},
            ],
            "alt_direction": "long",
        },
        "exit": {"stop_loss": 1.5, "take_profit": 3.0},
        "position": {"risk_per_trade": 0.5},
    }
    s = FundingArbStrategy(config)
    c = _make_candidate(funding_rate=-0.15, rsi_14=25.0)
    signal = await s.evaluate(c, [])
    assert signal is not None
    assert signal.signal == Signal.LONG


# ── Mean Reversion Strategy Tests ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mean_reversion_oversold():
    from src.strategy.builtin.mean_reversion import MeanReversionStrategy

    config = {
        "name": "test_mr",
        "exit": {"stop_loss": 2.0, "take_profit": 3.0},
        "position": {"risk_per_trade": 1.0},
    }
    s = MeanReversionStrategy(config)
    c = _make_candidate(rsi_14=22.0, bollinger_pct=-0.1)
    signal = await s.evaluate(c, [])
    assert signal is not None
    assert signal.signal == Signal.LONG


@pytest.mark.asyncio
async def test_mean_reversion_overbought():
    from src.strategy.builtin.mean_reversion import MeanReversionStrategy

    config = {
        "name": "test_mr",
        "exit": {"stop_loss": 2.0, "take_profit": 3.0},
        "position": {"risk_per_trade": 1.0},
    }
    s = MeanReversionStrategy(config)
    c = _make_candidate(rsi_14=78.0, bollinger_pct=1.1)
    signal = await s.evaluate(c, [])
    assert signal is not None
    assert signal.signal == Signal.SHORT


# ── Breakout Strategy Tests ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_breakout_upper():
    from src.strategy.builtin.breakout import BreakoutStrategy

    config = {
        "name": "test_breakout",
        "exit": {"stop_loss": 2.5, "take_profit": 5.0},
        "position": {"risk_per_trade": 1.0},
    }
    s = BreakoutStrategy(config)
    c = _make_candidate(bollinger_pct=1.2, volume_ratio=4.0, adx_14=30.0)
    signal = await s.evaluate(c, [])
    assert signal is not None
    assert signal.signal == Signal.LONG


@pytest.mark.asyncio
async def test_breakout_no_volume():
    from src.strategy.builtin.breakout import BreakoutStrategy

    config = {
        "name": "test_breakout",
        "exit": {"stop_loss": 2.5, "take_profit": 5.0},
    }
    s = BreakoutStrategy(config)
    c = _make_candidate(bollinger_pct=1.2, volume_ratio=1.0)
    signal = await s.evaluate(c, [])
    assert signal is None  # Not enough volume for breakout confirmation


# ── Strategy Loader Tests ────────────────────────────────────────────────────

def test_loader_loads_yaml():
    from src.strategy.loader import load_strategies

    strategies = load_strategies()
    assert len(strategies) >= 2  # momentum + funding_rate examples
    names = [s.name for s in strategies]
    assert "动量突破策略" in names
    assert "资金费率套利" in names


# ── Trade Signal Tests ───────────────────────────────────────────────────────

def test_trade_signal_timestamp():
    s = TradeSignal(
        strategy_name="test",
        symbol="BTCUSDT",
        market="futures_um",
        signal=Signal.LONG,
        confidence=0.8,
        entry_price=50000.0,
        stop_loss=49000.0,
        take_profit=52500.0,
        position_size_pct=1.0,
        reasoning="test signal",
    )
    assert s.timestamp > 0
