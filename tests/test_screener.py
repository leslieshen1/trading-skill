"""Tests for the scanner/screener and ranking logic."""

from __future__ import annotations

from src.scanner.filters import ScreenerConfig
from src.scanner.ranking import score_candidate
from src.scanner.screener import CandidateToken


def _make_candidate(**kwargs) -> CandidateToken:
    defaults = dict(
        symbol="BTCUSDT",
        market="futures_um",
        price=50000.0,
        change_24h=2.5,
        volume_24h=1000.0,
        quote_volume_24h=100_000_000.0,
    )
    defaults.update(kwargs)
    return CandidateToken(**defaults)


def test_candidate_creation():
    c = _make_candidate()
    assert c.symbol == "BTCUSDT"
    assert c.tags == []
    assert c.score == 0.0


def test_score_volume_spike():
    c = _make_candidate(volume_ratio=5.0, tags=["volume_spike"])
    score = score_candidate(c)
    assert score > 0


def test_score_oversold():
    c = _make_candidate(rsi_14=22.0, tags=["oversold"])
    score = score_candidate(c)
    assert score > 0


def test_score_funding_extreme():
    c = _make_candidate(funding_rate=0.15, tags=["funding_positive"])
    score = score_candidate(c)
    assert score > 0


def test_score_ranking_order():
    """Higher quality signals should score higher."""
    c_boring = _make_candidate(
        symbol="BORING",
        quote_volume_24h=2_000_000,
    )
    c_interesting = _make_candidate(
        symbol="HOT",
        volume_ratio=5.0,
        rsi_14=25.0,
        funding_rate=0.12,
        atr_percent=3.5,
        quote_volume_24h=80_000_000,
        tags=["volume_spike", "oversold", "funding_positive"],
    )
    assert score_candidate(c_interesting) > score_candidate(c_boring)


def test_screener_config_defaults():
    cfg = ScreenerConfig()
    assert cfg.min_quote_volume == 1_000_000
    assert cfg.markets == ["futures_um"]
    assert cfg.max_candidates == 50
