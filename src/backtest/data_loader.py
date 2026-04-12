"""Backtest data loader — loads historical klines from DB or Binance API."""

from __future__ import annotations

import asyncio

import structlog

from src.data.binance_futures import BinanceFuturesClient
from src.data.models import KlineBar, Market
from src.storage.database import async_session
from src.storage.repo_kline import KlineRepo

logger = structlog.get_logger()


class BacktestDataLoader:
    """Loads historical data for backtesting."""

    def __init__(self):
        self.futures_client = BinanceFuturesClient()

    async def load_from_db(
        self,
        symbol: str,
        interval: str = "1h",
        market: str = "futures_um",
        limit: int = 1000,
    ) -> list[KlineBar]:
        """Load klines from the local database."""
        async with async_session() as session:
            repo = KlineRepo(session)
            rows = await repo.get_klines(symbol, interval, market=market, limit=limit)
            return [
                KlineBar(
                    symbol=row.symbol,
                    market=Market(row.market),
                    interval=row.interval,
                    open_time=row.open_time,
                    open=row.open,
                    high=row.high,
                    low=row.low,
                    close=row.close,
                    volume=row.volume,
                    close_time=row.close_time,
                    quote_volume=row.quote_volume,
                    trade_count=row.trade_count,
                )
                for row in rows
            ]

    async def load_from_api(
        self,
        symbol: str,
        interval: str = "1h",
        limit: int = 1000,
    ) -> list[KlineBar]:
        """Fetch klines directly from Binance API.

        For limits > 1500, makes multiple requests.
        """
        all_bars: list[KlineBar] = []
        remaining = limit
        end_time = None

        while remaining > 0:
            batch_limit = min(remaining, 1500)
            try:
                bars = await self.futures_client.get_klines(symbol, interval, limit=batch_limit)
                if not bars:
                    break
                all_bars = bars + all_bars  # prepend older data
                remaining -= len(bars)
                if remaining > 0 and bars:
                    end_time = bars[0].open_time - 1
            except Exception as e:
                logger.error("backtest_data_fetch_error", symbol=symbol, error=str(e))
                break

        logger.info("backtest_data_loaded", symbol=symbol, bars=len(all_bars))
        return all_bars

    async def close(self) -> None:
        await self.futures_client.close()
