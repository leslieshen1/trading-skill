"""Position sizing calculators.

Methods:
  - fixed_percent:  risk a fixed % of equity per trade
  - kelly:          Kelly criterion based on win rate and payoff ratio
  - atr_based:      size inversely proportional to ATR (volatility-adjusted)
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog

logger = structlog.get_logger()


@dataclass
class PositionSize:
    quantity: float
    notional_value: float      # in quote currency
    risk_amount: float         # max loss if stop hit
    position_pct: float        # % of total equity


class PositionSizer:
    def __init__(self, total_equity: float, max_position_pct: float = 10.0):
        self.total_equity = total_equity
        self.max_position_pct = max_position_pct

    def calculate(
        self,
        method: str,
        entry_price: float,
        stop_loss: float,
        risk_per_trade_pct: float = 1.0,
        win_rate: float | None = None,
        avg_win: float | None = None,
        avg_loss: float | None = None,
        atr: float | None = None,
    ) -> PositionSize:
        """Calculate position size using the specified method."""
        if method == "kelly":
            return self._kelly(entry_price, stop_loss, win_rate, avg_win, avg_loss)
        elif method == "atr_based":
            return self._atr_based(entry_price, stop_loss, risk_per_trade_pct, atr)
        else:
            return self._fixed_percent(entry_price, stop_loss, risk_per_trade_pct)

    def _fixed_percent(
        self, entry_price: float, stop_loss: float, risk_pct: float
    ) -> PositionSize:
        """Risk a fixed percentage of equity per trade."""
        risk_amount = self.total_equity * risk_pct / 100
        price_risk = abs(entry_price - stop_loss)
        if price_risk <= 0:
            price_risk = entry_price * 0.02  # fallback: 2% stop

        quantity = risk_amount / price_risk
        notional = quantity * entry_price
        position_pct = notional / self.total_equity * 100

        # Cap at max position
        if position_pct > self.max_position_pct:
            notional = self.total_equity * self.max_position_pct / 100
            quantity = notional / entry_price
            position_pct = self.max_position_pct
            risk_amount = quantity * price_risk

        return PositionSize(
            quantity=round(quantity, 8),
            notional_value=round(notional, 2),
            risk_amount=round(risk_amount, 2),
            position_pct=round(position_pct, 4),
        )

    def _kelly(
        self,
        entry_price: float,
        stop_loss: float,
        win_rate: float | None,
        avg_win: float | None,
        avg_loss: float | None,
    ) -> PositionSize:
        """Kelly criterion: f* = (p*b - q) / b where p=win_rate, b=payoff, q=1-p."""
        if not win_rate or not avg_win or not avg_loss or avg_loss == 0:
            # Not enough data — fall back to conservative fixed %
            return self._fixed_percent(entry_price, stop_loss, 0.5)

        p = win_rate
        q = 1 - p
        b = abs(avg_win / avg_loss)
        kelly_fraction = (p * b - q) / b

        # Half-Kelly for safety
        kelly_fraction = max(0, kelly_fraction) * 0.5
        # Cap
        kelly_fraction = min(kelly_fraction, self.max_position_pct / 100)

        risk_amount = self.total_equity * kelly_fraction
        price_risk = abs(entry_price - stop_loss)
        if price_risk <= 0:
            price_risk = entry_price * 0.02

        quantity = risk_amount / price_risk
        notional = quantity * entry_price
        position_pct = notional / self.total_equity * 100

        return PositionSize(
            quantity=round(quantity, 8),
            notional_value=round(notional, 2),
            risk_amount=round(risk_amount, 2),
            position_pct=round(position_pct, 4),
        )

    def _atr_based(
        self,
        entry_price: float,
        stop_loss: float,
        risk_pct: float,
        atr: float | None,
    ) -> PositionSize:
        """ATR-based: use ATR as the stop distance, inversely scale position."""
        if not atr or atr <= 0:
            return self._fixed_percent(entry_price, stop_loss, risk_pct)

        risk_amount = self.total_equity * risk_pct / 100
        # Use 2x ATR as stop distance
        stop_distance = atr * 2
        quantity = risk_amount / stop_distance
        notional = quantity * entry_price
        position_pct = notional / self.total_equity * 100

        if position_pct > self.max_position_pct:
            notional = self.total_equity * self.max_position_pct / 100
            quantity = notional / entry_price
            position_pct = self.max_position_pct
            risk_amount = quantity * stop_distance

        return PositionSize(
            quantity=round(quantity, 8),
            notional_value=round(notional, 2),
            risk_amount=round(risk_amount, 2),
            position_pct=round(position_pct, 4),
        )
