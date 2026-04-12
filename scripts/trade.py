#!/usr/bin/env python3
"""Binance Futures 交易 CLI（双向持仓模式 + Algo 止损）

行情:
  python scripts/trade.py balance                           # 账户余额
  python scripts/trade.py pos                               # 当前持仓（v3/positionRisk）
  python scripts/trade.py orders [--symbol BTCUSDT]         # 挂单查询

下单:
  python scripts/trade.py order RAVE BUY 100 --leverage 3   # 市价开多 100 张，3x杠杆
  python scripts/trade.py order RAVE SELL 100               # 市价开空
  python scripts/trade.py cancel RAVEUSDT ORDER_ID          # 撤单

止损（Algo Order）:
  python scripts/trade.py sl RAVEUSDT 0.0050 --side LONG    # 给 LONG 仓设止损
  python scripts/trade.py stops                             # 查看所有 algo 止损单
  python scripts/trade.py cancel-stop RAVEUSDT ALGO_ID      # 取消 algo 止损

一键开仓+止损:
  python scripts/trade.py open RAVE BUY 100 --leverage 3 --sl 0.0050
"""

import argparse
import asyncio
import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.execution.binance_client import BinanceTradingClient


# ── 账户 ─────────────────────────────────────────────────────────────

async def cmd_balance(args):
    client = BinanceTradingClient(market=args.market)
    try:
        balance = await client.get_balance()
        total = balance["total"]
        avail = balance["available"]
        margin = balance["used_margin"]
        pnl = balance["unrealized_pnl"]
        print(f"总权益: ${total:.2f}U")
        print(f"可用:   ${avail:.2f}U")
        print(f"已用保证金: ${margin:.2f}U")
        print(f"未实现盈亏: {pnl:+.2f}U")
    except Exception as e:
        print(f"错误: {e}")
    finally:
        await client.close()


async def cmd_positions(args):
    """使用 /fapi/v3/positionRisk 获取准确持仓（双向持仓模式）"""
    client = BinanceTradingClient(market="futures_um")
    try:
        risks = await client.get_position_risk(symbol=args.symbol.upper() if args.symbol else None)
        has_pos = False
        for p in risks:
            amt = float(p.get("positionAmt", 0))
            if amt == 0:
                continue
            has_pos = True
            symbol = p["symbol"]
            side = p.get("positionSide", "LONG" if amt > 0 else "SHORT")
            entry = float(p.get("entryPrice", 0))
            mark = float(p.get("markPrice", 0))
            pnl = float(p.get("unRealizedProfit", 0))
            margin = float(p.get("initialMargin", 0))
            leverage = p.get("leverage", "?")
            pnl_pct = (pnl / margin * 100) if margin > 0 else 0
            liq = float(p.get("liquidationPrice", 0))
            print(
                f"{symbol:<14} {side:<6} {abs(amt):<10} "
                f"entry={entry:<12.6f} mark={mark:<12.6f} "
                f"PnL={pnl:+.2f}U ({pnl_pct:+.1f}%)  "
                f"lev={leverage}x  liq={liq:.6f}"
            )
        if not has_pos:
            print("当前无持仓")
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
            print(
                f"{o.get('symbol','?'):<14} {o.get('side','?'):<5} "
                f"type={o.get('type','?')} qty={o.get('origQty','?')} "
                f"price={o.get('price','?')} stopPrice={o.get('stopPrice','?')} "
                f"orderId={o.get('orderId','?')}"
            )
    except Exception as e:
        print(f"错误: {e}")
    finally:
        await client.close()


# ── 下单 ─────────────────────────────────────────────────────────────

async def cmd_order(args):
    symbol = args.symbol.upper()
    if not symbol.endswith("USDT"):
        symbol += "USDT"
    side = args.side.upper()
    quantity = args.quantity
    order_type = args.type.upper()
    price = args.price
    leverage = args.leverage

    client = BinanceTradingClient(market="futures_um")
    try:
        if leverage:
            await client.set_leverage(symbol, leverage)
            print(f"杠杆设置: {leverage}x")

        result = await client.place_order(
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price,
        )
        avg = result.get("avgPrice", "N/A")
        print(f"✅ 下单成功: {symbol} {side} {quantity}")
        print(f"   orderId={result.get('orderId')}  status={result.get('status')}  avgPrice={avg}")
    except Exception as e:
        print(f"❌ 下单失败: {e}")
    finally:
        await client.close()


