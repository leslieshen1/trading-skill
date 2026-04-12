"""Funding rate arbitrage strategy.

Opens positions against extreme funding rates, expecting mean reversion.
High positive funding → short (collect funding). High negative funding → long.
"""

from __future__ import annotations

from src.strategy.base import BaseStrategy, Signal, TradeSignal


class FundingArbStrategy(BaseStrategy):

    async def evaluate(self, candidate, klines: list) -> TradeSignal | None:
        entry_cfg = self.config.get("entry", {})
        conditions = entry_cfg.get("conditions", [])
        direction = entry_cfg.get("direction", "short")

        matched_main = self.check_conditions(candidate, conditions)
        matched_alt = False
        alt_direction = entry_cfg.get("alt_direction", "long")

        if not matched_main:
            alt_conditions = entry_cfg.get("alt_conditions")
            if alt_conditions:
                matched_alt = self.check_conditions(candidate, alt_conditions)

        if not matched_main and not matched_alt:
            return None

        if matched_alt:
            direction = alt_direction

        exit_cfg = self.config.get("exit", {})
        stop_pct = exit_cfg.get("stop_loss", 1.5)
        tp_pct = exit_cfg.get("take_profit", 3.0)
        stop_loss, take_profit = self.compute_stop_take(
            candidate.price, direction, stop_pct, tp_pct
        )

        # Confidence scales with funding rate extremity
        confidence = 0.5
        if candidate.funding_rate is not None:
            abs_fr = abs(candidate.funding_rate)
            if abs_fr > 0.2:
                confidence += 0.2
            elif abs_fr > 0.1:
                confidence += 0.1
        if candidate.rsi_14 is not None:
            if direction == "short" and candidate.rsi_14 > 75:
                confidence += 0.1
            elif direction == "long" and candidate.rsi_14 < 25:
                confidence += 0.1

        confidence = min(confidence, 1.0)

        pos_cfg = self.config.get("position", {})
        signal_type = Signal.LONG if direction == "long" else Signal.SHORT

        return TradeSignal(
            strategy_name=self.name,
            symbol=candidate.symbol,
            market=candidate.market,
            signal=signal_type,
            confidence=round(confidence, 2),
            entry_price=candidate.price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            position_size_pct=pos_cfg.get("risk_per_trade", 0.5),
            reasoning=(
                f"Funding arb {direction}: funding_rate={candidate.funding_rate:.4f}%, "
                f"RSI={candidate.rsi_14}"
            ),
            tags=candidate.tags if candidate.tags else [],
        )
