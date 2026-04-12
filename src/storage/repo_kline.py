"""CRUD operations for K-line (candlestick) data."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_upsert
from sqlalchemy.ext.asyncio import AsyncSession

from src.data.models import KlineBar, KlineDB


class KlineRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def bulk_insert(self, bars: list[KlineBar]) -> int:
        """Insert klines, skip duplicates."""
        if not bars:
            return 0

        for bar in bars:
            stmt = (
                sqlite_upsert(KlineDB)
                .values(
                    symbol=bar.symbol,
                    market=bar.market.value,
                    interval=bar.interval,
                    open_time=bar.open_time,
                    open=bar.open,
                    high=bar.high,
                    low=bar.low,
                    close=bar.close,
                    volume=bar.volume,
                    close_time=bar.close_time,
                    quote_volume=bar.quote_volume,
                    trade_count=bar.trade_count,
                )
                .on_conflict_do_nothing()
            )
            await self.session.execute(stmt)

        await self.session.commit()
        return len(bars)

    async def get_klines(
        self,
        symbol: str,
        interval: str,
        market: str = "futures_um",
        limit: int = 100,
    ) -> list[KlineDB]:
        """Get recent klines for a symbol, ordered by time ascending."""
        stmt = (
            select(KlineDB)
            .where(
                KlineDB.symbol == symbol,
                KlineDB.interval == interval,
                KlineDB.market == market,
            )
            .order_by(KlineDB.open_time.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        rows = list(result.scalars().all())
        rows.reverse()  # ascending order
        return rows
