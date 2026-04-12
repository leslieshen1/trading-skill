"""Run a backtest with built-in strategies on historical data.

Usage:
  python scripts/run_backtest.py --symbol BTCUSDT --interval 1h
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.backtest.data_loader import BacktestDataLoader
from src.backtest.engine import BacktestConfig, BacktestEngine
from src.backtest.report import generate_text_report
from src.monitor.logger import setup_logging
from src.strategy.loader import load_strategies


async def main(symbol: str, interval: str, limit: int, equity: float) -> None:
    setup_logging()

    # Load strategies
    strategies = load_strategies()
    if not strategies:
        print("No strategies loaded. Check config/strategies/")
        return

    print(f"Loaded {len(strategies)} strategies: {[s.name for s in strategies]}")

    # Load data
    loader = BacktestDataLoader()
    print(f"Fetching {limit} bars of {symbol} {interval} from Binance...")
    klines = await loader.load_from_api(symbol, interval, limit=limit)
    await loader.close()

    if not klines:
        print("Failed to load data. Check your API key and network.")
        return

    print(f"Loaded {len(klines)} bars")

    # Run backtest
    config = BacktestConfig(initial_equity=equity)
    engine = BacktestEngine(strategies, config)
    result = await engine.run(klines, symbol=symbol, interval=interval)

    # Print report
    print(generate_text_report(result))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run backtest")
    parser.add_argument("--symbol", default="BTCUSDT", help="Trading pair")
    parser.add_argument("--interval", default="1h", help="Kline interval")
    parser.add_argument("--limit", type=int, default=500, help="Number of bars")
    parser.add_argument("--equity", type=float, default=10000.0, help="Initial equity")
    args = parser.parse_args()

    asyncio.run(main(args.symbol, args.interval, args.limit, args.equity))
