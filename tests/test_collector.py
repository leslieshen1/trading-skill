"""Tests for data models and storage layer."""

import time

import pytest

from src.data.models import (
    FundingRateRecord,
    KlineBar,
    Market,
    TickerSnapshot,
)
from src.storage.repo_funding import FundingRateRepo
from src.storage.repo_kline import KlineRepo
from src.storage.repo_ticker import TickerRepo


# ── Pydantic Model Tests ────────────────────────────────────────────────────

def test_ticker_snapshot_creation():
    t = TickerSnapshot(
        symbol="BTCUSDT",
        market=Market.FUTURES_UM,
        price=50000.0,
        change_24h=2.5,
        volume_24h=1000.0,
        quote_volume_24h=50_000_000.0,
    )
    assert t.symbol == "BTCUSDT"
    assert t.market == Market.FUTURES_UM
    assert t.funding_rate is None
    assert t.timestamp > 0


def test_kline_bar_creation():
    k = KlineBar(
        symbol="ETHUSDT",
        market=Market.SPOT,
        interval="1h",
        open_time=1700000000000,
        open=2000.0,
        high=2050.0,
        low=1990.0,
        close=2040.0,
        volume=500.0,
        close_time=1700003600000,
        quote_volume=1_000_000.0,
    )
    assert k.close > k.low


def test_funding_rate_record():
    f = FundingRateRecord(
        symbol="BTCUSDT",
        funding_rate=0.01,
        funding_time=1700000000000,
    )
    assert f.mark_price == 0.0  # default


# ── Storage Repo Tests ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ticker_upsert_and_read(db_session):
    repo = TickerRepo(db_session)

    tickers = [
        TickerSnapshot(
            symbol="BTCUSDT",
            market=Market.FUTURES_UM,
            price=50000.0,
            change_24h=2.5,
            quote_volume_24h=100_000_000.0,
            timestamp=int(time.time() * 1000),
        ),
        TickerSnapshot(
            symbol="ETHUSDT",
            market=Market.FUTURES_UM,
            price=3000.0,
            change_24h=-1.0,
            quote_volume_24h=50_000_000.0,
            timestamp=int(time.time() * 1000),
        ),
    ]
    count = await repo.bulk_upsert(tickers)
    assert count == 2

    # Read back
    all_tickers = await repo.get_latest(market="futures_um")
    assert len(all_tickers) == 2
    assert all_tickers[0].symbol == "BTCUSDT"  # higher volume first

    # Upsert (update price)
    tickers[0].price = 51000.0
    await repo.bulk_upsert(tickers[:1])
    db_session.expire_all()
    updated = await repo.get_by_symbol("BTCUSDT", "futures_um")
    assert updated.price == 51000.0


@pytest.mark.asyncio
async def test_kline_insert_and_read(db_session):
    repo = KlineRepo(db_session)

    bars = [
        KlineBar(
            symbol="BTCUSDT",
            market=Market.FUTURES_UM,
            interval="1h",
            open_time=1700000000000 + i * 3600000,
            open=50000.0 + i * 100,
            high=50100.0 + i * 100,
            low=49900.0 + i * 100,
            close=50050.0 + i * 100,
            volume=100.0,
            close_time=1700000000000 + (i + 1) * 3600000,
            quote_volume=5_000_000.0,
        )
        for i in range(10)
    ]
    count = await repo.bulk_insert(bars)
    assert count == 10

    # Read back
    result = await repo.get_klines("BTCUSDT", "1h")
    assert len(result) == 10
    assert result[0].open_time < result[-1].open_time  # ascending


@pytest.mark.asyncio
async def test_funding_rate_insert_and_read(db_session):
    repo = FundingRateRepo(db_session)

    records = [
        FundingRateRecord(
            symbol="BTCUSDT",
            funding_rate=0.01,
            funding_time=1700000000000 + i * 28800000,
            mark_price=50000.0,
        )
        for i in range(3)
    ]
    count = await repo.bulk_insert(records)
    assert count == 3

    result = await repo.get_latest("BTCUSDT", limit=10)
    assert len(result) == 3

    # No duplicates on re-insert
    count2 = await repo.bulk_insert(records)
    assert count2 == 3  # returns len, but DB ignores duplicates
    result2 = await repo.get_latest("BTCUSDT", limit=10)
    assert len(result2) == 3
