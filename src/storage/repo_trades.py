"""CRUD operations for Trade records."""

from __future__ import annotations

import time

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.data.models import TradeRecordDB


class TradeRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, **kwargs) -> TradeRecordDB:
        record = TradeRecordDB(**kwargs)
        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def close_trade(
        self, trade_id: int, exit_price: float, pnl: float
    ) -> None:
        stmt = (
            update(TradeRecordDB)
            .where(TradeRecordDB.id == trade_id)
            .values(
                status="closed",
                exit_price=exit_price,
                pnl=pnl,
                closed_at=int(time.time() * 1000),
            )
        )
        await self.session.execute(stmt)
        await self.session.commit()

    async def get_open_trades(self) -> list[TradeRecordDB]:
        stmt = (
            select(TradeRecordDB)
            .where(TradeRecordDB.status == "open")
            .order_by(TradeRecordDB.opened_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_today_trades(self) -> list[TradeRecordDB]:
        """Trades opened in the last 24 hours."""
        since = int((time.time() - 86400) * 1000)
        stmt = (
            select(TradeRecordDB)
            .where(TradeRecordDB.opened_at >= since)
            .order_by(TradeRecordDB.opened_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_recent_closed(self, limit: int = 20) -> list[TradeRecordDB]:
        stmt = (
            select(TradeRecordDB)
            .where(TradeRecordDB.status == "closed")
            .order_by(TradeRecordDB.closed_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
