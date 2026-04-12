"""Decision aggregator — combines strategy signals, AI analysis, and risk checks
into a final trade decision.

Priority: Risk > AI > Strategy signal
  - Risk says no → always no
  - AI says no → usually no (unless strategy confidence is very high)
  - Strategy + AI + Risk all pass → execute
"""

from __future__ import annotations

from dataclasses import dataclass, field

import structlog

from src.ai.analyst import AIAnalyst
from src.ai.memory import TradingMemory
from src.strategy.base import TradeSignal

logger = structlog.get_logger()


@dataclass
class RiskCheckResult:
    passed: bool
    reason: str = ""


@dataclass
class FinalDecision:
    execute: bool
    signal: TradeSignal | None = None
    ai_analysis: dict | None = None
    reason: str = ""


class DecisionMaker:
    """Aggregates strategy signals, AI analysis, and risk checks."""

    def __init__(
        self,
        ai_analyst: AIAnalyst,
        trading_memory: TradingMemory,
        strategy_configs: dict | None = None,
    ):
        self.ai = ai_analyst
        self.memory = trading_memory
        self.strategy_configs = strategy_configs or {}
        # risk_manager will be injected in Phase 4
        self.risk_manager = None

    def set_risk_manager(self, risk_manager) -> None:
        self.risk_manager = risk_manager

    async def make_decision(
        self,
        signal: TradeSignal,
        candidate,
        klines: list,
    ) -> FinalDecision:
        """Full decision pipeline: risk pre-check → AI analysis → risk final check."""

        # 1. Risk pre-check (if risk manager is available)
        if self.risk_manager:
            risk_check = await self.risk_manager.pre_check(signal)
            if not risk_check.passed:
                logger.info(
                    "decision_risk_rejected",
                    symbol=signal.symbol,
                    reason=risk_check.reason,
                )
                return FinalDecision(execute=False, reason=f"风控拒绝: {risk_check.reason}")

        # 2. AI analysis (if configured for this strategy)
        ai_result = None
        strategy_ai_config = self._get_ai_config(signal.strategy_name)
        if strategy_ai_config.get("enabled", False) and strategy_ai_config.get("confirm_entry", False):
            trade_context = await self.memory.get_recent_context(symbol=signal.symbol)
            depth = strategy_ai_config.get("analysis_depth", "standard")

            ai_result = await self.ai.analyze_trade(
                signal=signal,
                candidate=candidate,
                klines=klines,
                trade_memory=trade_context,
                depth=depth,
            )

            if not ai_result.get("approve", False):
                # AI rejected — but allow override if strategy confidence is very high
                if signal.confidence >= 0.9:
                    logger.warning(
                        "decision_ai_override",
                        symbol=signal.symbol,
                        strategy_confidence=signal.confidence,
                        ai_confidence=ai_result.get("confidence"),
                    )
                else:
                    logger.info(
                        "decision_ai_rejected",
                        symbol=signal.symbol,
                        reason=ai_result.get("reasoning", "unknown"),
                    )
                    return FinalDecision(
                        execute=False,
                        ai_analysis=ai_result,
                        reason=f"AI拒绝: {ai_result.get('reasoning', 'unknown')}",
                    )

        # 3. Merge signal with AI adjustments
        final_signal = self._merge_signal(signal, ai_result)

        # 4. Final risk check (if risk manager is available)
        if self.risk_manager:
            final_risk = await self.risk_manager.final_check(final_signal)
            if not final_risk.passed:
                return FinalDecision(
                    execute=False,
                    reason=f"最终风控拒绝: {final_risk.reason}",
                )

        logger.info(
            "decision_approved",
            symbol=final_signal.symbol,
            direction=final_signal.signal.value,
            confidence=final_signal.confidence,
        )
        return FinalDecision(
            execute=True,
            signal=final_signal,
            ai_analysis=ai_result,
            reason="策略+AI+风控 全部通过" if ai_result else "策略+风控 通过（AI未启用）",
        )

    def _get_ai_config(self, strategy_name: str) -> dict:
        """Get AI configuration for a specific strategy."""
        config = self.strategy_configs.get(strategy_name, {})
        return config.get("ai", {})

    def _merge_signal(self, signal: TradeSignal, ai_result: dict | None) -> TradeSignal:
        """Apply AI adjustments to the original signal."""
        if not ai_result:
            return signal

        # Create a new signal with potential adjustments
        merged = TradeSignal(
            strategy_name=signal.strategy_name,
            symbol=signal.symbol,
            market=signal.market,
            signal=signal.signal,
            confidence=ai_result.get("confidence", signal.confidence),
            entry_price=ai_result.get("adjusted_entry") or signal.entry_price,
            stop_loss=ai_result.get("adjusted_stop_loss") or signal.stop_loss,
            take_profit=ai_result.get("adjusted_take_profit") or signal.take_profit,
            position_size_pct=signal.position_size_pct,
            reasoning=f"[策略] {signal.reasoning} | [AI] {ai_result.get('reasoning', '')}",
            tags=signal.tags,
            timestamp=signal.timestamp,
        )

        # Adjust position size based on AI suggestion
        size_suggestion = ai_result.get("position_size_suggestion", "keep")
        if size_suggestion == "increase":
            merged.position_size_pct = min(signal.position_size_pct * 1.5, 5.0)
        elif size_suggestion == "decrease":
            merged.position_size_pct = signal.position_size_pct * 0.5

        return merged
