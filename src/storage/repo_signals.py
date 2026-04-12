"""CRUD operations for Signal records."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.data.models import SignalRecordDB


class SignalRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, **kwargs) -> SignalRecordDB:
        record = SignalRecordDB(**kwargs)
        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def get_recent(self, symbol: str | None = None, limit: int = 50) -> list[SignalRecordDB]:
        stmt = select(SignalRecordDB).order_by(SignalRecordDB.timestamp.desc()).limit(limit)
        if symbol:
            stmt = stmt.where(SignalRecordDB.symbol == symbol)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
