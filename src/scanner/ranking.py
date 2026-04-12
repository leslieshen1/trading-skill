"""Scoring and ranking logic for screened candidates."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.scanner.screener import CandidateToken


def score_candidate(c: "CandidateToken") -> float:
    """Compute a composite score for ranking candidates.

    Higher score = more interesting trading opportunity.
    Factors (all normalized to roughly 0-1 range):
      - Volume activity   (volume_ratio)
      - Trend strength    (ADX / 100)
      - Volatility        (atr_percent, moderate is best)
      - Funding anomaly   (|funding_rate|)
      - Tag bonus         (each tag adds weight)
    """
    score = 0.0

    # Volume ratio — capped at 10x
    if c.volume_ratio and c.volume_ratio > 1:
        score += min(c.volume_ratio / 10, 1.0) * 25

    # ATR volatility — sweet spot around 2-5%
    if c.atr_percent is not None:
        if 2.0 <= c.atr_percent <= 5.0:
            score += 20
        elif 1.0 <= c.atr_percent < 2.0 or 5.0 < c.atr_percent <= 8.0:
            score += 10

    # Funding rate anomaly
    if c.funding_rate is not None:
        abs_fr = abs(c.funding_rate)
        if abs_fr > 0.1:
            score += 15
        elif abs_fr > 0.05:
            score += 8

    # Quote volume (liquidity bonus)
    if c.quote_volume_24h > 50_000_000:
        score += 10
    elif c.quote_volume_24h > 10_000_000:
        score += 5

    # RSI extremes
    if c.rsi_14 is not None:
        if c.rsi_14 < 25 or c.rsi_14 > 75:
            score += 10
        elif c.rsi_14 < 30 or c.rsi_14 > 70:
            score += 5

    # Tag bonuses
    tag_weights = {
        "volume_spike": 10,
        "oversold": 8,
        "overbought": 8,
        "funding_negative": 6,
        "funding_positive": 6,
        "macd_golden": 7,
        "macd_death": 7,
    }
    if c.tags:
        for tag in c.tags:
            score += tag_weights.get(tag, 2)

    return round(score, 2)
