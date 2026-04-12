#!/usr/bin/env python3
"""CLI tool for fetching live market data from Binance.

Usage:
  python scripts/market.py tickers [--market futures_um|spot] [--limit 20]
  python scripts/market.py detail BTCUSDT [--market futures_um]
  python scripts/market.py analysis BTCUSDT [--interval 1h] [--market futures_um]
  python scripts/market.py funding [--symbol BTCUSDT] [--limit 10]
  python scripts/market.py oi BTCUSDT
"""

import argparse
import asyncio
import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.data.binance_futures import BinanceFuturesClient
from src.data.binance_spot import BinanceSpotClient
from src.strategy.indicators import calculate_indicators


async def cmd_tickers(args):
    client = BinanceFuturesClient() if args.market == "futures_um" else BinanceSpotClient()
    try:
        tickers = await client.get_all_tickers()
        tickers.sort(key=lambda t: t.quote_volume_24h, reverse=True)
        tickers = tickers[: args.limit]
        for t in tickers:
            funding = ""
            if hasattr(t, "funding_rate") and t.funding_rate is not None:
                funding = f"  费率:{t.funding_rate:+.4f}%"
            print(
                f"{t.symbol:<16} ${t.price:<12.4f} "
                f"{t.change_24h:+6.2f}%  "
                f"Vol: ${t.quote_volume_24h / 1e6:.1f}M"
                f"{funding}"
            )
    finally:
        await client.close()


async def cmd_detail(args):
    symbol = args.symbol.upper()
    client = BinanceFuturesClient() if args.market == "futures_um" else BinanceSpotClient()
    try:
        tickers = await client.get_all_tickers()
        match = next((t for t in tickers if t.symbol == symbol), None)
        if not match:
            print(f"未找到 {symbol}")
            return
        info = {
            "symbol": match.symbol,
            "price": match.price,
            "change_24h%": round(match.change_24h, 2),
            "high_24h": match.high_24h,
            "low_24h": match.low_24h,
            "volume_usdt": round(match.quote_volume_24h),
            "trade_count": match.trade_count,
        }
        if args.market == "futures_um":
            info["funding_rate%"] = round(match.funding_rate, 4)
            info["mark_price"] = match.mark_price
            info["index_price"] = match.index_price
            try:
                fc = BinanceFuturesClient()
                oi = await fc.get_open_interest(symbol)
                info["open_interest"] = oi
                await fc.close()
            except Exception:
                pass
        print(json.dumps(info, indent=2, ensure_ascii=False))
    finally:
        await client.close()


async def cmd_analysis(args):
    symbol = args.symbol.upper()
    client = BinanceFuturesClient() if args.market == "futures_um" else BinanceSpotClient()
    try:
        klines = await client.get_klines(symbol, interval=args.interval, limit=100)
        if not klines:
            print(f"{symbol} 无K线数据")
            return
        ind = calculate_indicators(klines)
        price = klines[-1].close
        print(f"=== {symbol} {args.interval} 技术分析 ===")
        print(f"价格: ${price}")
        print(f"RSI(14): {ind.rsi_14:.1f}" if ind.rsi_14 else "RSI: N/A")
        print(f"MACD: {ind.macd_value:.4f}  Signal: {ind.macd_signal_value:.4f}  Hist: {ind.macd_histogram:.4f}  [{ind.macd_signal}]" if ind.macd_value else "MACD: N/A")
        print(f"EMA20: {ind.ema_20:.4f}  EMA50: {ind.ema_50:.4f}  趋势: {ind.ema_trend}" if ind.ema_20 else "EMA: N/A")
        print(f"布林带: Upper={ind.bollinger_upper:.4f} Mid={ind.bollinger_mid:.4f} Lower={ind.bollinger_lower:.4f}  %B={ind.bollinger_pct:.2f}" if ind.bollinger_upper else "Bollinger: N/A")
        print(f"ATR(14): {ind.atr_14:.4f}  ({ind.atr_percent:.2f}%)" if ind.atr_14 else "ATR: N/A")
        print(f"ADX(14): {ind.adx_14:.1f}" if ind.adx_14 else "ADX: N/A")
        print(f"KDJ: K={ind.stoch_k:.1f}  D={ind.stoch_d:.1f}" if ind.stoch_k else "KDJ: N/A")
        print(f"成交量比: {ind.volume_ratio:.2f}x" if ind.volume_ratio else "Volume: N/A")
    finally:
        await client.close()


async def cmd_funding(args):
    client = BinanceFuturesClient()
    try:
        symbol = args.symbol.upper() if args.symbol else None
        rates = await client.get_funding_rates(symbol=symbol, limit=args.limit)
        for r in rates:
            from datetime import datetime
            ts = datetime.fromtimestamp(r.funding_time / 1000).strftime("%m-%d %H:%M")
            print(f"{r.symbol:<16} {r.funding_rate:+.4f}%  {ts}")
    finally:
        await client.close()


async def cmd_oi(args):
    client = BinanceFuturesClient()
    try:
        oi = await client.get_open_interest(args.symbol.upper())
        print(f"{args.symbol.upper()} 持仓量: {oi}")
    finally:
        await client.close()


def main():
    parser = argparse.ArgumentParser(description="Binance Market Data CLI")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("tickers", help="Top tickers by volume")
    p.add_argument("--market", default="futures_um", choices=["futures_um", "spot"])
    p.add_argument("--limit", type=int, default=20)

    p = sub.add_parser("detail", help="Symbol detail")
    p.add_argument("symbol")
    p.add_argument("--market", default="futures_um", choices=["futures_um", "spot"])

    p = sub.add_parser("analysis", help="Technical analysis")
    p.add_argument("symbol")
    p.add_argument("--interval", default="1h", choices=["5m", "15m", "1h", "4h", "1d"])
    p.add_argument("--market", default="futures_um", choices=["futures_um", "spot"])

    p = sub.add_parser("funding", help="Funding rates")
    p.add_argument("--symbol", default=None)
    p.add_argument("--limit", type=int, default=10)

    p = sub.add_parser("oi", help="Open interest")
    p.add_argument("symbol")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    cmd = {"tickers": cmd_tickers, "detail": cmd_detail, "analysis": cmd_analysis,
           "funding": cmd_funding, "oi": cmd_oi}[args.command]
    asyncio.run(cmd(args))


if __name__ == "__main__":
    main()
