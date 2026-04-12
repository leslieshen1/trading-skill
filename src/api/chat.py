"""Interactive AI trading agent — Claude with live market data tools.

This module exposes a /api/chat endpoint that lets the user converse with an AI
trading assistant. The assistant has tool_use access to:
  - Live Binance market data (tickers, klines, funding rates, open interest)
  - Technical indicator calculations
  - Account balance & positions (testnet)
  - Order placement (testnet)
  - Conversation memory
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import anthropic
import structlog
from fastapi import APIRouter

from config.settings import settings
from src.data.binance_futures import BinanceFuturesClient
from src.data.binance_spot import BinanceSpotClient
from src.execution.binance_client import BinanceTradingClient
from src.strategy.indicators import calculate_indicators

logger = structlog.get_logger()
router = APIRouter()

# ── Memory ──────────────────────────────────────────────────────────────────

MEMORY_DIR = Path("data/memory")
MEMORY_DIR.mkdir(parents=True, exist_ok=True)
CONVERSATION_FILE = MEMORY_DIR / "conversations.jsonl"
TRADE_MEMORY_FILE = MEMORY_DIR / "trade_memory.json"

def _load_trade_memory() -> dict:
    if TRADE_MEMORY_FILE.exists():
        return json.loads(TRADE_MEMORY_FILE.read_text())
    return {"trades": [], "lessons": [], "preferences": []}

def _save_trade_memory(mem: dict):
    TRADE_MEMORY_FILE.write_text(json.dumps(mem, ensure_ascii=False, indent=2))

def _append_conversation(role: str, content: str):
    with open(CONVERSATION_FILE, "a") as f:
        f.write(json.dumps({
            "ts": time.time(),
            "role": role,
            "content": content[:2000],
        }, ensure_ascii=False) + "\n")

def _load_recent_conversations(n: int = 50) -> list[dict]:
    if not CONVERSATION_FILE.exists():
        return []
    lines = CONVERSATION_FILE.read_text().strip().split("\n")
    recent = lines[-n:] if len(lines) > n else lines
    return [json.loads(line) for line in recent if line.strip()]


# ── Tool Definitions ────────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "get_top_tickers",
        "description": "获取交易量最大的代币行情。返回 symbol, price, 24h涨跌幅, 成交量, 资金费率等。market 可选 futures_um 或 spot。",
        "input_schema": {
            "type": "object",
            "properties": {
                "market": {"type": "string", "enum": ["futures_um", "spot"], "default": "futures_um"},
                "limit": {"type": "integer", "default": 20, "description": "返回数量"},
            },
        },
    },
    {
        "name": "get_symbol_detail",
        "description": "获取单个代币的详细信息：当前价格、24h数据、资金费率、持仓量。",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "交易对，如 BTCUSDT"},
                "market": {"type": "string", "enum": ["futures_um", "spot"], "default": "futures_um"},
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "get_technical_analysis",
        "description": "获取代币的技术分析：RSI, MACD, EMA, 布林带, ATR, ADX, KDJ等指标。可选不同时间周期。",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "交易对，如 BTCUSDT"},
                "interval": {"type": "string", "enum": ["5m", "15m", "1h", "4h", "1d"], "default": "1h"},
                "market": {"type": "string", "enum": ["futures_um", "spot"], "default": "futures_um"},
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "get_funding_rates",
        "description": "获取资金费率数据。可以查单个币种的历史资金费率。",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "交易对，如 BTCUSDT。留空获取所有"},
                "limit": {"type": "integer", "default": 10},
            },
        },
    },
    {
        "name": "get_account_balance",
        "description": "获取账户余额和持仓信息（Testnet）。",
        "input_schema": {
            "type": "object",
            "properties": {
                "market": {"type": "string", "enum": ["futures_um", "spot"], "default": "futures_um"},
            },
        },
    },
    {
        "name": "get_positions",
        "description": "获取当前持仓列表（合约）。",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "place_order",
        "description": "下单交易（Testnet）。包括开仓和平仓。会返回订单结果。",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "交易对"},
                "side": {"type": "string", "enum": ["BUY", "SELL"]},
                "quantity": {"type": "number", "description": "数量"},
                "order_type": {"type": "string", "enum": ["MARKET", "LIMIT"], "default": "MARKET"},
                "price": {"type": "number", "description": "限价单价格（LIMIT时必填）"},
                "leverage": {"type": "integer", "description": "杠杆倍数，默认不改变"},
                "reason": {"type": "string", "description": "交易理由"},
            },
            "required": ["symbol", "side", "quantity", "reason"],
        },
    },
    {
        "name": "remember",
        "description": "保存重要信息到记忆中，包括交易经验、用户偏好、市场观察等。",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "enum": ["trade", "lesson", "preference", "observation"]},
                "content": {"type": "string", "description": "要记住的内容"},
            },
            "required": ["category", "content"],
        },
    },
    {
        "name": "recall_memory",
        "description": "回忆之前保存的记忆和交易记录。",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "enum": ["all", "trades", "lessons", "preferences"], "default": "all"},
            },
        },
    },
]


# ── Tool Execution ──────────────────────────────────────────────────────────

futures_client = BinanceFuturesClient()
spot_client = BinanceSpotClient()


async def execute_tool(name: str, params: dict) -> str:
    """Execute a tool and return the result as a string."""
    try:
        if name == "get_top_tickers":
            market = params.get("market", "futures_um")
            limit = params.get("limit", 20)
            client = futures_client if market == "futures_um" else spot_client
            tickers = await client.get_all_tickers()
            # Sort by quote volume, take top N
            tickers.sort(key=lambda t: t.quote_volume_24h, reverse=True)
            tickers = tickers[:limit]
            result = []
            for t in tickers:
                item = {
                    "symbol": t.symbol,
                    "price": t.price,
                    "change_24h%": round(t.change_24h, 2),
                    "volume_usdt": round(t.quote_volume_24h),
                }
                if hasattr(t, "funding_rate") and t.funding_rate is not None:
                    item["funding_rate%"] = round(t.funding_rate, 4)
                result.append(item)
            return json.dumps(result, ensure_ascii=False)

        elif name == "get_symbol_detail":
            symbol = params["symbol"].upper()
            market = params.get("market", "futures_um")
            client = futures_client if market == "futures_um" else spot_client
            tickers = await client.get_all_tickers()
            match = next((t for t in tickers if t.symbol == symbol), None)
            if not match:
                return f"未找到 {symbol}"
            info = {
                "symbol": match.symbol,
                "price": match.price,
                "change_24h%": round(match.change_24h, 2),
                "high_24h": match.high_24h,
                "low_24h": match.low_24h,
                "volume_usdt": round(match.quote_volume_24h),
                "trade_count": match.trade_count,
            }
            if market == "futures_um" and hasattr(match, "funding_rate"):
                info["funding_rate%"] = round(match.funding_rate, 4)
                info["mark_price"] = match.mark_price
                info["index_price"] = match.index_price
                try:
                    oi = await futures_client.get_open_interest(symbol)
                    info["open_interest"] = oi
                except Exception:
                    pass
            return json.dumps(info, ensure_ascii=False)

        elif name == "get_technical_analysis":
            symbol = params["symbol"].upper()
            interval = params.get("interval", "1h")
            market = params.get("market", "futures_um")
            client = futures_client if market == "futures_um" else spot_client
            klines = await client.get_klines(symbol, interval=interval, limit=100)
            if not klines:
                return f"{symbol} 无K线数据"
            indicators = calculate_indicators(klines)
            # Get current price
            current_price = klines[-1].close
            result = {"symbol": symbol, "interval": interval, "price": current_price}
            for field in [
                "rsi_14", "macd_value", "macd_signal_value", "macd_histogram", "macd_signal",
                "ema_20", "ema_50", "ema_trend",
                "bollinger_upper", "bollinger_lower", "bollinger_mid", "bollinger_pct",
                "atr_14", "atr_percent", "volume_ratio",
                "adx_14", "stoch_k", "stoch_d",
            ]:
                val = getattr(indicators, field, None)
                if val is not None:
                    result[field] = val
            return json.dumps(result, ensure_ascii=False)

        elif name == "get_funding_rates":
            symbol = params.get("symbol", "").upper() or None
            limit = params.get("limit", 10)
            rates = await futures_client.get_funding_rates(symbol=symbol, limit=limit)
            result = [
                {"symbol": r.symbol, "rate%": round(r.funding_rate, 4), "time": r.funding_time}
                for r in rates
            ]
            return json.dumps(result, ensure_ascii=False)

        elif name == "get_account_balance":
            market = params.get("market", "futures_um")
            trading_client = BinanceTradingClient(market=market)
            try:
                balance = await trading_client.get_balance()
                return json.dumps(balance, ensure_ascii=False)
            except Exception as e:
                return f"获取余额失败（请检查API Key配置）: {e}"
            finally:
                await trading_client.close()

        elif name == "get_positions":
            trading_client = BinanceTradingClient(market="futures_um")
            try:
                positions = await trading_client.get_positions()
                if not positions:
                    return "当前没有持仓"
                return json.dumps(positions, ensure_ascii=False)
            except Exception as e:
                return f"获取持仓失败: {e}"
            finally:
                await trading_client.close()

        elif name == "place_order":
            symbol = params["symbol"].upper()
            side = params["side"]
            quantity = params["quantity"]
            order_type = params.get("order_type", "MARKET")
            price = params.get("price")
            leverage = params.get("leverage")
            reason = params.get("reason", "")

            trading_client = BinanceTradingClient(market="futures_um")
            try:
                if leverage:
                    await trading_client.set_leverage(symbol, leverage)

                result = await trading_client.place_order(
                    symbol=symbol,
                    side=side,
                    order_type=order_type,
                    quantity=quantity,
                    price=price,
                )

                # Save trade to memory
                mem = _load_trade_memory()
                mem["trades"].append({
                    "ts": time.time(),
                    "symbol": symbol,
                    "side": side,
                    "quantity": quantity,
                    "order_type": order_type,
                    "reason": reason,
                    "result": {
                        "orderId": result.get("orderId"),
                        "status": result.get("status"),
                        "avgPrice": result.get("avgPrice"),
                    },
                })
                _save_trade_memory(mem)

                return json.dumps({
                    "success": True,
                    "orderId": result.get("orderId"),
                    "status": result.get("status"),
                    "symbol": symbol,
                    "side": side,
                    "quantity": quantity,
                    "avgPrice": result.get("avgPrice"),
                    "reason": reason,
                }, ensure_ascii=False)
            except Exception as e:
                return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)
            finally:
                await trading_client.close()

        elif name == "remember":
            category = params["category"]
            content = params["content"]
            mem = _load_trade_memory()
            key = category + "s" if category != "trade" else "trades"
            if key not in mem:
                mem[key] = []
            mem[key].append({"ts": time.time(), "content": content})
            _save_trade_memory(mem)
            return f"已记住: [{category}] {content}"

        elif name == "recall_memory":
            category = params.get("category", "all")
            mem = _load_trade_memory()
            if category == "all":
                return json.dumps(mem, ensure_ascii=False, default=str)
            key = category
            return json.dumps(mem.get(key, []), ensure_ascii=False, default=str)

        else:
            return f"未知工具: {name}"

    except Exception as e:
        logger.error("tool_execution_error", tool=name, error=str(e))
        return f"工具执行出错: {e}"


# ── System Prompt ───────────────────────────────────────────────────────────

def build_system_prompt() -> str:
    mem = _load_trade_memory()
    memory_context = ""
    if mem.get("lessons"):
        memory_context += "\n## 交易经验教训\n"
        for item in mem["lessons"][-10:]:
            memory_context += f"- {item['content']}\n"
    if mem.get("preferences"):
        memory_context += "\n## 用户偏好\n"
        for item in mem["preferences"][-10:]:
            memory_context += f"- {item['content']}\n"
    if mem.get("observations"):
        memory_context += "\n## 市场观察\n"
        for item in mem["observations"][-5:]:
            memory_context += f"- {item['content']}\n"
    recent_trades = mem.get("trades", [])[-5:]
    if recent_trades:
        memory_context += "\n## 最近交易\n"
        for t in recent_trades:
            memory_context += f"- {t.get('symbol')} {t.get('side')} qty={t.get('quantity')} | 理由: {t.get('reason', 'N/A')}\n"

    return f"""你是一个专业的加密货币交易助手。你可以实时查看市场数据、分析行情、帮用户下单交易。

