"""Position manager — tracks open positions and their associated orders."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import structlog

from src.execution.binance_client import BinanceTradingClient
from src.risk.stop_loss import StopLossManager, StopLossState
from src.storage.repo_trades import TradeRepo

logger = structlog.get_logger()


@dataclass
class Position:
    """Internal position representation."""

    symbol: str
    market: str
    direction: str            # "long" / "short"
    entry_price: float
    quantity: float
    strategy_name: str
    stop_loss_state: StopLossState | None = None
    take_profit_price: float | None = None
    trade_record_id: int | None = None
    opened_at: float = field(default_factory=time.time)
    max_hold_hours: float | None = None

    @property
    def notional_value(self) -> float:
        return self.quantity * self.entry_price

    def unrealized_pnl(self, current_price: float) -> float:
        if self.direction == "long":
            return (current_price - self.entry_price) * self.quantity
        else:
            return (self.entry_price - current_price) * self.quantity

    def is_expired(self) -> bool:
        if self.max_hold_hours is None:
            return False
        elapsed_hours = (time.time() - self.opened_at) / 3600
        return elapsed_hours >= self.max_hold_hours


class PositionManager:
    """Manages all open positions, including stop/TP monitoring."""

    def __init__(
        self,
        client: BinanceTradingClient,
        trade_repo: TradeRepo,
        stop_loss_mgr: StopLossManager,
    ):
        self.client = client
        self.trade_repo = trade_repo
        self.stop_loss_mgr = stop_loss_mgr
        self._positions: dict[str, Position] = {}  # keyed by symbol

    def add_position(self, position: Position) -> None:
        self._positions[position.symbol] = position
        logger.info(
            "position_opened",
            symbol=position.symbol,
            direction=position.direction,
            entry=position.entry_price,
            quantity=position.quantity,
        )

    def get_position(self, symbol: str) -> Position | None:
        return self._positions.get(symbol)

    def get_all_positions(self) -> list[Position]:
        return list(self._positions.values())

    def has_position(self, symbol: str) -> bool:
        return symbol in self._positions

    @property
    def total_exposure(self) -> float:
        return sum(p.notional_value for p in self._positions.values())

    @property
    def exposure_by_symbol(self) -> dict[str, float]:
        return {p.symbol: p.notional_value for p in self._positions.values()}

    async def check_exits(self, price_feed: dict[str, float]) -> list[Position]:
        """Check all positions for stop-loss, take-profit, or expiry triggers.

        Args:
            price_feed: {symbol: current_price} dict

        Returns:
            List of positions that need to be closed.
        """
        to_close: list[Position] = []

        for symbol, position in list(self._positions.items()):
            current_price = price_feed.get(symbol)
            if current_price is None:
                continue

            # 1. Stop-loss check
            if position.stop_loss_state:
                # Update trailing stop
                position.stop_loss_state = self.stop_loss_mgr.update(
                    position.stop_loss_state, current_price
                )
                if self.stop_loss_mgr.check_triggered(position.stop_loss_state, current_price):
                    logger.warning(
                        "stop_loss_triggered",
                        symbol=symbol,
                        price=current_price,
                        stop=position.stop_loss_state.current_stop,
                    )
                    to_close.append(position)
                    continue

            # 2. Take-profit check
            if position.take_profit_price:
                if position.direction == "long" and current_price >= position.take_profit_price:
                    logger.info("take_profit_triggered", symbol=symbol, price=current_price)
                    to_close.append(position)
                    continue
                if position.direction == "short" and current_price <= position.take_profit_price:
                    logger.info("take_profit_triggered", symbol=symbol, price=current_price)
                    to_close.append(position)
                    continue

            # 3. Max hold time
            if position.is_expired():
                logger.info("position_expired", symbol=symbol)
                to_close.append(position)
                continue

        return to_close

    async def close_position(
        self,
        position: Position,
        exit_price: float,
        reason: str = "",
    ) -> None:
        """Record a position close."""
        pnl = position.unrealized_pnl(exit_price)

        # Update trade record
        if position.trade_record_id:
            await self.trade_repo.close_trade(position.trade_record_id, exit_price, pnl)

        logger.info(
            "position_closed",
            symbol=position.symbol,
            direction=position.direction,
            entry=position.entry_price,
            exit=exit_price,
            pnl=round(pnl, 2),
            reason=reason,
        )

        del self._positions[position.symbol]