async def cmd_cancel(args):
    client = BinanceTradingClient(market="futures_um")
    try:
        result = await client.cancel_order(args.symbol.upper(), int(args.order_id))
        print(f"✅ 已取消: orderId={result.get('orderId')}")
    except Exception as e:
        print(f"❌ 取消失败: {e}")
    finally:
        await client.close()


# ── 止损（Algo Order）────────────────────────────────────────────────

async def cmd_stoploss(args):
    """给指定持仓设置 algo 止损单"""
    symbol = args.symbol.upper()
    if not symbol.endswith("USDT"):
        symbol += "USDT"
    trigger = args.trigger_price
    pos_side = args.side.upper()  # LONG or SHORT

    # LONG 持仓止损 = SELL，SHORT 持仓止损 = BUY
    order_side = "SELL" if pos_side == "LONG" else "BUY"

    client = BinanceTradingClient(market="futures_um")
    try:
        result = await client.place_algo_order(
            symbol=symbol,
            side=order_side,
            order_type="STOP_MARKET",
            trigger_price=trigger,
            position_side=pos_side,
            close_position=True,
        )
        print(f"✅ 止损已设置: {symbol} {pos_side} → 触发价 {trigger}")
        print(f"   algoId={result.get('algoId')}")
    except Exception as e:
        print(f"❌ 止损设置失败: {e}")
    finally:
        await client.close()


async def cmd_stops(args):
    """查看所有 algo 止损单"""
    client = BinanceTradingClient(market="futures_um")
    try:
        orders = await client.get_open_algo_orders(
            symbol=args.symbol.upper() if args.symbol else None
        )
        if not orders:
            print("无 algo 止损单")
            return
        for o in orders:
            print(
                f"{o.get('symbol','?'):<14} {o.get('side','?'):<5} "
                f"posSide={o.get('positionSide','?')} "
                f"type={o.get('type','?')} "
                f"trigger={o.get('triggerPrice','?')} "
                f"algoId={o.get('algoId','?')} "
                f"status={o.get('algoStatus','?')}"
            )
    except Exception as e:
        print(f"错误: {e}")
    finally:
        await client.close()


async def cmd_cancel_stop(args):
    """取消 algo 止损单"""
    symbol = args.symbol.upper()
    if not symbol.endswith("USDT"):
        symbol += "USDT"
    client = BinanceTradingClient(market="futures_um")
    try:
        result = await client.cancel_algo_order(symbol, int(args.algo_id))
        print(f"✅ 已取消 algo 止损: algoId={args.algo_id}")
    except Exception as e:
        print(f"❌ 取消失败: {e}")
    finally:
        await client.close()


# ── 一键开仓+止损 ───────────────────────────────────────────────────

async def cmd_open(args):
    """开仓 + 自动设止损（铁律：裸仓零容忍）"""
    symbol = args.symbol.upper()
    if not symbol.endswith("USDT"):
        symbol += "USDT"
    side = args.side.upper()
    quantity = args.quantity
    order_type = args.type.upper()
    price = args.price
    leverage = args.leverage
    sl_price = args.sl

    pos_side = "LONG" if side == "BUY" else "SHORT"
    sl_side = "SELL" if side == "BUY" else "BUY"

    client = BinanceTradingClient(market="futures_um")
    try:
        # 1. 设杠杆
        if leverage:
            await client.set_leverage(symbol, leverage)
            print(f"杠杆: {leverage}x")

        # 2. 开仓
        result = await client.place_order(
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price,
        )
        avg = result.get("avgPrice", "N/A")
        print(f"✅ 开仓成功: {symbol} {side} {quantity}  avgPrice={avg}")

        # 3. 设止损
        if sl_price:
            try:
                sl_result = await client.place_algo_order(
                    symbol=symbol,
                    side=sl_side,
                    order_type="STOP_MARKET",
                    trigger_price=sl_price,
                    position_side=pos_side,
                    close_position=True,
                )
                print(f"✅ 止损已设: {pos_side} → 触发价 {sl_price}  algoId={sl_result.get('algoId')}")
            except Exception as e:
                print(f"⚠️ 止损设置失败: {e}")
                print("⚠️ 警告：当前为裸仓！请手动设置止损或立即平仓！")
        else:
            print("⚠️ 未设止损（--sl 参数缺失），请立即手动设置！")
    except Exception as e:
        print(f"❌ 开仓失败: {e}")
    finally:
        await client.close()


