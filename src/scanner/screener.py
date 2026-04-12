"""Multi-dimension market screener.

Filters the full market data down to a ranked list of trading candidates,
each annotated with technical indicators and feature tags.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import structlog

from src.scanner.filters import ScreenerConfig
from src.scanner.ranking import score_candidate
from src.strategy.indicators import IndicatorResult, calculate_indicators
from src.storage.repo_kline import KlineRepo
from src.storage.repo_ticker import TickerRepo

logger = structlog.get_logger()


@dataclass
class CandidateToken:
    """A screened candidate with computed features."""

    symbol: str
    market: str
    price: float
    change_24h: float
    volume_24h: float
    quote_volume_24h: float
    funding_rate: float | None = None
    open_interest: float | None = None
    # Technical indicators
    rsi_14: float | None = None
    macd_signal: str | None = None
    ema_trend: str | None = None
    volume_ratio: float | None = None
    atr_percent: float | None = None
    adx_14: float | None = None
    bollinger_pct: float | None = None
    # Scoring
    score: float = 0.0
    tags: list[str] = field(default_factory=list)


class MarketScreener:
    """Scans the market and produces a ranked candidate list."""

    def __init__(self, ticker_repo: TickerRepo, kline_repo: KlineRepo, config: ScreenerConfig):
        self.ticker_repo = ticker_repo
        self.kline_repo = kline_repo
        self.config = config

    async def scan(self) -> list[CandidateToken]:
        """Run full scan: filter → compute indicators → tag → score → rank."""

        # 1. Load latest tickers
        all_tickers = []
        for market in self.config.markets:
            tickers = await self.ticker_repo.get_latest(market=market)
            all_tickers.extend(tickers)

        logger.info("screener_loaded_tickers", count=len(all_tickers))

        # 2. Base filters
        filtered = self._apply_base_filters(all_tickers)
        logger.info("screener_after_base_filter", count=len(filtered))

        # 3. Compute indicators & build candidates
        candidates: list[CandidateToken] = []
        for ticker in filtered:
            klines = await self.kline_repo.get_klines(
                ticker.symbol, "1h", market=ticker.market, limit=100
            )
            indicators = calculate_indicators(klines)
            candidate = self._build_candidate(ticker, indicators)
            candidates.append(candidate)

        # 4. Tag features
        for c in candidates:
            c.tags = self._detect_tags(c)

        # 5. Score & rank
        for c in candidates:
            c.score = score_candidate(c)

        candidates.sort(key=lambda x: x.score, reverse=True)
        top = candidates[: self.config.max_candidates]
        logger.info("screener_complete", total=len(candidates), returned=len(top))
        return top

    def _apply_base_filters(self, tickers: list) -> list:
        """Apply volume, change range, and exclusion filters."""
        result = []
        for t in tickers:
            # Volume filter
            if t.quote_volume_24h < self.config.min_quote_volume:
                continue
            # Change range filter
            if not (self.config.min_change <= t.change_24h <= self.config.max_change):
                continue
            # Symbol exclusion
            if t.symbol in self.config.exclude_symbols:
                continue
            # Quote asset filter
            if self.config.quote_assets:
                if not any(t.symbol.endswith(qa) for qa in self.config.quote_assets):
                    continue
            # Trade count filter
            if t.trade_count < self.config.min_trade_count:
                continue
            result.append(t)
        return result

    def _build_candidate(self, ticker, indicators: IndicatorResult) -> CandidateToken:
        return CandidateToken(
            symbol=ticker.symbol,
            market=ticker.market,
            price=ticker.price,
            change_24h=ticker.change_24h,
            volume_24h=ticker.volume_24h,
            quote_volume_24h=ticker.quote_volume_24h,
            funding_rate=ticker.funding_rate,
            open_interest=ticker.open_interest,
            rsi_14=indicators.rsi_14,
            macd_signal=indicators.macd_signal,
            ema_trend=indicators.ema_trend,
            volume_ratio=indicators.volume_ratio,
            atr_percent=indicators.atr_percent,
            adx_14=indicators.adx_14,
            bollinger_pct=indicators.bollinger_pct,
        )

    def _detect_tags(self, c: CandidateToken) -> list[str]:
        """Detect notable feature tags for a candidate."""
        tags: list[str] = []
        cfg = self.config

        if c.volume_ratio and c.volume_ratio > cfg.volume_spike_multiplier:
            tags.append("volume_spike")
        if c.rsi_14 is not None:
            if c.rsi_14 < 30:
                tags.append("oversold")
            elif c.rsi_14 > 70:
                tags.append("overbought")
        if c.funding_rate is not None:
            if c.funding_rate < -cfg.funding_rate_threshold:
                tags.append("funding_negative")
            elif c.funding_rate > cfg.funding_rate_threshold:
                tags.append("funding_positive")
        if c.macd_signal == "bullish_cross":
            tags.append("macd_golden")
        elif c.macd_signal == "bearish_cross":
            tags.append("macd_death")
        if c.bollinger_pct is not None:
            if c.bollinger_pct > 1.0:
                tags.append("bb_breakout_upper")
            elif c.bollinger_pct < 0.0:
                tags.append("bb_breakout_lower")

        return tags
