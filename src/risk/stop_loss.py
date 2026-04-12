"""Stop-loss strategy implementations.

Types:
  - fixed:     static stop at a fixed % from entry
  - trailing:  moves up with price, locks in profit
  - atr:       stop at N * ATR below entry (volatility-adaptive)
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog

logger = structlog.get_logger()


@dataclass
class StopLossState:
    """Tracks the current stop-loss level for a position."""

    symbol: str
    direction: str              # "long" or "short"
    entry_price: float
    current_stop: float
    initial_stop: float
    highest_price: float        # for trailing (long)
    lowest_price: float         # for trailing (short)
    stop_type: str              # "fixed" / "trailing" / "atr"


class StopLossManager:
    """Manages stop-loss logic for open positions."""

    def create_stop(
        self,
        symbol: str,
        direction: str,
        entry_price: float,
        stop_pct: float = 2.0,
        trailing_pct: float | None = None,
        atr: float | None = None,
        atr_multiplier: float = 2.0,
    ) -> StopLossState:
        """Create a new stop-loss state for a position."""
        if atr and atr > 0:
            stop_type = "atr"
            distance = atr * atr_multiplier
        else:
            distance = entry_price * stop_pct / 100
            stop_type = "trailing" if trailing_pct else "fixed"

        if direction == "long":
            current_stop = entry_price - distance
        else:
            current_stop = entry_price + distance

        return StopLossState(
            symbol=symbol,
            direction=direction,
            entry_price=entry_price,
            current_stop=round(current_stop, 8),
            initial_stop=round(current_stop, 8),
            highest_price=entry_price,
            lowest_price=entry_price,
            stop_type=stop_type,
        )

    def update(
        self,
        state: StopLossState,
        current_price: float,
        trailing_pct: float = 1.5,
    ) -> StopLossState:
        """Update stop-loss based on current price (for trailing stops)."""
        if state.stop_type != "trailing":
            return state

        if state.direction == "long":
            if current_price > state.highest_price:
                state.highest_price = current_price
                new_stop = current_price * (1 - trailing_pct / 100)
                if new_stop > state.current_stop:
                    state.current_stop = round(new_stop, 8)
                    logger.debug(
                        "trailing_stop_updated",
                        symbol=state.symbol,
                        new_stop=state.current_stop,
                    )
        else:  # short
            if current_price < state.lowest_price:
                state.lowest_price = current_price
                new_stop = current_price * (1 + trailing_pct / 100)
                if new_stop < state.current_stop:
                    state.current_stop = round(new_stop, 8)

        return state

    def check_triggered(self, state: StopLossState, current_price: float) -> bool:
        """Check if the stop-loss has been triggered."""
        if state.direction == "long":
            return current_price <= state.current_stop
        else:
            return current_price >= state.current_stop
