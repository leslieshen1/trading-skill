"""Mean reversion strategy.

Looks for oversold/overbought conditions (RSI, Bollinger %B) and trades
the snap-back to the mean.
"""

from __future__ import annotations

from src.strategy.base import BaseStrategy, Signal, TradeSignal


class MeanReversionStrategy(BaseStrategy):

    async def evaluate(self, candidate, klines: list) -> TradeSignal | None:
        entry_cfg = self.config.get("entry", {})
        conditions = entry_cfg.get("conditions", [])

        # If explicit conditions exist, use them
        if conditions and self.check_conditions(candidate, conditions):
            direction = entry_cfg.get("direction", "long")
        else:
            # Default: RSI + Bollinger band based detection
            direction = self._detect_reversion(candidate)
            if direction is None:
                return None

        exit_cfg = self.config.get("exit", {})
        stop_pct = exit_cfg.get("stop_loss", 2.0)
        tp_pct = exit_cfg.get("take_profit", 3.0)
        stop_loss, take_profit = self.compute_stop_take(
            candidate.price, direction, stop_pct, tp_pct
        )

        confidence = 0.5
        if candidate.rsi_14 is not None:
            if candidate.rsi_14 < 20 and direction == "long":
                confidence += 0.2
            elif candidate.rsi_14 > 80 and direction == "short":
                confidence += 0.2
            elif candidate.rsi_14 < 30 and direction == "long":
                confidence += 0.1
            elif candidate.rsi_14 > 70 and direction == "short":
                confidence += 0.1
        if candidate.bollinger_pct is not None:
            if candidate.bollinger_pct < 0 and direction == "long":
                confidence += 0.15
            elif candidate.bollinger_pct > 1.0 and direction == "short":
                confidence += 0.15

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
                f"Mean reversion {direction}: RSI={candidate.rsi_14}, "
                f"BB%B={candidate.bollinger_pct}"
            ),
            tags=candidate.tags if candidate.tags else [],
        )

    def _detect_reversion(self, candidate) -> str | None:
        rsi = candidate.rsi_14
        bb = candidate.bollinger_pct

        # Oversold → long
        if rsi is not None and rsi < 30:
            return "long"
        if bb is not None and bb < 0:
            return "long"

        # Overbought → short
        if rsi is not None and rsi > 70:
            return "short"
        if bb is not None and bb > 1.0:
            return "short"

        return None
