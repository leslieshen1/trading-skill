"""Strategy engine — schedules and runs all enabled strategies against candidates."""

from __future__ import annotations

import structlog

from src.scanner.screener import CandidateToken, MarketScreener
from src.strategy.base import BaseStrategy, TradeSignal
from src.storage.repo_kline import KlineRepo

logger = structlog.get_logger()


class StrategyEngine:
    """Runs all loaded strategies against screened candidates."""

    def __init__(
        self,
        strategies: list[BaseStrategy],
        screener: MarketScreener,
        kline_repo: KlineRepo,
    ):
        self.strategies = [s for s in strategies if s.enabled]
        self.screener = screener
        self.kline_repo = kline_repo

    async def run_cycle(self) -> list[TradeSignal]:
        """Execute one full scan-and-evaluate cycle.

        1. Screen market for candidates
        2. For each candidate, run every enabled strategy
        3. Collect and return all generated signals
        """
        candidates = await self.screener.scan()
        if not candidates:
            logger.info("engine_no_candidates")
            return []

        logger.info("engine_evaluating", candidates=len(candidates), strategies=len(self.strategies))

        all_signals: list[TradeSignal] = []

        for candidate in candidates:
            klines = await self.kline_repo.get_klines(
                candidate.symbol, "1h", market=candidate.market, limit=100
            )

            for strategy in self.strategies:
                try:
                    signal = await strategy.evaluate(candidate, klines)
                    if signal is not None:
                        all_signals.append(signal)
                        logger.info(
                            "signal_generated",
                            strategy=signal.strategy_name,
                            symbol=signal.symbol,
                            direction=signal.signal.value,
                            confidence=signal.confidence,
                        )
                except Exception as e:
                    logger.error(
                        "strategy_eval_error",
                        strategy=strategy.name,
                        symbol=candidate.symbol,
                        error=str(e),
                    )

        # Sort by confidence descending
        all_signals.sort(key=lambda s: s.confidence, reverse=True)
        logger.info("engine_cycle_complete", signals=len(all_signals))
        return all_signals
