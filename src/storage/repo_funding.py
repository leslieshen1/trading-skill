"""CRUD operations for Funding Rate data."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_upsert
from sqlalchemy.ext.asyncio import AsyncSession

from src.data.models import FundingRateDB, FundingRateRecord


class FundingRateRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def bulk_insert(self, records: list[FundingRateRecord]) -> int:
        if not records:
            return 0

        for rec in records:
            stmt = (
                sqlite_upsert(FundingRateDB)
                .values(
                    symbol=rec.symbol,
                    funding_rate=rec.funding_rate,
                    funding_time=rec.funding_time,
                    mark_price=rec.mark_price,
                )
                .on_conflict_do_nothing()
            )
            await self.session.execute(stmt)

        await self.session.commit()
        return len(records)

    async def get_latest(self, symbol: str, limit: int = 10) -> list[FundingRateDB]:
        stmt = (
            select(FundingRateDB)
            .where(FundingRateDB.symbol == symbol)
            .order_by(FundingRateDB.funding_time.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        rows = list(result.scalars().all())
        rows.reverse()
        return rows

    async def get_all_latest(self) -> list[FundingRateDB]:
        """Get the most recent funding rate for every symbol."""
        # Subquery: max funding_time per symbol
        from sqlalchemy import func
        subq = (
            select(
                FundingRateDB.symbol,
                func.max(FundingRateDB.funding_time).label("max_ft"),
            )
            .group_by(FundingRateDB.symbol)
            .subquery()
        )
        stmt = (
            select(FundingRateDB)
            .join(
                subq,
                (FundingRateDB.symbol == subq.c.symbol)
                & (FundingRateDB.funding_time == subq.c.max_ft),
            )
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
