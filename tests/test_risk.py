"""Tests for risk management — risk manager, position sizer, stop loss, circuit breaker."""

from __future__ import annotations

import pytest

from src.risk.circuit_breaker import BreakerLevel, CircuitBreaker
from src.risk.position_sizer import PositionSizer
from src.risk.risk_manager import RiskCheckResult, RiskManager
from src.risk.stop_loss import StopLossManager
from src.strategy.base import Signal, TradeSignal


def _make_signal(**kwargs) -> TradeSignal:
    defaults = dict(
        strategy_name="test",
        symbol="BTCUSDT",
        market="futures_um",
        signal=Signal.LONG,
        confidence=0.7,
        entry_price=50000.0,
        stop_loss=49000.0,
        take_profit=52500.0,
        position_size_pct=1.0,
        reasoning="test",
    )
    defaults.update(kwargs)
    return TradeSignal(**defaults)


# ── Risk Manager Tests ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_risk_passes_normal():
    rm = RiskManager()
    rm.update_equity(100_000)
    signal = _make_signal()
    result = await rm.pre_check(signal)
    assert result.passed


@pytest.mark.asyncio
async def test_risk_blocks_daily_loss():
    rm = RiskManager({"max_daily_loss_pct": 5.0})
    rm.update_equity(100_000)
    rm.record_trade_result(-5500)  # > 5%
    signal = _make_signal()
    result = await rm.pre_check(signal)
    assert not result.passed
    assert "日亏损" in result.reason


@pytest.mark.asyncio
async def test_risk_blocks_consecutive_losses():
    rm = RiskManager({"max_consecutive_losses": 3})
    rm.update_equity(100_000)
    rm.record_trade_result(-100)
    rm.record_trade_result(-100)
    rm.record_trade_result(-100)
    signal = _make_signal()
    result = await rm.pre_check(signal)
    assert not result.passed
    assert "连续亏损" in result.reason


@pytest.mark.asyncio
async def test_risk_resets_consecutive_on_win():
    rm = RiskManager({"max_consecutive_losses": 3})
    rm.update_equity(100_000)
    rm.record_trade_result(-100)
    rm.record_trade_result(-100)
    rm.record_trade_result(200)  # Win resets counter
    rm.record_trade_result(-100)
    signal = _make_signal()
    result = await rm.pre_check(signal)
    assert result.passed


@pytest.mark.asyncio
async def test_risk_blocks_daily_trade_count():
    rm = RiskManager({"max_daily_trades": 2})
    rm.update_equity(100_000)
    rm.record_trade_result(50)
    rm.record_trade_result(50)
    signal = _make_signal()
    result = await rm.pre_check(signal)
    assert not result.passed
    assert "日交易次数" in result.reason


@pytest.mark.asyncio
async def test_risk_blocks_max_loss_per_trade():
    rm = RiskManager({"max_loss_per_trade_pct": 2.0})
    rm.update_equity(10_000)
    # Stop loss is 2% away, position is 100% of equity → loss would be 2% of 10k = 200
    # But position_size_pct=1.0 means 1% of equity=100, and 2% of 100 = 2
    # So this should pass. Let's make a scenario that fails:
    signal = _make_signal(
        entry_price=50000, stop_loss=45000, position_size_pct=5.0
    )
    # position_value = 5% * 10000 = 500
    # loss_pct = (50000-45000)/50000 = 10%
    # potential_loss = 500 * 10% = 50
    # max_allowed = 10000 * 2% = 200
    # 50 < 200 → passes. Let's make it bigger.
    signal = _make_signal(
        entry_price=50000, stop_loss=25000, position_size_pct=10.0
    )
    # position_value = 10% * 10000 = 1000
    # loss_pct = (50000-25000)/50000 = 50%
    # potential_loss = 1000 * 50% = 500
    # max_allowed = 10000 * 2% = 200
    result = await rm.pre_check(signal)
    assert not result.passed
    assert "单笔潜在亏损" in result.reason


@pytest.mark.asyncio
async def test_risk_halt_and_reset():
    rm = RiskManager({"max_daily_loss_pct": 5.0})
    rm.update_equity(100_000)
    rm.record_trade_result(-6000)
    assert rm.is_halted
    rm.reset_halt()
    assert not rm.is_halted


# ── Position Sizer Tests ────────────────────────────────────────────────────

def test_sizer_fixed_percent():
    sizer = PositionSizer(total_equity=100_000, max_position_pct=50.0)
    result = sizer.calculate("fixed_percent", entry_price=50000, stop_loss=49000, risk_per_trade_pct=1.0)
    # risk = 1% of 100k = 1000, stop distance = 1000, qty = 1000/1000 = 1
    assert result.quantity == 1.0
    assert result.risk_amount == 1000.0
    assert result.notional_value == 50000.0


