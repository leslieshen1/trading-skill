"""Market data API routes."""

from __future__ import annotations

from fastapi import APIRouter, Query

from src.storage.database import async_session
from src.storage.repo_ticker import TickerRepo
from src.storage.repo_kline import KlineRepo
from src.storage.repo_funding import FundingRateRepo

router = APIRouter()


@router.get("/tickers")
async def get_tickers(
    market: str = Query("futures_um", description="Market type"),
    limit: int = Query(50, le=500),
):
    async with async_session() as session:
        repo = TickerRepo(session)
        tickers = await repo.get_latest(market=market)
        return [
            {
                "symbol": t.symbol,
                "market": t.market,
                "price": t.price,
                "change_24h": t.change_24h,
                "volume_24h": t.volume_24h,
                "quote_volume_24h": t.quote_volume_24h,
                "funding_rate": t.funding_rate,
                "open_interest": t.open_interest,
            }
            for t in tickers[:limit]
        ]


@router.get("/klines/{symbol}")
async def get_klines(
    symbol: str,
    interval: str = Query("1h"),
    market: str = Query("futures_um"),
    limit: int = Query(100, le=1000),
):
    async with async_session() as session:
        repo = KlineRepo(session)
        klines = await repo.get_klines(symbol, interval, market=market, limit=limit)
        return [
            {
                "open_time": k.open_time,
                "open": k.open,
                "high": k.high,
                "low": k.low,
                "close": k.close,
                "volume": k.volume,
                "quote_volume": k.quote_volume,
            }
            for k in klines
        ]


@router.get("/funding/{symbol}")
async def get_funding_rates(symbol: str, limit: int = Query(20, le=100)):
    async with async_session() as session:
        repo = FundingRateRepo(session)
        rates = await repo.get_latest(symbol, limit=limit)
        return [
            {
                "symbol": r.symbol,
                "funding_rate": r.funding_rate,
                "funding_time": r.funding_time,
                "mark_price": r.mark_price,
            }
            for r in rates
        ]
