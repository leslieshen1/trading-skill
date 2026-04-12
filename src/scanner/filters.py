"""Screener filter definitions."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ScreenerConfig:
    """Configuration for the market screener."""

    min_quote_volume: float = 1_000_000       # Minimum 24h quote volume (USDT)
    min_change: float = -100.0                # Min 24h change %
    max_change: float = 100.0                 # Max 24h change %
    funding_rate_threshold: float = 0.05      # Absolute funding rate threshold %
    volume_spike_multiplier: float = 3.0      # Volume spike detection multiplier
    markets: list[str] = field(default_factory=lambda: ["futures_um"])
    quote_assets: list[str] = field(default_factory=lambda: ["USDT"])
    exclude_symbols: list[str] = field(default_factory=list)
    only_perpetual: bool = True
    min_trade_count: int = 0                  # Minimum 24h trade count
    max_candidates: int = 50                  # Max candidates to return
