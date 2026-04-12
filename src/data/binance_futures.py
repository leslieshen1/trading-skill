"""Binance USDT-M Futures data collector.

Key Endpoints:
  GET /fapi/v1/ticker/24hr        — 24h ticker
  GET /fapi/v1/premiumIndex       — Funding rate + mark/index price
  GET /fapi/v1/klines             — Klines
  GET /fapi/v1/depth              — Order book
  GET /fapi/v1/openInterest       — Open interest
  GET /fapi/v1/fundingRate        — Historical funding rate
  GET /fapi/v1/exchangeInfo       — Trading rules

WebSocket Streams (wss://fstream.binance.com/ws):
  <symbol>@kline_<interval>       — Kline stream
  <symbol>@aggTrade               — Aggregated trades
  <symbol>@depth@100ms            — Depth stream
  !ticker@arr                     — All-market ticker
  <symbol>@markPrice@1s           — Mark price stream
"""

from __future__ import annotations

import structlog
import httpx

from config.settings import settings
from src.data.models import FundingRateRecord, KlineBar, Market, TickerSnapshot

logger = structlog.get_logger()


class BinanceFuturesClient:
    def __init__(self):
        self.base_url = settings.binance_futures_base
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
        resp = await client.get("/fapi/v1/exchangeInfo")
        resp.raise_for_status()
        return resp.json()

    async def get_all_tickers(self) -> list[TickerSnapshot]:
        """Fetch 24h tickers for all USDT-M futures."""
        client = await self._get_client()

        # Fetch tickers + premium index (funding rates) concurrently
        resp_ticker = await client.get("/fapi/v1/ticker/24hr")
        resp_ticker.raise_for_status()
        ticker_data = resp_ticker.json()

        resp_premium = await client.get("/fapi/v1/premiumIndex")
        resp_premium.raise_for_status()
        premium_data = resp_premium.json()

        # Build a funding rate lookup
        funding_map: dict[str, dict] = {}
        for p in premium_data:
            funding_map[p["symbol"]] = p

        tickers: list[TickerSnapshot] = []
        for item in ticker_data:
            try:
                sym = item["symbol"]
                premium = funding_map.get(sym, {})
                tickers.append(
                    TickerSnapshot(
                        symbol=sym,
                        market=Market.FUTURES_UM,
                        price=float(item["lastPrice"]),
                        change_24h=float(item["priceChangePercent"]),
                        volume_24h=float(item["volume"]),
                        quote_volume_24h=float(item["quoteVolume"]),
                        high_24h=float(item["highPrice"]),
                        low_24h=float(item["lowPrice"]),
                        trade_count=int(item["count"]),
                        funding_rate=float(premium.get("lastFundingRate", 0)) * 100,
                        mark_price=float(premium.get("markPrice", 0)),
                        index_price=float(premium.get("indexPrice", 0)),
                    )
                )
            except (KeyError, ValueError) as e:
                logger.warning("futures_ticker_parse_error", symbol=item.get("symbol"), error=str(e))
        logger.info("futures_um_tickers_fetched", count=len(tickers))
        return tickers

    async def get_klines(
        self, symbol: str, interval: str = "1h", limit: int = 100
    ) -> list[KlineBar]:
        client = await self._get_client()
        resp = await client.get(
            "/fapi/v1/klines",
            params={"symbol": symbol, "interval": interval, "limit": limit},
        )
        resp.raise_for_status()
        data = resp.json()

        return [
            KlineBar(
                symbol=symbol,
                market=Market.FUTURES_UM,
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

    async def get_funding_rates(
        self, symbol: str | None = None, limit: int = 100
    ) -> list[FundingRateRecord]:
        """Fetch historical funding rates."""
        client = await self._get_client()
        params: dict = {"limit": limit}
        if symbol:
            params["symbol"] = symbol
        resp = await client.get("/fapi/v1/fundingRate", params=params)
        resp.raise_for_status()
        data = resp.json()

        return [
            FundingRateRecord(
                symbol=item["symbol"],
                funding_rate=float(item["fundingRate"]) * 100,
                funding_time=int(item["fundingTime"]),
                mark_price=float(item.get("markPrice", 0)),
            )
            for item in data
        ]

    async def get_open_interest(self, symbol: str) -> float:
        client = await self._get_client()
        resp = await client.get("/fapi/v1/openInterest", params={"symbol": symbol})
        resp.raise_for_status()
        return float(resp.json()["openInterest"])
