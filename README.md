# Crypto Trading Agent

Claude Code skill for crypto trading. Real-time Binance market data, technical analysis, and trade execution — all through `/trade` command.

## Quick Start

```bash
# 1. Clone
git clone https://github.com/leslieshen1/trading.git
cd trading

# 2. Install dependencies
pip install httpx structlog pydantic-settings ta pandas numpy

# 3. Configure API keys
cp .env.example .env
# Edit .env, fill in BINANCE_API_KEY and BINANCE_API_SECRET

# 4. Use in Claude Code
/trade 现在哪些币涨得好？
/trade 分析一下 BTC
/trade 查看我的持仓
```

## Features

- **Real-time market data** — Top movers, price, volume, funding rates
- **Technical analysis** — RSI, MACD, EMA, Bollinger Bands, ATR, ADX, KDJ
- **Trading** — Place/cancel orders, check positions and balance
- **Risk awareness** — Alerts on high volatility, leverage, abnormal funding rates

## Skill Commands

```
/trade 涨幅榜              → 查看涨跌排行
/trade 分析 ETHUSDT 4h     → 技术分析
/trade 查看持仓             → 当前持仓
/trade BTC 什么情况         → 币种详情
```

## CLI Tools

Can also be used standalone:

```bash
python scripts/market.py tickers --limit 10          # Top 10 by volume
python scripts/market.py analysis BTCUSDT --interval 4h  # Technical analysis
python scripts/trade.py balance                      # Account balance
python scripts/trade.py positions                    # Open positions
```

## Project Structure

```
.claude/skills/trade/SKILL.md   # Claude Code skill definition
scripts/market.py               # Market data CLI
scripts/trade.py                # Trading CLI
src/data/                       # Binance API clients (spot, futures, coinm, websocket)
src/strategy/                   # Strategy engine, indicators, built-in strategies
src/execution/                  # Order execution, position management
src/risk/                       # Risk manager, position sizing, circuit breaker
src/ai/                         # AI analyst (Claude), decision maker
src/backtest/                   # Backtesting engine
config/                         # Settings, strategy YAML configs
```

## Requirements

- Python 3.9+
- Binance API key (testnet or production)
- Claude Code (for `/trade` skill)