## 你的能力
- 查看所有加密货币实时行情（价格、涨跌幅、成交量、资金费率）
- 技术分析（RSI、MACD、EMA、布林带、ATR、ADX、KDJ）
- 查看账户余额和持仓
- 帮用户下单（当前连接的是 Binance {'Testnet' if settings.binance_testnet else '实盘'}）
- 记忆和回忆交易经验

## 工作原则
1. **每次交易都要给出清晰的理由**：包括技术面分析、市场情绪、风险评估
2. **主动风险提醒**：发现异常波动、高杠杆、集中持仓时主动提醒
3. **交易后跟踪**：记住每笔交易的理由，结束后总结得失
4. **积累记忆**：记住用户的交易风格、偏好、教训，越用越懂你
5. **中文交流**，数据用简洁表格展示

## 回答风格
- 简洁专业，直击要点
- 数据用表格或要点列表展示
- 给建议时说明理由和风险
- 下单前必须确认用户同意
{memory_context}"""


# ── Chat Endpoint ───────────────────────────────────────────────────────────

from pydantic import BaseModel

class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None

class ChatResponse(BaseModel):
    reply: str
    tools_used: list[str] = []


# Store conversation history in memory (per session)
_conversations: dict[str, list[dict]] = {}


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    conv_id = req.conversation_id or "default"

    # Get or init conversation
    if conv_id not in _conversations:
        _conversations[conv_id] = []
    messages = _conversations[conv_id]

    # Add user message
    messages.append({"role": "user", "content": req.message})
    _append_conversation("user", req.message)

    # Call Claude with tools
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    tools_used = []

    try:
        # Agentic loop — keep calling Claude until it stops using tools
        while True:
            response = client.messages.create(
                model=settings.claude_model,
                max_tokens=4096,
                system=build_system_prompt(),
                tools=TOOLS,
                messages=messages,
            )

            # Collect text and tool use blocks
            text_parts = []
            tool_uses = []
            for block in response.content:
                if block.type == "text":
                    text_parts.append(block.text)
                elif block.type == "tool_use":
                    tool_uses.append(block)

            if not tool_uses:
                # No more tool calls — we're done
                reply = "\n".join(text_parts)
                messages.append({"role": "assistant", "content": response.content})
                break

            # Process tool calls
            messages.append({"role": "assistant", "content": response.content})
            tool_results = []
            for tool_use in tool_uses:
                tools_used.append(tool_use.name)
                logger.info("tool_call", tool=tool_use.name, params=tool_use.input)
                result = await execute_tool(tool_use.name, tool_use.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": result,
                })
            messages.append({"role": "user", "content": tool_results})

            # If stop_reason is end_turn (not tool_use), also break
            if response.stop_reason == "end_turn":
                reply = "\n".join(text_parts) if text_parts else "Done."
                break

        # Keep conversation manageable (last 40 messages)
        if len(messages) > 40:
            _conversations[conv_id] = messages[-40:]

        _append_conversation("assistant", reply)
        return ChatResponse(reply=reply, tools_used=tools_used)

    except anthropic.AuthenticationError:
        return ChatResponse(
            reply="❌ Anthropic API Key 未配置或无效。请在 .env 文件中设置 ANTHROPIC_API_KEY。",
            tools_used=[],
        )
    except Exception as e:
        logger.error("chat_error", error=str(e))
        return ChatResponse(reply=f"出错了: {e}", tools_used=[])
