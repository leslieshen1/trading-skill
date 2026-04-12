"""Data models — Pydantic schemas for API data + SQLAlchemy ORM models for persistence."""

from __future__ import annotations

import time
from enum import Enum

from pydantic import BaseModel, Field
from sqlalchemy import (
    BigInteger,
    Column,
    Float,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase


# ── Enums ────────────────────────────────────────────────────────────────────

class Market(str, Enum):
    SPOT = "spot"
    FUTURES_UM = "futures_um"
    FUTURES_CM = "futures_cm"


# ── Pydantic schemas (API / in-memory) ───────────────────────────────────────

class TickerSnapshot(BaseModel):
    """A point-in-time snapshot for one symbol."""

    symbol: str
    market: Market
    base_asset: str = ""
    quote_asset: str = ""
    price: float
    change_24h: float = 0.0
    volume_24h: float = 0.0
    quote_volume_24h: float = 0.0
    high_24h: float = 0.0
    low_24h: float = 0.0
    trade_count: int = 0
    # Futures-only
    funding_rate: float | None = None
    mark_price: float | None = None
    index_price: float | None = None
    open_interest: float | None = None
    contract_type: str | None = None
    timestamp: int = Field(default_factory=lambda: int(time.time() * 1000))


class KlineBar(BaseModel):
    """Single candlestick bar."""

    symbol: str
    market: Market
    interval: str
    open_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    close_time: int
    quote_volume: float
    trade_count: int = 0


class FundingRateRecord(BaseModel):
    """Funding-rate snapshot."""

    symbol: str
    funding_rate: float
    funding_time: int
    mark_price: float = 0.0


# ── SQLAlchemy ORM models ────────────────────────────────────────────────────

class Base(DeclarativeBase):
    pass


class TickerDB(Base):
    __tablename__ = "tickers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(32), nullable=False)
    market = Column(String(16), nullable=False)
    base_asset = Column(String(16), default="")
    quote_asset = Column(String(16), default="")
    price = Column(Float, nullable=False)
    change_24h = Column(Float, default=0.0)
    volume_24h = Column(Float, default=0.0)
    quote_volume_24h = Column(Float, default=0.0)
    high_24h = Column(Float, default=0.0)
    low_24h = Column(Float, default=0.0)
    trade_count = Column(Integer, default=0)
    funding_rate = Column(Float, nullable=True)
    mark_price = Column(Float, nullable=True)
    index_price = Column(Float, nullable=True)
    open_interest = Column(Float, nullable=True)
    contract_type = Column(String(32), nullable=True)
    timestamp = Column(BigInteger, nullable=False)

    __table_args__ = (
        UniqueConstraint("symbol", "market", name="uq_ticker_symbol_market"),
        Index("ix_ticker_market", "market"),
        Index("ix_ticker_timestamp", "timestamp"),
    )


class KlineDB(Base):
    __tablename__ = "klines"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(32), nullable=False)
    market = Column(String(16), nullable=False)
    interval = Column(String(8), nullable=False)
    open_time = Column(BigInteger, nullable=False)
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(Float, nullable=False)
    close_time = Column(BigInteger, nullable=False)
    quote_volume = Column(Float, default=0.0)
    trade_count = Column(Integer, default=0)

    __table_args__ = (
        UniqueConstraint("symbol", "market", "interval", "open_time", name="uq_kline"),
        Index("ix_kline_symbol_interval", "symbol", "interval"),
        Index("ix_kline_open_time", "open_time"),
    )


class FundingRateDB(Base):
    __tablename__ = "funding_rates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(32), nullable=False)
    funding_rate = Column(Float, nullable=False)
    funding_time = Column(BigInteger, nullable=False)
    mark_price = Column(Float, default=0.0)

    __table_args__ = (
        UniqueConstraint("symbol", "funding_time", name="uq_funding"),
        Index("ix_funding_symbol", "symbol"),
        Index("ix_funding_time", "funding_time"),
    )


class TradeRecordDB(Base):
    __tablename__ = "trade_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(32), nullable=False)
    market = Column(String(16), nullable=False)
    side = Column(String(8), nullable=False)  # BUY / SELL
    signal = Column(String(16), nullable=False)  # long / short / close_long / close_short
    strategy_name = Column(String(64), nullable=False)
    entry_price = Column(Float, nullable=False)
    quantity = Column(Float, nullable=False)
    stop_loss = Column(Float, nullable=True)
    take_profit = Column(Float, nullable=True)
    status = Column(String(16), default="open")  # open / closed / cancelled
    pnl = Column(Float, nullable=True)
    exit_price = Column(Float, nullable=True)
    opened_at = Column(BigInteger, nullable=False)
    closed_at = Column(BigInteger, nullable=True)
    ai_reasoning = Column(String(2000), nullable=True)

    __table_args__ = (
        Index("ix_trade_symbol", "symbol"),
        Index("ix_trade_status", "status"),
    )


class SignalRecordDB(Base):
    __tablename__ = "signal_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(32), nullable=False)
    market = Column(String(16), nullable=False)
    strategy_name = Column(String(64), nullable=False)
    signal = Column(String(16), nullable=False)
    confidence = Column(Float, default=0.0)
    entry_price = Column(Float, nullable=False)
    stop_loss = Column(Float, nullable=True)
    take_profit = Column(Float, nullable=True)
    reasoning = Column(String(2000), nullable=True)
    ai_approved = Column(Integer, nullable=True)  # 1=approved, 0=rejected, null=not checked
    executed = Column(Integer, default=0)
    timestamp = Column(BigInteger, nullable=False)

    __table_args__ = (
        Index("ix_signal_symbol", "symbol"),
        Index("ix_signal_timestamp", "timestamp"),
    )
