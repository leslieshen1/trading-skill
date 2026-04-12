"""Backfill historical data from Binance into the database.

Usage:
  python scripts/backfill_data.py --symbols BTCUSDT,ETHUSDT --interval 1h --limit 1000
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data.binance_futures import BinanceFuturesClient
from src.monitor.logger import setup_logging
from src.storage.database import async_session, init_db
from src.storage.repo_kline import KlineRepo

import structlog

logger = structlog.get_logger()


async def main(symbols: list[str], interval: str, limit: int) -> None:
    setup_logging()
    await init_db()

    client = BinanceFuturesClient()

    for symbol in symbols:
        logger.info("backfilling", symbol=symbol, interval=interval, limit=limit)
        try:
            klines = await client.get_klines(symbol, interval, limit=limit)
            if klines:
                async with async_session() as session:
                    repo = KlineRepo(session)
                    count = await repo.bulk_insert(klines)
                    logger.info("backfill_complete", symbol=symbol, bars=count)
            else:
                logger.warning("backfill_no_data", symbol=symbol)
        except Exception as e:
            logger.error("backfill_error", symbol=symbol, error=str(e))

    await client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill historical data")
    parser.add_argument("--symbols", default="BTCUSDT,ETHUSDT", help="Comma-separated symbols")
    parser.add_argument("--interval", default="1h", help="Kline interval")
    parser.add_argument("--limit", type=int, default=1000, help="Number of bars per symbol")
    args = parser.parse_args()

    symbol_list = [s.strip() for s in args.symbols.split(",")]
    asyncio.run(main(symbol_list, args.interval, args.limit))
