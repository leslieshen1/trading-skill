"""Tests for technical indicator calculations."""

from __future__ import annotations

import random

from src.strategy.indicators import IndicatorResult, calculate_indicators, klines_to_dataframe


class FakeKline:
    def __init__(self, open_time, o, h, l, c, v):
        self.open_time = open_time
        self.open = o
        self.high = h
        self.low = l
        self.close = c
        self.volume = v


def _generate_klines(n: int = 60, base_price: float = 100.0) -> list[FakeKline]:
    """Generate synthetic kline data with a slight uptrend."""
    klines = []
    price = base_price
    for i in range(n):
        change = random.uniform(-2, 2.5)  # slight bullish bias
        o = price
        c = price + change
        h = max(o, c) + random.uniform(0, 1)
        l = min(o, c) - random.uniform(0, 1)
        v = random.uniform(100, 500)
        klines.append(FakeKline(1700000000000 + i * 3600000, o, h, l, c, v))
        price = c
    return klines


def test_klines_to_dataframe():
    klines = _generate_klines(10)
    df = klines_to_dataframe(klines)
    assert len(df) == 10
    assert list(df.columns) == ["open_time", "open", "high", "low", "close", "volume"]


def test_calculate_indicators_empty():
    result = calculate_indicators([])
    assert isinstance(result, IndicatorResult)
    assert result.rsi_14 is None


def test_calculate_indicators_insufficient_data():
    klines = _generate_klines(5)
    result = calculate_indicators(klines)
    assert result.rsi_14 is None  # Not enough data


def test_calculate_indicators_full():
    random.seed(42)
    klines = _generate_klines(60)
    result = calculate_indicators(klines)

    # RSI should be between 0-100
    assert result.rsi_14 is not None
    assert 0 < result.rsi_14 < 100

    # MACD signal should be one of expected values
    assert result.macd_signal in ("bullish_cross", "bearish_cross", "neutral")

    # EMA trend should be detected
    assert result.ema_trend in ("above", "below", "crossing")

    # ATR should be positive
    assert result.atr_14 is not None
    assert result.atr_14 > 0
    assert result.atr_percent is not None

    # Volume ratio
    assert result.volume_ratio is not None
    assert result.volume_ratio > 0

    # Bollinger bands
    assert result.bollinger_upper is not None
    assert result.bollinger_lower is not None
    assert result.bollinger_upper > result.bollinger_lower
