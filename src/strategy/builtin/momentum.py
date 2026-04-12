"""Momentum / trend-following strategy.

Looks for strong directional moves confirmed by volume and trend indicators.
"""

from __future__ import annotations

from src.strategy.base import BaseStrategy, Signal, TradeSignal


class MomentumStrategy(BaseStrategy):

    async def evaluate(self, candidate, klines: list) -> TradeSignal | None:
        entry_cfg = self.config.get("entry", {})
        conditions = entry_cfg.get("conditions", [])
        direction = entry_cfg.get("direction", "long")

        if not self.check_conditions(candidate, conditions):
            return None

        exit_cfg = self.config.get("exit", {})
        stop_pct = exit_cfg.get("stop_loss", 2.0)
        tp_pct = exit_cfg.get("take_profit", 5.0)

        stop_loss, take_profit = self.compute_stop_take(
            candidate.price, direction, stop_pct, tp_pct
        )

        # Confidence based on indicator alignment
        confidence = 0.5
        if candidate.volume_ratio and candidate.volume_ratio > 3:
            confidence += 0.1
        if candidate.ema_trend == "above" and direction == "long":
            confidence += 0.1
        if candidate.ema_trend == "below" and direction == "short":
            confidence += 0.1
        if candidate.rsi_14 is not None:
            if direction == "long" and 40 < candidate.rsi_14 < 65:
                confidence += 0.1
            elif direction == "short" and 35 < candidate.rsi_14 < 60:
                confidence += 0.1
        if candidate.adx_14 is not None and candidate.adx_14 > 25:
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
            position_size_pct=pos_cfg.get("risk_per_trade", 1.0),
            reasoning=(
                f"Momentum {direction}: 24h change={candidate.change_24h:.1f}%, "
                f"volume_ratio={candidate.volume_ratio}, RSI={candidate.rsi_14}, "
                f"EMA trend={candidate.ema_trend}"
            ),
            tags=candidate.tags if candidate.tags else [],
        )