# ── CLI ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Binance Futures 交易 CLI（双向持仓 + Algo 止损）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s balance                          # 查余额
  %(prog)s pos                              # 查持仓
  %(prog)s order RAVE BUY 100 --leverage 3  # 市价开多
  %(prog)s sl RAVEUSDT 0.005 --side LONG    # 设止损
  %(prog)s stops                            # 查止损单
  %(prog)s open RAVE BUY 100 -l 3 --sl 0.005  # 开仓+止损一步到位
"""
    )
    sub = parser.add_subparsers(dest="command")

    # balance
    p = sub.add_parser("balance", help="账户余额")
    p.add_argument("--market", default="futures_um", choices=["futures_um", "spot"])

    # positions
    p = sub.add_parser("pos", help="当前持仓（v3/positionRisk，双向持仓准确）")
    p.add_argument("--symbol", default=None, help="筛选币种")

    # orders
    p = sub.add_parser("orders", help="挂单查询")
    p.add_argument("--symbol", default=None)

    # order (simple)
    p = sub.add_parser("order", help="下单（市价/限价）")
    p.add_argument("symbol", help="交易对，如 RAVE 或 RAVEUSDT")
    p.add_argument("side", choices=["BUY", "SELL", "buy", "sell"], help="BUY=开多 SELL=开空")
    p.add_argument("quantity", type=float, help="下单数量")
    p.add_argument("--type", default="MARKET", choices=["MARKET", "LIMIT"])
    p.add_argument("--price", type=float, default=None, help="限价单价格")
    p.add_argument("--leverage", "-l", type=int, default=None, help="杠杆倍数")

    # cancel
    p = sub.add_parser("cancel", help="撤销普通挂单")
    p.add_argument("symbol")
    p.add_argument("order_id")

    # stoploss
    p = sub.add_parser("sl", help="设置 algo 止损单")
    p.add_argument("symbol", help="交易对")
    p.add_argument("trigger_price", type=float, help="止损触发价")
    p.add_argument("--side", required=True, choices=["LONG", "SHORT", "long", "short"],
                   help="持仓方向（LONG=多头止损 SHORT=空头止损）")

    # list stops
    p = sub.add_parser("stops", help="查看所有 algo 止损单")
    p.add_argument("--symbol", default=None)

    # cancel stop
    p = sub.add_parser("cancel-stop", help="取消 algo 止损单")
    p.add_argument("symbol")
    p.add_argument("algo_id", help="algo 订单 ID")

    # open (combined)
    p = sub.add_parser("open", help="一键开仓+止损（推荐）")
    p.add_argument("symbol", help="交易对，如 RAVE")
    p.add_argument("side", choices=["BUY", "SELL", "buy", "sell"], help="BUY=做多 SELL=做空")
    p.add_argument("quantity", type=float, help="下单数量")
    p.add_argument("--type", default="MARKET", choices=["MARKET", "LIMIT"])
    p.add_argument("--price", type=float, default=None, help="限价单价格")
    p.add_argument("--leverage", "-l", type=int, default=None, help="杠杆倍数")
    p.add_argument("--sl", type=float, default=None, help="止损触发价（强烈建议设置）")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    cmds = {
        "balance": cmd_balance,
        "pos": cmd_positions,
        "orders": cmd_orders,
        "order": cmd_order,
        "cancel": cmd_cancel,
        "sl": cmd_stoploss,
        "stops": cmd_stops,
        "cancel-stop": cmd_cancel_stop,
        "open": cmd_open,
    }
    asyncio.run(cmds[args.command](args))


if __name__ == "__main__":
    main()
