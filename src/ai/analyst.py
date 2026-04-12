"""AI analyst — calls Claude API to evaluate trade signals and review portfolios."""

from __future__ import annotations

import json
import re

import structlog
import anthropic

from config.settings import settings
from src.ai.prompts import (
    MARKET_ANALYSIS_PROMPT,
    PORTFOLIO_REVIEW_PROMPT,
    QUICK_ANALYSIS_PROMPT,
    format_klines_for_prompt,
)
from src.strategy.base import TradeSignal

logger = structlog.get_logger()


class AIAnalyst:
    """Wraps Claude API for trade analysis."""

    def __init__(self):
        self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self.model = settings.claude_model

    async def analyze_trade(
        self,
        signal: TradeSignal,
        candidate,
        klines: list,
        trade_memory: str = "",
        depth: str = "standard",
    ) -> dict:
        """AI analysis of a single trade signal.

        Args:
            signal: The strategy-generated trade signal.
            candidate: The screened candidate with indicators.
            klines: Recent kline data.
            trade_memory: Formatted trade history context.
            depth: "quick" / "standard" / "deep" — controls prompt detail.

        Returns:
            Parsed JSON dict with approve, confidence, adjustments, etc.
        """
        if depth == "quick":
            prompt = QUICK_ANALYSIS_PROMPT.format(
                symbol=candidate.symbol,
                price=candidate.price,
                change_24h=candidate.change_24h,
                signal_direction=signal.signal.value,
                rsi_14=candidate.rsi_14,
                funding_rate=candidate.funding_rate or 0,
                strategy_name=signal.strategy_name,
                reasoning=signal.reasoning,
            )
            max_tokens = 300
        else:
            prompt = MARKET_ANALYSIS_PROMPT.format(
                symbol=candidate.symbol,
                market=candidate.market,
                price=candidate.price,
                change_24h=candidate.change_24h,
                quote_volume=f"{candidate.quote_volume_24h:,.0f}",
                funding_rate=candidate.funding_rate or 0,
                rsi_14=candidate.rsi_14,
                macd_signal=candidate.macd_signal,
                ema_trend=candidate.ema_trend,
                volume_ratio=candidate.volume_ratio,
                atr_percent=candidate.atr_percent,
                strategy_name=signal.strategy_name,
                signal_direction=signal.signal.value,
                confidence=signal.confidence,
                reasoning=signal.reasoning,
                tags=", ".join(signal.tags) if signal.tags else "none",
                recent_klines=format_klines_for_prompt(klines),
                trade_memory=trade_memory or "无历史记录",
            )
            max_tokens = 1000

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.content[0].text
            result = _parse_json_response(raw)
            logger.info(
                "ai_analysis_complete",
                symbol=candidate.symbol,
                approved=result.get("approve"),
                confidence=result.get("confidence"),
            )
            return result

        except anthropic.APIError as e:
            logger.error("ai_api_error", error=str(e))
            return _fallback_response(signal)
        except Exception as e:
            logger.error("ai_analysis_error", error=str(e))
            return _fallback_response(signal)

    async def review_portfolio(
        self,
        positions: list[dict],
        balance: dict,
        pending_signals: list[dict],
        performance_summary: str = "",
    ) -> dict:
        """AI review of the full portfolio."""
        prompt = PORTFOLIO_REVIEW_PROMPT.format(
            positions_json=json.dumps(positions, indent=2, ensure_ascii=False),
            total_balance=f"{balance.get('total', 0):,.2f}",
            used_margin=f"{balance.get('used_margin', 0):,.2f}",
            available_balance=f"{balance.get('available', 0):,.2f}",
            daily_pnl=f"{balance.get('daily_pnl', 0):,.2f}",
            pending_signals=json.dumps(pending_signals, indent=2, ensure_ascii=False),
            performance_summary=performance_summary or "无数据",
        )

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1500,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.content[0].text
            return _parse_json_response(raw)

        except Exception as e:
            logger.error("ai_portfolio_review_error", error=str(e))
            return {
                "overall_risk_level": "medium",
                "position_adjustments": [],
                "new_signal_approvals": [],
                "risk_warnings": [f"AI分析不可用: {e}"],
                "reasoning": "AI服务暂时不可用，请人工审核。",
            }


def _parse_json_response(raw: str) -> dict:
    """Extract JSON from AI response, handling markdown code blocks."""
    # Try to find JSON in code blocks first
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", raw, re.DOTALL)
    if match:
        raw = match.group(1)

    # Strip any leading/trailing whitespace
    raw = raw.strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Try to find any JSON object in the text
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
        logger.warning("ai_json_parse_failed", raw=raw[:200])
        return {"approve": False, "confidence": 0.0, "reasoning": f"无法解析AI响应: {raw[:100]}"}


def _fallback_response(signal: TradeSignal) -> dict:
    """Fallback when AI is unavailable — conservative pass-through."""
    return {
        "approve": signal.confidence >= 0.7,
        "confidence": signal.confidence * 0.8,
        "adjusted_entry": None,
        "adjusted_stop_loss": None,
        "adjusted_take_profit": None,
        "position_size_suggestion": "keep",
        "risk_notes": "AI分析不可用，使用策略原始信号（降低置信度）",
        "reasoning": "Fallback: AI service unavailable",
    }
