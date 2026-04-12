"""Breakout strategy.

Detects price breaking out of consolidation ranges, confirmed by
volume spikes and volatility expansion.
"""

from __future__ import annotations

from src.strategy.base import BaseStrategy, Signal, TradeSignal


class BreakoutStrategy(BaseStrategy):

    async def evaluate(self, candidate, klines: list) -> TradeSignal | None:
        entry_cfg = self.config.get("entry", {})
        conditions = entry_cfg.get("conditions", [])

        if conditions and self.check_conditions(candidate, conditions):
            direction = entry_cfg.get("direction", "long")
        else:
            direction = self._detect_breakout(candidate)
            if direction is None:
                return None

        exit_cfg = self.config.get("exit", {})
        stop_pct = exit_cfg.get("stop_loss", 2.5)
        tp_pct = exit_cfg.get("take_profit", 5.0)
        stop_loss, take_profit = self.compute_stop_take(
            candidate.price, direction, stop_pct, tp_pct
        )

        confidence = 0.5
        # Volume confirmation is critical for breakouts
        if candidate.volume_ratio and candidate.volume_ratio > 3:
            confidence += 0.2
        elif candidate.volume_ratio and candidate.volume_ratio > 2:
            confidence += 0.1
        # ADX confirms trend strength
        if candidate.adx_14 is not None and candidate.adx_14 > 25:
            confidence += 0.1
        # Volatility expansion
        if candidate.atr_percent is not None and candidate.atr_percent > 3:
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
                f"Breakout {direction}: BB%B={candidate.bollinger_pct}, "
                f"volume_ratio={candidate.volume_ratio}, ADX={candidate.adx_14}"
            ),
            tags=candidate.tags if candidate.tags else [],
        )

    def _detect_breakout(self, candidate) -> str | None:
        bb = candidate.bollinger_pct
        vol = candidate.volume_ratio

        # Need volume confirmation
        if not vol or vol < 2.0:
            return None

        # Upper Bollinger breakout → long
        if bb is not None and bb > 1.0:
            return "long"

        # Lower Bollinger breakout → short
        if bb is not None and bb < 0.0:
            return "short"

        # Strong directional move without BB data
        if candidate.change_24h and abs(candidate.change_24h) > 5 and vol > 2.5:
            return "long" if candidate.change_24h > 0 else "short"

        return None
