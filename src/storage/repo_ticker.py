"""CRUD operations for Ticker data."""

from __future__ import annotations

from sqlalchemy import select, delete
from sqlalchemy.dialects.sqlite import insert as sqlite_upsert
from sqlalchemy.ext.asyncio import AsyncSession

from src.data.models import TickerDB, TickerSnapshot


class TickerRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def bulk_upsert(self, tickers: list[TickerSnapshot]) -> int:
        """Insert or update tickers (keyed on symbol+market)."""
        if not tickers:
            return 0

        for ticker in tickers:
            stmt = (
                sqlite_upsert(TickerDB)
                .values(
                    symbol=ticker.symbol,
                    market=ticker.market.value,
                    base_asset=ticker.base_asset,
                    quote_asset=ticker.quote_asset,
                    price=ticker.price,
                    change_24h=ticker.change_24h,
                    volume_24h=ticker.volume_24h,
                    quote_volume_24h=ticker.quote_volume_24h,
                    high_24h=ticker.high_24h,
                    low_24h=ticker.low_24h,
                    trade_count=ticker.trade_count,
                    funding_rate=ticker.funding_rate,
                    mark_price=ticker.mark_price,
                    index_price=ticker.index_price,
                    open_interest=ticker.open_interest,
                    contract_type=ticker.contract_type,
                    timestamp=ticker.timestamp,
                )
                .on_conflict_do_update(
                    index_elements=["symbol", "market"],
                    set_={
                        "price": ticker.price,
                        "change_24h": ticker.change_24h,
                        "volume_24h": ticker.volume_24h,
                        "quote_volume_24h": ticker.quote_volume_24h,
                        "high_24h": ticker.high_24h,
                        "low_24h": ticker.low_24h,
                        "trade_count": ticker.trade_count,
                        "funding_rate": ticker.funding_rate,
                        "mark_price": ticker.mark_price,
                        "index_price": ticker.index_price,
                        "open_interest": ticker.open_interest,
                        "timestamp": ticker.timestamp,
                    },
                )
            )
            await self.session.execute(stmt)

        await self.session.commit()
        return len(tickers)

    async def get_latest(self, market: str | None = None) -> list[TickerDB]:
        """Get the latest ticker snapshot for all symbols."""
        stmt = select(TickerDB)
        if market:
            stmt = stmt.where(TickerDB.market == market)
        stmt = stmt.order_by(TickerDB.quote_volume_24h.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_symbol(self, symbol: str, market: str) -> TickerDB | None:
        stmt = select(TickerDB).where(
            TickerDB.symbol == symbol, TickerDB.market == market
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
