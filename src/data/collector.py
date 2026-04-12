"""Data collection scheduler — orchestrates all Binance data fetching.

Collection strategy:
  1. Full ticker snapshot:  every TICKER_INTERVAL seconds (default 10)
  2. Kline data:            every minute for candidate symbols
  3. Funding rates:         every hour
  4. WebSocket streams:     real-time ticker + kline for active symbols
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config.settings import settings
from src.data.binance_coinm import BinanceCoinMClient
from src.data.binance_futures import BinanceFuturesClient
from src.data.binance_spot import BinanceSpotClient
from src.data.binance_futures import FundingRateRecord
from src.data.models import Market, TickerSnapshot
from src.data.websocket_stream import WebSocketManager
from src.storage.database import async_session
from src.storage.repo_funding import FundingRateRepo
from src.storage.repo_kline import KlineRepo
from src.storage.repo_ticker import TickerRepo

logger = structlog.get_logger()


class DataCollector:
    """Central data-collection orchestrator."""

    def __init__(self):
        self.spot_client = BinanceSpotClient()
        self.futures_client = BinanceFuturesClient()
        self.coinm_client = BinanceCoinMClient()
        self.ws_manager = WebSocketManager()
        self._scheduler: AsyncIOScheduler | None = None
        self._candidate_symbols: list[str] = []

    async def start(self) -> None:
        """Start all collection tasks."""
        logger.info("collector_starting")

        # 1) Initial full pull
        await self.fetch_all_tickers()

        # 2) Scheduled tasks
        self._scheduler = AsyncIOScheduler()
        self._scheduler.add_job(
            self.fetch_all_tickers,
            "interval",
            seconds=settings.ticker_interval,
            id="tickers",
        )
        self._scheduler.add_job(
            self.fetch_funding_rates,
            "interval",
            hours=1,
            id="funding_rates",
        )
        self._scheduler.add_job(
            self.fetch_klines_batch,
            "interval",
            minutes=1,
            id="klines",
        )
        self._scheduler.start()
        logger.info("collector_scheduler_started")

        # 3) WebSocket real-time streams
        await self.ws_manager.start()
        self.ws_manager.subscribe_futures_tickers(self._on_ws_ticker)
        logger.info("collector_ws_started")

    async def stop(self) -> None:
        """Graceful shutdown."""
        if self._scheduler:
            self._scheduler.shutdown(wait=False)
        await self.ws_manager.stop()
        await asyncio.gather(
            self.spot_client.close(),
            self.futures_client.close(),
            self.coinm_client.close(),
        )
        logger.info("collector_stopped")

    # ── Scheduled Jobs ───────────────────────────────────────────────────

    async def fetch_all_tickers(self) -> None:
        """Concurrently fetch tickers from all three markets and persist."""
        try:
            spot, futures, coinm = await asyncio.gather(
                self.spot_client.get_all_tickers(),
                self.futures_client.get_all_tickers(),
                self.coinm_client.get_all_tickers(),
                return_exceptions=True,
            )

            all_tickers: list[TickerSnapshot] = []
            for label, result in [("spot", spot), ("futures_um", futures), ("futures_cm", coinm)]:
                if isinstance(result, Exception):
                    logger.error("ticker_fetch_failed", market=label, error=str(result))
                else:
                    all_tickers.extend(result)

            if all_tickers:
                async with async_session() as session:
                    repo = TickerRepo(session)
                    count = await repo.bulk_upsert(all_tickers)
                    logger.info("tickers_persisted", count=count)
        except Exception as e:
            logger.error("fetch_all_tickers_error", error=str(e))

    async def fetch_funding_rates(self) -> None:
        """Fetch funding rates for top futures symbols."""
        try:
            # Fetch from USDT-M futures (most liquid)
            records = await self.futures_client.get_funding_rates(limit=1000)
            if records:
                async with async_session() as session:
                    repo = FundingRateRepo(session)
                    count = await repo.bulk_insert(records)
                    logger.info("funding_rates_persisted", count=count)
        except Exception as e:
            logger.error("fetch_funding_rates_error", error=str(e))

    async def fetch_klines_batch(
        self,
        symbols: list[str] | None = None,
        interval: str = "1h",
    ) -> None:
        """Batch-fetch klines for candidate symbols with rate limiting."""
        if symbols is None:
            symbols = await self._get_candidate_symbols()
        if not symbols:
            return

        semaphore = asyncio.Semaphore(10)  # Binance rate-limit safety

        async def fetch_one(sym: str):
            async with semaphore:
                try:
                    return await self.futures_client.get_klines(sym, interval, limit=100)
                except Exception as e:
                    logger.warning("kline_fetch_failed", symbol=sym, error=str(e))
                    return []

        results = await asyncio.gather(*[fetch_one(s) for s in symbols])

        all_bars = []
        for bars in results:
            all_bars.extend(bars)

        if all_bars:
            async with async_session() as session:
                repo = KlineRepo(session)
                count = await repo.bulk_insert(all_bars)
                logger.info("klines_persisted", count=count, symbols=len(symbols))

    # ── Candidate Management ─────────────────────────────────────────────

    async def _get_candidate_symbols(self) -> list[str]:
        """Get top-volume USDT-M futures symbols for kline fetching."""
        if self._candidate_symbols:
            return self._candidate_symbols

        async with async_session() as session:
            repo = TickerRepo(session)
            tickers = await repo.get_latest(market="futures_um")
            # Top 50 by quote volume
            self._candidate_symbols = [
                t.symbol for t in tickers[:50]
                if t.quote_volume_24h and t.quote_volume_24h > 1_000_000
            ]
        return self._candidate_symbols

    def set_candidate_symbols(self, symbols: list[str]) -> None:
        """Externally update the candidate list (e.g. from Screener)."""
        self._candidate_symbols = symbols
        logger.info("candidates_updated", count=len(symbols))

    # ── WebSocket Callbacks ──────────────────────────────────────────────

    async def _on_ws_ticker(self, data: dict[str, Any]) -> None:
        """Handle real-time ticker updates from WebSocket."""
        # The !ticker@arr stream sends an array of ticker objects
        if isinstance(data, list):
            tickers = []
            for item in data:
                try:
                    tickers.append(
                        TickerSnapshot(
                            symbol=item["s"],
                            market=Market.FUTURES_UM,
                            price=float(item["c"]),
                            change_24h=float(item["P"]),
                            volume_24h=float(item["v"]),
                            quote_volume_24h=float(item["q"]),
                            high_24h=float(item["h"]),
                            low_24h=float(item["l"]),
                            trade_count=int(item["n"]),
                        )
                    )
                except (KeyError, ValueError):
                    continue

            if tickers:
                async with async_session() as session:
                    repo = TickerRepo(session)
                    await repo.bulk_upsert(tickers)
