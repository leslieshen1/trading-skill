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
        print(f"布林带: Upper={ind.bollinger_upper:.4f} Mid={ind.bollinger_mid:.4f} Lower={ind.bollinger_lower:.4f}  %B={ind.bollinger_pct:.2f}" if (ind.bollinger_upper and ind.bollinger_mid and ind.bollinger_lower and ind.bollinger_pct is not None) else "Bollinger: N/A")
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


async def cmd_scan(args):
    """扫描全市场，识别早期启动/反转信号。

    检测模式：
    1. 早期启动（做多）：涨 5-30% + 负费率 + 量放大 + %B > 0.7
    2. 高点反转（做空）：涨 > 50% + KDJ > 90 + 正费率 > 0.1%
    3. 超卖反弹（做多）：跌 > 15% + KDJ < 20 + 负费率
    4. 负费率轧空（做多）：费率 < -0.15% + 价格横盘或微涨
    5. 突破做多（趋势延续）：涨 > 30% + 大成交量，捕捉已启动但趋势延续的妖币
    6. 异常量能：24h 交易量 > $200M，捕捉资金异动但未归入其他桶的币
    """
    # 排除大币种
    BIG_CAPS = {"BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT",
                "BTCUSDC", "ETHUSDC", "SOLUSDC", "XRPUSDC", "XAUUSDT", "XAGUSDT",
                "PAXGUSDT", "XAUTUSDT"}

    client = BinanceFuturesClient()
    try:
        tickers = await client.get_all_tickers()
        # 获取交易状态，过滤掉已下架/结算中的币
        try:
            info = await client.get_exchange_info()
            trading_syms = {s['symbol'] for s in info.get('symbols', [])
                            if s.get('status') == 'TRADING'}
        except Exception:
            trading_syms = None  # 失败则不过滤
        # 过滤：只看有足够交易量的小币 (> $1M 24h volume) + 正在交易中
        candidates = [t for t in tickers
                      if t.symbol not in BIG_CAPS
                      and t.quote_volume_24h > 1_000_000
                      and t.funding_rate is not None
                      and (trading_syms is None or t.symbol in trading_syms)]

        early_pumps = []      # 早期启动
        top_reversals = []    # 高点反转做空
        oversold = []         # 超卖反弹
        neg_funding = []      # 负费率轧空
        breakouts = []        # 突破做多（趋势延续）
        vol_anomalies = []    # 异常量能

        for t in candidates:
            # 模式1: 早期启动 — 涨 5-40%, 费率刚转负或微负, 量 > $10M
            if (5 < t.change_24h < 40
                and -0.3 < t.funding_rate < -0.02
                and t.quote_volume_24h > 10_000_000):
                early_pumps.append(t)

            # 模式2: 高点反转做空 — 涨 > 40%, 正费率 > 0.08%
            if (t.change_24h > 40
                and t.funding_rate > 0.08):
                top_reversals.append(t)

            # 模式3: 超卖反弹 — 跌 > 15%, 费率负
            if (t.change_24h < -15
                and t.funding_rate < 0
                and t.quote_volume_24h > 5_000_000):
                oversold.append(t)

            # 模式4: 负费率轧空 — 费率 < -0.15%, 价格没大跌
            if (t.funding_rate < -0.15
                and t.change_24h > -10):
                neg_funding.append(t)

            # 模式5: 突破做多（趋势延续） — 涨 > 30%, 量 > $30M, 费率非极端正
            # 用于捕捉BIO/BASED/ORDI这类已经启动但仍在延续的妖币
            if (t.change_24h > 30
                and t.quote_volume_24h > 30_000_000
                and t.funding_rate < 0.15):
                breakouts.append(t)

            # 模式6: 异常量能 — 24h交易量 > $200M，资金明显异动
            # 不看涨跌幅，用来发现其他桶没覆盖到的被大资金炒作的币
            if t.quote_volume_24h > 200_000_000:
                vol_anomalies.append(t)

        # 模式8: 15分钟共振做多 — 5个条件至少满足4个
        # 筛选：涨幅-5%到+30%(未极端) + 量>$5M，并发拉15m K线和OI历史
        resonance_candidates = [t for t in candidates
                                if -5 < t.change_24h < 30
                                and t.quote_volume_24h > 5_000_000]
        resonance_alerts = []  # (ticker, score, details_dict)

        import httpx
        async def check_resonance(t):
            try:
                # 并发拉取 15m K线 + OI历史
                bars_task = client.get_klines(t.symbol, interval="15m", limit=30)
                async with httpx.AsyncClient(timeout=10.0, base_url="https://fapi.binance.com") as h:
                    oi_task = h.get("/futures/data/openInterestHist",
                                    params={"symbol": t.symbol, "period": "5m", "limit": 7})
                    bars, oi_resp = await asyncio.gather(bars_task, oi_task)

                if not bars or len(bars) < 25:
                    return None
                closes = [b.close for b in bars]
                current_close = closes[-1]

                # 条件1: MA对齐 — EMA5 > EMA20 且 价格 > EMA20
                def ema(data, period):
                    k = 2 / (period + 1)
                    e = data[0]
                    for p in data[1:]:
                        e = p * k + e * (1 - k)
                    return e
                ema5 = ema(closes[-10:], 5)
                ema20 = ema(closes[-25:], 20)
                ma_aligned = current_close > ema20 and ema5 > ema20

                # 条件2: 量能 > 20根均量 × 1.8
                current_vol = bars[-1].volume
                avg_vol = sum(b.volume for b in bars[-21:-1]) / 20
                vol_surge = current_vol > avg_vol * 1.8 if avg_vol > 0 else False
                vol_ratio = current_vol / avg_vol if avg_vol > 0 else 0

                # 条件3: OI过去30分钟增长 > +3% (5m * 6bars = 30min)
                oi_data = oi_resp.json() if oi_resp.status_code == 200 else []
                oi_pct = 0
                if len(oi_data) >= 7:
                    oi_now = float(oi_data[-1]["sumOpenInterest"])
                    oi_30min_ago = float(oi_data[0]["sumOpenInterest"])
                    if oi_30min_ago > 0:
                        oi_pct = (oi_now / oi_30min_ago - 1) * 100
                oi_grow = oi_pct > 3

                # 条件4: 费率在 -0.15% 到 +0.08%
                funding_ok = -0.15 < t.funding_rate < 0.08

                # 条件5: %B 在 0.6-1.0
                mid = sum(closes[-20:]) / 20
                std = (sum((c - mid) ** 2 for c in closes[-20:]) / 20) ** 0.5
                upper = mid + 2 * std
                lower = mid - 2 * std
                pct_b = (current_close - lower) / (upper - lower) if upper > lower else 0.5
                pct_b_ok = 0.6 <= pct_b <= 1.0

                score = sum([ma_aligned, vol_surge, oi_grow, funding_ok, pct_b_ok])
                if score >= 4:
                    details = {
                        'price': current_close,
                        'ma': '✓' if ma_aligned else '✗',
                        'vol': f"{vol_ratio:.1f}x{'✓' if vol_surge else '✗'}",
                        'oi': f"{oi_pct:+.1f}%{'✓' if oi_grow else '✗'}",
                        'fr': f"{t.funding_rate:+.3f}%{'✓' if funding_ok else '✗'}",
                        'b': f"{pct_b:.2f}{'✓' if pct_b_ok else '✗'}",
                    }
                    return (t, score, details)
                return None
            except Exception:
                return None

        sem_r = asyncio.Semaphore(15)
        async def bounded_r(t):
            async with sem_r:
                return await check_resonance(t)
        r_results = await asyncio.gather(*[bounded_r(t) for t in resonance_candidates])
        resonance_alerts = [r for r in r_results if r is not None]

        # 模式7: 早期量能异动 — 需要单独拉K线检查
        # 筛选：涨幅-2%到+8%(微涨或刚启动) + 量>$10M，然后拉1h K线检查当前量能vs20h均量
        early_vol_candidates = [t for t in candidates
                                if -2 < t.change_24h < 8
                                and t.quote_volume_24h > 10_000_000]
        early_vol_alerts = []  # (ticker, vol_ratio, last_change)

        async def check_vol(t):
            try:
                bars = await client.get_klines(t.symbol, interval="1h", limit=25)
                if not bars or len(bars) < 22:
                    return None
                current = bars[-1]
                past20 = bars[-21:-1]  # 前20根（不含当前）
                avg_vol = sum(b.volume for b in past20) / 20
                if avg_vol <= 0:
                    return None
                vol_ratio = current.volume / avg_vol
                last_change = (current.close / current.open - 1) * 100 if current.open > 0 else 0
                if vol_ratio >= 2.5:
                    return (t, vol_ratio, last_change, current.close)
                return None
            except Exception:
                return None

        # 并发检查（限制并发数避免打爆API）
        sem = asyncio.Semaphore(20)
        async def bounded(t):
            async with sem:
                return await check_vol(t)
        results = await asyncio.gather(*[bounded(t) for t in early_vol_candidates])
        early_vol_alerts = [r for r in results if r is not None]

        # 对早期启动做技术分析验证
        print("=" * 70)
        print("🚀 早期启动信号（做多）— 涨5-40% + 负费率 + 有量")
        print("=" * 70)
        if early_pumps:
            early_pumps.sort(key=lambda t: t.change_24h, reverse=True)
            for t in early_pumps[:args.limit]:
                # 快速技术分析
                score = ""
                try:
                    klines = await client.get_klines(t.symbol, interval="1h", limit=100)
                    if klines:
                        ind = calculate_indicators(klines)
                        parts = []
                        if ind.stoch_k is not None:
                            parts.append(f"KDJ:{ind.stoch_k:.0f}/{ind.stoch_d:.0f}")
                        if ind.bollinger_pct is not None:
                            parts.append(f"%B:{ind.bollinger_pct:.2f}")
                        if ind.volume_ratio is not None:
                            parts.append(f"Vol:{ind.volume_ratio:.1f}x")
                        if ind.rsi_14 is not None:
                            parts.append(f"RSI:{ind.rsi_14:.0f}")
                        if ind.adx_14 is not None:
                            parts.append(f"ADX:{ind.adx_14:.0f}")
                        score = "  " + " | ".join(parts)
                except Exception:
                    pass
                print(
                    f"  {t.symbol:<16} +{t.change_24h:.1f}%  "
                    f"费率:{t.funding_rate:+.4f}%  "
                    f"Vol:${t.quote_volume_24h/1e6:.0f}M"
                    f"{score}"
                )
        else:
            print("  无信号")

        print()
        print("=" * 70)
        print("🔻 高点反转信号（做空）— 涨>40% + 正费率高")
        print("=" * 70)
        if top_reversals:
            top_reversals.sort(key=lambda t: t.funding_rate, reverse=True)
            for t in top_reversals[:args.limit]:
                try:
                    klines = await client.get_klines(t.symbol, interval="1h", limit=100)
                    if klines:
                        ind = calculate_indicators(klines)
                        parts = []
                        if ind.stoch_k is not None:
                            parts.append(f"KDJ:{ind.stoch_k:.0f}/{ind.stoch_d:.0f}")
                        if ind.rsi_14 is not None:
                            parts.append(f"RSI:{ind.rsi_14:.0f}")
                        if ind.bollinger_pct is not None:
                            parts.append(f"%B:{ind.bollinger_pct:.2f}")
                        score = "  " + " | ".join(parts)
                    else:
                        score = ""
                except Exception:
                    score = ""
                print(
                    f"  {t.symbol:<16} +{t.change_24h:.1f}%  "
                    f"费率:{t.funding_rate:+.4f}%  "
                    f"Vol:${t.quote_volume_24h/1e6:.0f}M"
                    f"{score}"
                )
        else:
            print("  无信号")

        print()
        print("=" * 70)
        print("📉 超卖反弹信号（做多）— 跌>15% + 负费率")
        print("=" * 70)
        if oversold:
            oversold.sort(key=lambda t: t.change_24h)
            for t in oversold[:args.limit]:
                print(
                    f"  {t.symbol:<16} {t.change_24h:+.1f}%  "
                    f"费率:{t.funding_rate:+.4f}%  "
                    f"Vol:${t.quote_volume_24h/1e6:.0f}M"
                )
        else:
            print("  无信号")

        print()
        print("=" * 70)
        print("💰 负费率轧空信号（做多）— 费率<-0.15% + 没大跌")
        print("=" * 70)
        if neg_funding:
            neg_funding.sort(key=lambda t: t.funding_rate)
            for t in neg_funding[:args.limit]:
                print(
                    f"  {t.symbol:<16} {t.change_24h:+.1f}%  "
                    f"费率:{t.funding_rate:+.4f}%  "
                    f"Vol:${t.quote_volume_24h/1e6:.0f}M"
                )
        else:
            print("  无信号")

        # 模式5: 突破做多
        print()
        print("=" * 70)
        print("🚀🚀 突破做多信号（趋势延续）— 涨>30% + 大成交量 + 费率非极端")
        print("=" * 70)
        if breakouts:
            # 去重：已在 top_reversals 里的不重复（费率高的会进反转桶）
            reversal_syms = {t.symbol for t in top_reversals}
            filtered = [t for t in breakouts if t.symbol not in reversal_syms]
            filtered.sort(key=lambda t: t.change_24h, reverse=True)
            for t in filtered[:args.limit]:
                score = ""
                try:
                    klines = await client.get_klines(t.symbol, interval="1h", limit=100)
                    if klines:
                        ind = calculate_indicators(klines)
                        parts = []
                        if ind.stoch_k is not None:
                            parts.append(f"KDJ:{ind.stoch_k:.0f}/{ind.stoch_d:.0f}")
                        if ind.bollinger_pct is not None:
                            parts.append(f"%B:{ind.bollinger_pct:.2f}")
                        if ind.volume_ratio is not None:
                            parts.append(f"Vol:{ind.volume_ratio:.1f}x")
                        if ind.rsi_14 is not None:
                            parts.append(f"RSI:{ind.rsi_14:.0f}")
                        if ind.adx_14 is not None:
                            parts.append(f"ADX:{ind.adx_14:.0f}")
                        score = "  " + " | ".join(parts)
                except Exception:
                    pass
                print(
                    f"  {t.symbol:<16} +{t.change_24h:.1f}%  "
                    f"费率:{t.funding_rate:+.4f}%  "
                    f"Vol:${t.quote_volume_24h/1e6:.0f}M"
                    f"{score}"
                )
        else:
            print("  无信号")

        # 模式6: 异常量能
        print()
        print("=" * 70)
        print("💥 异常量能（资金异动）— 24h成交量>$200M")
        print("=" * 70)
        if vol_anomalies:
            # 去重：已经在其他桶里的不重复
            other_syms = ({t.symbol for t in early_pumps}
                          | {t.symbol for t in top_reversals}
                          | {t.symbol for t in breakouts})
            filtered = [t for t in vol_anomalies if t.symbol not in other_syms]
            filtered.sort(key=lambda t: t.quote_volume_24h, reverse=True)
            for t in filtered[:args.limit]:
                print(
                    f"  {t.symbol:<16} {t.change_24h:+.1f}%  "
                    f"费率:{t.funding_rate:+.4f}%  "
                    f"Vol:${t.quote_volume_24h/1e6:.0f}M"
                )
        else:
            print("  无信号")

        # 模式7: 早期量能异动（最前哨信号）
        print()
        print("=" * 70)
        print("⚡ 早期量能异动（前哨信号）— 微涨 + 1h量>20h均量2.5x")
        print("=" * 70)
        if early_vol_alerts:
            early_vol_alerts.sort(key=lambda x: x[1], reverse=True)  # 按vol_ratio排序
            for t, vol_ratio, last_change, price in early_vol_alerts[:args.limit]:
                print(
                    f"  {t.symbol:<16} 24h:{t.change_24h:+.1f}%  "
                    f"1h:{last_change:+.1f}%  "
                    f"量:{vol_ratio:.1f}x  "
                    f"价:{price:.6f}  "
                    f"费率:{t.funding_rate:+.4f}%  "
                    f"Vol24:${t.quote_volume_24h/1e6:.0f}M"
                )
        else:
            print("  无信号")

        # 模式8: 15分钟共振做多
        print()
        print("=" * 70)
        print("🎯 15分钟共振做多（MA+量+OI+费率+Boll至少4项）")
        print("=" * 70)
        if resonance_alerts:
            resonance_alerts.sort(key=lambda x: x[1], reverse=True)  # 按score排序
            for t, score, d in resonance_alerts[:args.limit]:
                print(
                    f"  {t.symbol:<16} {score}/5  "
                    f"价:{d['price']:.6g}  "
                    f"MA:{d['ma']}  Vol:{d['vol']}  OI:{d['oi']}  FR:{d['fr']}  %B:{d['b']}"
                )
        else:
            print("  无信号")

        total = (len(early_pumps) + len(top_reversals) + len(oversold) + len(neg_funding)
                 + len(breakouts) + len(vol_anomalies) + len(early_vol_alerts)
                 + len(resonance_alerts))
        print(f"\n共扫描 {len(candidates)} 币种，发现 {total} 个信号")
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

    p = sub.add_parser("scan", help="扫描全市场早期启动/反转信号")
    p.add_argument("--limit", type=int, default=8, help="每类最多显示几个")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    cmd = {"tickers": cmd_tickers, "detail": cmd_detail, "analysis": cmd_analysis,
           "funding": cmd_funding, "oi": cmd_oi, "scan": cmd_scan}[args.command]
    asyncio.run(cmd(args))


if __name__ == "__main__":
    main()
