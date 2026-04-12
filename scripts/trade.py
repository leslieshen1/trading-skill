#!/usr/bin/env python3
"""CLI tool for trading operations on Binance Testnet.

Usage:
  python scripts/trade.py balance [--market futures_um|spot]
  python scripts/trade.py positions
  python scripts/trade.py orders [--symbol BTCUSDT]
  python scripts/trade.py order BTCUSDT BUY 0.001 [--type MARKET] [--leverage 5] [--price 50000]
  python scripts/trade.py cancel BTCUSDT ORDER_ID
"""

import argparse
import asyncio
import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.execution.binance_client import BinanceTradingClient


async def cmd_balance(args):
    client = BinanceTradingClient(market=args.market)
    try:
        balance = await client.get_balance()
        print(json.dumps(balance, indent=2))
    except Exception as e:
        print(f"错误: {e}")
    finally:
        await client.close()


async def cmd_positions(args):
    client = BinanceTradingClient(market="futures_um")
    try:
        positions = await client.get_positions()
        if not positions:
            print("当前无持仓")
            return
        for p in positions:
            print(
                f"{p['symbol']:<12} {p['side']:<6} "
                f"qty={p['quantity']:<10} entry=${p['entry_price']:<12} "
                f"PnL={p['unrealized_pnl']:+.4f}  "
                f"leverage={p['leverage']}x"
            )
    except Exception as e:
        print(f"错误: {e}")
    finally:
        await client.close()


async def cmd_orders(args):
    client = BinanceTradingClient(market="futures_um")
    try:
        orders = await client.get_open_orders(symbol=args.symbol)
        if not orders:
            print("无挂单")
            return
        for o in orders:
            print(json.dumps(o, indent=2))
    except Exception as e:
        print(f"错误: {e}")
    finally:
        await client.close()


async def cmd_order(args):
    symbol = args.symbol.upper()
    side = args.side.upper()
    quantity = args.quantity
    order_type = args.type.upper()
    price = args.price
    leverage = args.leverage

    client = BinanceTradingClient(market="futures_um")
    try:
        if leverage:
            result = await client.set_leverage(symbol, leverage)
            print(f"杠杆设置: {leverage}x")

        result = await client.place_order(
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price,
        )
        print(json.dumps({
            "orderId": result.get("orderId"),
            "status": result.get("status"),
            "symbol": symbol,
            "side": side,
            "type": order_type,
            "quantity": quantity,
            "avgPrice": result.get("avgPrice"),
        }, indent=2))
    except Exception as e:
        print(f"下单失败: {e}")
    finally:
        await client.close()


async def cmd_cancel(args):
    client = BinanceTradingClient(market="futures_um")
    try:
        result = await client.cancel_order(args.symbol.upper(), int(args.order_id))
        print(f"已取消: {json.dumps(result, indent=2)}")
    except Exception as e:
        print(f"取消失败: {e}")
    finally:
        await client.close()


def main():
    parser = argparse.ArgumentParser(description="Binance Trading CLI")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("balance", help="Account balance")
    p.add_argument("--market", default="futures_um", choices=["futures_um", "spot"])

    sub.add_parser("positions", help="Open positions")

    p = sub.add_parser("orders", help="Open orders")
    p.add_argument("--symbol", default=None)

    p = sub.add_parser("order", help="Place order")
    p.add_argument("symbol")
    p.add_argument("side", choices=["BUY", "SELL", "buy", "sell"])
    p.add_argument("quantity", type=float)
    p.add_argument("--type", default="MARKET", choices=["MARKET", "LIMIT"])
    p.add_argument("--price", type=float, default=None)
    p.add_argument("--leverage", type=int, default=None)

    p = sub.add_parser("cancel", help="Cancel order")
    p.add_argument("symbol")
    p.add_argument("order_id")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    cmd = {"balance": cmd_balance, "positions": cmd_positions, "orders": cmd_orders,
           "order": cmd_order, "cancel": cmd_cancel}[args.command]
    asyncio.run(cmd(args))


if __name__ == "__main__":
    main()
