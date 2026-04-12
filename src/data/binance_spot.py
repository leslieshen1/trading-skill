"""Binance Spot market data collector.

Key Endpoints:
  GET /api/v3/ticker/24hr        — 24h ticker for all symbols
  GET /api/v3/klines             — Kline/candlestick data
  GET /api/v3/exchangeInfo       — Trading rules & symbol list
"""

from __future__ import annotations

import structlog
import httpx

from config.settings import settings
from src.data.models import KlineBar, Market, TickerSnapshot

logger = structlog.get_logger()


class BinanceSpotClient:
    def __init__(self):
        self.base_url = settings.binance_spot_base
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=30.0,
                headers={"X-MBX-APIKEY": settings.binance_api_key},
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def get_exchange_info(self) -> dict:
        client = await self._get_client()
        resp = await client.get("/api/v3/exchangeInfo")
        resp.raise_for_status()
        return resp.json()

    async def get_all_tickers(self) -> list[TickerSnapshot]:
        """Fetch 24h tickers for all spot symbols."""
        client = await self._get_client()
        resp = await client.get("/api/v3/ticker/24hr")
        resp.raise_for_status()
        data = resp.json()

        tickers: list[TickerSnapshot] = []
        for item in data:
            try:
                tickers.append(
                    TickerSnapshot(
                        symbol=item["symbol"],
                        market=Market.SPOT,
                        price=float(item["lastPrice"]),
                        change_24h=float(item["priceChangePercent"]),
                        volume_24h=float(item["volume"]),
                        quote_volume_24h=float(item["quoteVolume"]),
                        high_24h=float(item["highPrice"]),
                        low_24h=float(item["lowPrice"]),
                        trade_count=int(item["count"]),
                    )
                )
            except (KeyError, ValueError) as e:
                logger.warning("spot_ticker_parse_error", symbol=item.get("symbol"), error=str(e))
        logger.info("spot_tickers_fetched", count=len(tickers))
        return tickers

    async def get_klines(
        self, symbol: str, interval: str = "1h", limit: int = 100
    ) -> list[KlineBar]:
        """Fetch klines for a single symbol."""
        client = await self._get_client()
        resp = await client.get(
            "/api/v3/klines",
            params={"symbol": symbol, "interval": interval, "limit": limit},
        )
        resp.raise_for_status()
        data = resp.json()

        return [
            KlineBar(
                symbol=symbol,
                market=Market.SPOT,
                interval=interval,
                open_time=int(k[0]),
                open=float(k[1]),
                high=float(k[2]),
                low=float(k[3]),
                close=float(k[4]),
                volume=float(k[5]),
                close_time=int(k[6]),
                quote_volume=float(k[7]),
                trade_count=int(k[8]),
            )
            for k in data
        ]