def test_sizer_fixed_percent_capped():
    sizer = PositionSizer(total_equity=10_000, max_position_pct=5.0)
    # If calculated position exceeds max, it should be capped
    result = sizer.calculate("fixed_percent", entry_price=100, stop_loss=99, risk_per_trade_pct=10.0)
    # risk = 10% of 10k = 1000, stop = 1, qty = 1000, notional = 100k
    # but max = 5% of 10k = 500, so qty = 500/100 = 5
    assert result.position_pct <= 5.0
    assert result.notional_value <= 500.0


def test_sizer_kelly_no_data():
    sizer = PositionSizer(total_equity=100_000)
    # Without win_rate data, should fall back to conservative
    result = sizer.calculate("kelly", entry_price=50000, stop_loss=49000)
    assert result.quantity > 0


def test_sizer_kelly_with_data():
    sizer = PositionSizer(total_equity=100_000)
    result = sizer.calculate(
        "kelly", entry_price=50000, stop_loss=49000,
        win_rate=0.6, avg_win=2000, avg_loss=1000
    )
    assert result.quantity > 0


def test_sizer_atr_based():
    sizer = PositionSizer(total_equity=100_000)
    result = sizer.calculate("atr_based", entry_price=50000, stop_loss=49000, atr=500)
    # stop_distance = 500*2 = 1000, risk = 1% of 100k = 1000, qty = 1
    assert result.quantity > 0


# ── Stop Loss Tests ──────────────────────────────────────────────────────────

def test_stop_loss_fixed_long():
    mgr = StopLossManager()
    state = mgr.create_stop("BTCUSDT", "long", 50000, stop_pct=2.0)
    assert state.current_stop == 49000.0
    assert state.stop_type == "fixed"

    # Price goes up — fixed stop doesn't move
    state = mgr.update(state, 52000)
    assert state.current_stop == 49000.0

    # Check trigger
    assert not mgr.check_triggered(state, 50000)
    assert mgr.check_triggered(state, 48999)


def test_stop_loss_trailing_long():
    mgr = StopLossManager()
    state = mgr.create_stop("BTCUSDT", "long", 50000, stop_pct=2.0, trailing_pct=1.5)
    assert state.stop_type == "trailing"
    initial_stop = state.current_stop

    # Price moves up → trailing stop should follow
    state = mgr.update(state, 52000, trailing_pct=1.5)
    assert state.current_stop > initial_stop
    assert state.highest_price == 52000

    # Price moves down — trailing stop stays
    old_stop = state.current_stop
    state = mgr.update(state, 51500, trailing_pct=1.5)
    assert state.current_stop == old_stop


def test_stop_loss_short():
    mgr = StopLossManager()
    state = mgr.create_stop("ETHUSDT", "short", 3000, stop_pct=2.0)
    assert state.current_stop == 3060.0  # 3000 + 2%

    assert not mgr.check_triggered(state, 2900)
    assert mgr.check_triggered(state, 3100)


def test_stop_loss_atr():
    mgr = StopLossManager()
    state = mgr.create_stop("BTCUSDT", "long", 50000, atr=500, atr_multiplier=2.0)
    assert state.stop_type == "atr"
    assert state.current_stop == 49000.0  # 50000 - 500*2


# ── Circuit Breaker Tests ────────────────────────────────────────────────────

def test_breaker_normal():
    cb = CircuitBreaker(initial_equity=100_000)
    state = cb.evaluate(daily_pnl=0, total_equity=100_000)
    assert state.level == BreakerLevel.NORMAL
    assert state.allow_new_entry
    assert state.position_size_multiplier == 1.0


def test_breaker_l1_reduce():
    cb = CircuitBreaker(initial_equity=100_000)
    state = cb.evaluate(daily_pnl=-3500, total_equity=100_000)
    assert state.level == BreakerLevel.L1_REDUCE
    assert state.position_size_multiplier == 0.5
    assert state.allow_new_entry


def test_breaker_l2_stop_entry():
    cb = CircuitBreaker(initial_equity=100_000)
    state = cb.evaluate(daily_pnl=-5500, total_equity=100_000)
    assert state.level == BreakerLevel.L2_STOP_ENTRY
    assert not state.allow_new_entry
    assert not state.close_all


def test_breaker_l3_close_all():
    cb = CircuitBreaker(initial_equity=100_000)
    state = cb.evaluate(daily_pnl=-8500, total_equity=100_000)
    assert state.level == BreakerLevel.L3_CLOSE_ALL
    assert state.close_all
    assert not state.shutdown


def test_breaker_l4_shutdown():
    cb = CircuitBreaker(initial_equity=100_000)
    # Total equity dropped by >15%
    state = cb.evaluate(daily_pnl=-1000, total_equity=84_000)
    assert state.level == BreakerLevel.L4_SHUTDOWN
    assert state.shutdown
    assert state.close_all
