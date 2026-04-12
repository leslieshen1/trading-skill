"""Technical indicator calculations.

Uses the `ta` library for standard indicators and raw numpy for custom ones.
All functions accept a list of KlineDB/KlineBar objects and return computed values.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import ta


@dataclass
class IndicatorResult:
    """Computed indicators for a single symbol."""

    rsi_14: float | None = None
    macd_value: float | None = None
    macd_signal_value: float | None = None
    macd_histogram: float | None = None
    macd_signal: str | None = None          # "bullish_cross" / "bearish_cross" / "neutral"
    ema_20: float | None = None
    ema_50: float | None = None
    ema_trend: str | None = None            # "above" / "below" / "crossing"
    bollinger_upper: float | None = None
    bollinger_lower: float | None = None
    bollinger_mid: float | None = None
    bollinger_pct: float | None = None      # %B — where price is in the band
    atr_14: float | None = None
    atr_percent: float | None = None        # ATR / price * 100
    volume_sma_20: float | None = None
    volume_ratio: float | None = None       # current volume / avg volume
    adx_14: float | None = None
    stoch_k: float | None = None
    stoch_d: float | None = None


def klines_to_dataframe(klines: list) -> pd.DataFrame:
    """Convert a list of kline objects to a pandas DataFrame."""
    if not klines:
        return pd.DataFrame()

    rows = []
    for k in klines:
        rows.append({
            "open_time": getattr(k, "open_time", 0),
            "open": float(getattr(k, "open", 0)),
            "high": float(getattr(k, "high", 0)),
            "low": float(getattr(k, "low", 0)),
            "close": float(getattr(k, "close", 0)),
            "volume": float(getattr(k, "volume", 0)),
        })

    df = pd.DataFrame(rows)
    df = df.sort_values("open_time").reset_index(drop=True)
    return df


def calculate_indicators(klines: list) -> IndicatorResult:
    """Calculate all technical indicators from kline data.

    Requires at least 50 bars for meaningful results.
    """
    df = klines_to_dataframe(klines)
    if len(df) < 14:
        return IndicatorResult()

    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]
    result = IndicatorResult()

    # ── RSI ──────────────────────────────────────────────────────────────
    rsi_series = ta.momentum.rsi(close, window=14)
    result.rsi_14 = _last_valid(rsi_series)

    # ── MACD ─────────────────────────────────────────────────────────────
    macd_indicator = ta.trend.MACD(close, window_slow=26, window_fast=12, window_sign=9)
    macd_line = macd_indicator.macd()
    signal_line = macd_indicator.macd_signal()
    histogram = macd_indicator.macd_diff()

    result.macd_value = _last_valid(macd_line)
    result.macd_signal_value = _last_valid(signal_line)
    result.macd_histogram = _last_valid(histogram)

    if len(histogram.dropna()) >= 2:
        prev_hist = histogram.dropna().iloc[-2]
        curr_hist = histogram.dropna().iloc[-1]
        if prev_hist <= 0 < curr_hist:
            result.macd_signal = "bullish_cross"
        elif prev_hist >= 0 > curr_hist:
            result.macd_signal = "bearish_cross"
        else:
            result.macd_signal = "neutral"

    # ── EMA ──────────────────────────────────────────────────────────────
    ema_20 = ta.trend.ema_indicator(close, window=20)
    ema_50 = ta.trend.ema_indicator(close, window=50)
    result.ema_20 = _last_valid(ema_20)
    result.ema_50 = _last_valid(ema_50)

    current_price = close.iloc[-1]
    if result.ema_20 is not None:
        if current_price > result.ema_20:
            result.ema_trend = "above"
        elif current_price < result.ema_20:
            result.ema_trend = "below"
        else:
            result.ema_trend = "crossing"

    # ── Bollinger Bands ──────────────────────────────────────────────────
    bb = ta.volatility.BollingerBands(close, window=20, window_dev=2)
    result.bollinger_upper = _last_valid(bb.bollinger_hband())
    result.bollinger_lower = _last_valid(bb.bollinger_lband())
    result.bollinger_mid = _last_valid(bb.bollinger_mavg())
    result.bollinger_pct = _last_valid(bb.bollinger_pband())

    # ── ATR ──────────────────────────────────────────────────────────────
    atr_series = ta.volatility.average_true_range(high, low, close, window=14)
    result.atr_14 = _last_valid(atr_series)
    if result.atr_14 is not None and current_price > 0:
        result.atr_percent = round(result.atr_14 / current_price * 100, 4)

    # ── Volume ───────────────────────────────────────────────────────────
    vol_sma = volume.rolling(window=20).mean()
    result.volume_sma_20 = _last_valid(vol_sma)
    current_vol = volume.iloc[-1]
    if result.volume_sma_20 and result.volume_sma_20 > 0:
        result.volume_ratio = round(current_vol / result.volume_sma_20, 2)

    # ── ADX ──────────────────────────────────────────────────────────────
    if len(df) >= 28:
        adx_series = ta.trend.adx(high, low, close, window=14)
        result.adx_14 = _last_valid(adx_series)

    # ── Stochastic ───────────────────────────────────────────────────────
    stoch = ta.momentum.StochasticOscillator(high, low, close, window=14, smooth_window=3)
    result.stoch_k = _last_valid(stoch.stoch())
    result.stoch_d = _last_valid(stoch.stoch_signal())

    return result


def _last_valid(series: pd.Series) -> float | None:
    """Get the last non-NaN value from a pandas Series."""
    if series is None or series.empty:
        return None
    valid = series.dropna()
    if valid.empty:
        return None
    return round(float(valid.iloc[-1]), 6)
