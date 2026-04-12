"""Tests for the AI decision layer — uses mocks instead of real API calls."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.ai.analyst import AIAnalyst, _parse_json_response, _fallback_response
from src.ai.decision import DecisionMaker, FinalDecision, RiskCheckResult
from src.ai.memory import TradingMemory
from src.ai.prompts import format_klines_for_prompt
from src.scanner.screener import CandidateToken
from src.strategy.base import Signal, TradeSignal


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_candidate(**kwargs) -> CandidateToken:
    defaults = dict(
        symbol="BTCUSDT",
        market="futures_um",
        price=50000.0,
        change_24h=3.5,
        volume_24h=1000.0,
        quote_volume_24h=80_000_000.0,
        rsi_14=55.0,
        macd_signal="neutral",
        ema_trend="above",
        volume_ratio=2.5,
        atr_percent=2.8,
        funding_rate=0.01,
        tags=["volume_spike"],
    )
    defaults.update(kwargs)
    return CandidateToken(**defaults)


def _make_signal(**kwargs) -> TradeSignal:
    defaults = dict(
        strategy_name="test_momentum",
        symbol="BTCUSDT",
        market="futures_um",
        signal=Signal.LONG,
        confidence=0.7,
        entry_price=50000.0,
        stop_loss=49000.0,
        take_profit=52500.0,
        position_size_pct=1.0,
        reasoning="Momentum long triggered",
        tags=["volume_spike"],
    )
    defaults.update(kwargs)
    return TradeSignal(**defaults)


# ── JSON Parsing Tests ───────────────────────────────────────────────────────

def test_parse_json_clean():
    raw = '{"approve": true, "confidence": 0.8, "reasoning": "looks good"}'
    result = _parse_json_response(raw)
    assert result["approve"] is True
    assert result["confidence"] == 0.8


def test_parse_json_in_code_block():
    raw = '```json\n{"approve": false, "confidence": 0.3, "reasoning": "risky"}\n```'
    result = _parse_json_response(raw)
    assert result["approve"] is False


def test_parse_json_with_surrounding_text():
    raw = 'Here is my analysis:\n{"approve": true, "confidence": 0.9, "reasoning": "strong"}\nDone.'
    result = _parse_json_response(raw)
    assert result["approve"] is True


def test_parse_json_invalid():
    raw = "This is not JSON at all"
    result = _parse_json_response(raw)
    assert result["approve"] is False


# ── Fallback Response Tests ──────────────────────────────────────────────────

def test_fallback_high_confidence():
    signal = _make_signal(confidence=0.8)
    result = _fallback_response(signal)
    assert result["approve"] is True
    assert abs(result["confidence"] - 0.64) < 1e-9  # 0.8 * 0.8


def test_fallback_low_confidence():
    signal = _make_signal(confidence=0.5)
    result = _fallback_response(signal)
    assert result["approve"] is False


# ── Prompt Formatting Tests ──────────────────────────────────────────────────

class FakeKline:
    def __init__(self, ot, o, h, l, c, v):
        self.open_time = ot
        self.open = o
        self.high = h
        self.low = l
        self.close = c
        self.volume = v


def test_format_klines_empty():
    assert format_klines_for_prompt([]) == "无K线数据"


def test_format_klines():
    klines = [FakeKline(1700000000000, 50000, 50100, 49900, 50050, 100)]
    result = format_klines_for_prompt(klines)
    assert "50000.00" in result
    assert "---|---|---|---|---|---" in result


# ── Decision Maker Tests ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_decision_no_ai():
    """Decision without AI — just passes through the signal."""
    ai_analyst = MagicMock(spec=AIAnalyst)
    trade_repo_mock = MagicMock()
    trade_repo_mock.get_recent_closed = AsyncMock(return_value=[])
    trade_repo_mock.get_open_trades = AsyncMock(return_value=[])
    memory = TradingMemory(trade_repo_mock)

    maker = DecisionMaker(
        ai_analyst=ai_analyst,
        trading_memory=memory,
        strategy_configs={},  # no AI config → AI not enabled
    )

    signal = _make_signal()
    candidate = _make_candidate()
    decision = await maker.make_decision(signal, candidate, [])

    assert decision.execute is True
    assert decision.signal is not None
    assert decision.reason == "策略+风控 通过（AI未启用）"


@pytest.mark.asyncio
async def test_decision_ai_approves():
    """Decision with AI approval."""
    ai_analyst = MagicMock(spec=AIAnalyst)
    ai_analyst.analyze_trade = AsyncMock(return_value={
        "approve": True,
        "confidence": 0.85,
        "adjusted_entry": None,
        "adjusted_stop_loss": None,
        "adjusted_take_profit": None,
        "position_size_suggestion": "keep",
        "risk_notes": "",
        "reasoning": "Strong setup",
    })

    trade_repo_mock = MagicMock()
    trade_repo_mock.get_recent_closed = AsyncMock(return_value=[])
    trade_repo_mock.get_open_trades = AsyncMock(return_value=[])
    memory = TradingMemory(trade_repo_mock)

    maker = DecisionMaker(
        ai_analyst=ai_analyst,
        trading_memory=memory,
        strategy_configs={
            "test_momentum": {"ai": {"enabled": True, "confirm_entry": True, "analysis_depth": "standard"}},
        },
    )

    signal = _make_signal()
    candidate = _make_candidate()
    decision = await maker.make_decision(signal, candidate, [])

    assert decision.execute is True
    assert decision.ai_analysis is not None
    assert decision.ai_analysis["approve"] is True


@pytest.mark.asyncio
async def test_decision_ai_rejects():
    """Decision with AI rejection."""
    ai_analyst = MagicMock(spec=AIAnalyst)
    ai_analyst.analyze_trade = AsyncMock(return_value={
        "approve": False,
        "confidence": 0.3,
        "reasoning": "Bearish divergence detected",
    })

    trade_repo_mock = MagicMock()
    trade_repo_mock.get_recent_closed = AsyncMock(return_value=[])
    trade_repo_mock.get_open_trades = AsyncMock(return_value=[])
    memory = TradingMemory(trade_repo_mock)

    maker = DecisionMaker(
        ai_analyst=ai_analyst,
        trading_memory=memory,
        strategy_configs={
            "test_momentum": {"ai": {"enabled": True, "confirm_entry": True}},
        },
    )

    signal = _make_signal(confidence=0.7)
    candidate = _make_candidate()
    decision = await maker.make_decision(signal, candidate, [])

    assert decision.execute is False
    assert "AI拒绝" in decision.reason


@pytest.mark.asyncio
async def test_decision_ai_reject_override_high_confidence():
    """AI rejected but strategy confidence >= 0.9 forces override."""
    ai_analyst = MagicMock(spec=AIAnalyst)
    ai_analyst.analyze_trade = AsyncMock(return_value={
        "approve": False,
        "confidence": 0.4,
        "reasoning": "Slightly risky",
    })

    trade_repo_mock = MagicMock()
    trade_repo_mock.get_recent_closed = AsyncMock(return_value=[])
    trade_repo_mock.get_open_trades = AsyncMock(return_value=[])
    memory = TradingMemory(trade_repo_mock)

    maker = DecisionMaker(
        ai_analyst=ai_analyst,
        trading_memory=memory,
        strategy_configs={
            "test_momentum": {"ai": {"enabled": True, "confirm_entry": True}},
        },
    )

    signal = _make_signal(confidence=0.95)
    candidate = _make_candidate()
    decision = await maker.make_decision(signal, candidate, [])

    # High confidence overrides AI rejection
    assert decision.execute is True


@pytest.mark.asyncio
async def test_decision_risk_blocks():
    """Risk manager blocks the trade."""
    ai_analyst = MagicMock(spec=AIAnalyst)
    trade_repo_mock = MagicMock()
    trade_repo_mock.get_recent_closed = AsyncMock(return_value=[])
    trade_repo_mock.get_open_trades = AsyncMock(return_value=[])
    memory = TradingMemory(trade_repo_mock)

    maker = DecisionMaker(
        ai_analyst=ai_analyst,
        trading_memory=memory,
        strategy_configs={},
    )

    # Mock risk manager
    risk_manager = MagicMock()
    risk_manager.pre_check = AsyncMock(
        return_value=RiskCheckResult(passed=False, reason="日亏损超限")
    )
    maker.set_risk_manager(risk_manager)

    signal = _make_signal()
    candidate = _make_candidate()
    decision = await maker.make_decision(signal, candidate, [])

    assert decision.execute is False
    assert "风控拒绝" in decision.reason


@pytest.mark.asyncio
async def test_decision_merge_signal_adjustments():
    """AI adjusts entry/stop/take-profit prices."""
    ai_analyst = MagicMock(spec=AIAnalyst)
    ai_analyst.analyze_trade = AsyncMock(return_value={
        "approve": True,
        "confidence": 0.9,
        "adjusted_entry": 49800.0,
        "adjusted_stop_loss": 48500.0,
        "adjusted_take_profit": 53000.0,
        "position_size_suggestion": "decrease",
        "reasoning": "Adjusted for better risk/reward",
    })

    trade_repo_mock = MagicMock()
    trade_repo_mock.get_recent_closed = AsyncMock(return_value=[])
    trade_repo_mock.get_open_trades = AsyncMock(return_value=[])
    memory = TradingMemory(trade_repo_mock)

    maker = DecisionMaker(
        ai_analyst=ai_analyst,
        trading_memory=memory,
        strategy_configs={
            "test_momentum": {"ai": {"enabled": True, "confirm_entry": True}},
        },
    )

    signal = _make_signal(position_size_pct=2.0)
    candidate = _make_candidate()
    decision = await maker.make_decision(signal, candidate, [])

    assert decision.execute is True
    assert decision.signal.entry_price == 49800.0
    assert decision.signal.stop_loss == 48500.0
    assert decision.signal.take_profit == 53000.0
    assert decision.signal.position_size_pct == 1.0  # 2.0 * 0.5 = 1.0 (decreased)
    assert decision.signal.confidence == 0.9


# ── Trading Memory Tests ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_memory_empty():
    trade_repo_mock = MagicMock()
    trade_repo_mock.get_recent_closed = AsyncMock(return_value=[])
    trade_repo_mock.get_open_trades = AsyncMock(return_value=[])
    memory = TradingMemory(trade_repo_mock)
    result = await memory.get_recent_context()
    assert "无历史交易记录" in result


@pytest.mark.asyncio
async def test_memory_with_trades():
    mock_trade = MagicMock()
    mock_trade.symbol = "BTCUSDT"
    mock_trade.signal = "long"
    mock_trade.strategy_name = "momentum"
    mock_trade.entry_price = 50000.0
    mock_trade.exit_price = 51000.0
    mock_trade.stop_loss = 49000.0
    mock_trade.take_profit = 52000.0
    mock_trade.pnl = 200.0
    mock_trade.status = "closed"

    trade_repo_mock = MagicMock()
    trade_repo_mock.get_recent_closed = AsyncMock(return_value=[mock_trade])
    trade_repo_mock.get_open_trades = AsyncMock(return_value=[])
    memory = TradingMemory(trade_repo_mock)

    result = await memory.get_recent_context()
    assert "最近平仓记录" in result
    assert "BTCUSDT" in result


@pytest.mark.asyncio
async def test_performance_summary_empty():
    trade_repo_mock = MagicMock()
    trade_repo_mock.get_today_trades = AsyncMock(return_value=[])
    trade_repo_mock.get_recent_closed = AsyncMock(return_value=[])
    memory = TradingMemory(trade_repo_mock)
    result = await memory.get_performance_summary()
    assert "无交易记录" in result
