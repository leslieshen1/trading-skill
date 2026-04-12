"""Prompt templates for Claude AI analysis."""

from __future__ import annotations

MARKET_ANALYSIS_PROMPT = """\
你是一个专业的加密货币交易分析师。根据以下市场数据，评估该交易机会。

## 币种信息
- 交易对: {symbol}
- 市场: {market}
- 当前价格: {price}
- 24h涨跌: {change_24h}%
- 24h成交额: ${quote_volume}
- 资金费率: {funding_rate}%

## 技术指标
- RSI(14): {rsi_14}
- MACD: {macd_signal}
- EMA趋势: {ema_trend}
- 量比: {volume_ratio}x
- 波动率(ATR%): {atr_percent}%

## 策略信号
- 策略名称: {strategy_name}
- 方向: {signal_direction}
- 策略置信度: {confidence}
- 触发原因: {reasoning}
- 特征标签: {tags}

## 最近K线 (最近20根1h K线)
{recent_klines}

## 历史交易记忆
{trade_memory}

## 任务
请分析:
1. 该策略信号是否合理
2. 当前市场环境是否适合该交易
3. 有哪些潜在风险
4. 建议的入场/止损/止盈价位调整

请严格用以下 JSON 格式回复（不要添加其他文字）:
```json
{{
  "approve": true或false,
  "confidence": 0.0到1.0之间的数值,
  "adjusted_entry": 数值或null,
  "adjusted_stop_loss": 数值或null,
  "adjusted_take_profit": 数值或null,
  "position_size_suggestion": "increase"或"keep"或"decrease",
  "risk_notes": "风险提示...",
  "reasoning": "分析理由..."
}}
```"""

PORTFOLIO_REVIEW_PROMPT = """\
你是一个投资组合管理顾问。审查当前持仓并提出建议。

## 当前持仓
{positions_json}

## 账户信息
- 总资金: ${total_balance}
- 已用保证金: ${used_margin}
- 可用余额: ${available_balance}
- 当日PnL: ${daily_pnl}

## 待执行信号
{pending_signals}

## 历史交易表现
{performance_summary}

## 任务
1. 审查当前持仓的风险暴露
2. 评估待执行信号与现有持仓的关联性
3. 是否需要调整仓位
4. 整体风险评估

请严格用以下 JSON 格式回复（不要添加其他文字）:
```json
{{
  "overall_risk_level": "low"或"medium"或"high"或"critical",
  "position_adjustments": [
    {{
      "symbol": "交易对",
      "action": "hold"或"reduce"或"close"或"add",
      "reason": "原因"
    }}
  ],
  "new_signal_approvals": [
    {{
      "symbol": "交易对",
      "approve": true或false,
      "reason": "原因"
    }}
  ],
  "risk_warnings": ["警告1", "警告2"],
  "reasoning": "整体分析..."
}}
```"""

QUICK_ANALYSIS_PROMPT = """\
加密货币交易快速评估。

币种: {symbol} | 价格: {price} | 24h: {change_24h}%
方向: {signal_direction} | RSI: {rsi_14} | 资金费率: {funding_rate}%
策略: {strategy_name} | 原因: {reasoning}

用JSON回复: {{"approve": bool, "confidence": float, "risk_notes": "..."}}"""


def format_klines_for_prompt(klines: list, limit: int = 20) -> str:
    """Format recent klines into a readable table for the prompt."""
    if not klines:
        return "无K线数据"

    recent = klines[-limit:]
    lines = ["时间 | 开盘 | 最高 | 最低 | 收盘 | 成交量"]
    lines.append("---|---|---|---|---|---")

    for k in recent:
        open_time = getattr(k, "open_time", 0)
        lines.append(
            f"{open_time} | "
            f"{_fmt(getattr(k, 'open', 0))} | "
            f"{_fmt(getattr(k, 'high', 0))} | "
            f"{_fmt(getattr(k, 'low', 0))} | "
            f"{_fmt(getattr(k, 'close', 0))} | "
            f"{_fmt(getattr(k, 'volume', 0))}"
        )
    return "\n".join(lines)


def _fmt(v: float) -> str:
    if v > 1000:
        return f"{v:.2f}"
    if v > 1:
        return f"{v:.4f}"
    return f"{v:.8f}"
