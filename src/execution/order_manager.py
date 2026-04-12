"""Order lifecycle management — tracks orders from creation to fill/cancel."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum

import structlog

from src.execution.binance_client import BinanceTradingClient

logger = structlog.get_logger()


class OrderStatus(str, Enum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    FAILED = "failed"


@dataclass
class ManagedOrder:
    """Internal order representation with lifecycle tracking."""

    symbol: str
    side: str
    order_type: str
    quantity: float
    price: float | None = None
    stop_price: float | None = None
    order_id: int | None = None
    status: OrderStatus = OrderStatus.PENDING
    filled_quantity: float = 0.0
    avg_fill_price: float = 0.0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    timeout_seconds: float = 60.0
    tag: str = ""  # "entry" / "stop_loss" / "take_profit"


class OrderManager:
    """Manages the lifecycle of orders with timeout and status tracking."""

    def __init__(self, client: BinanceTradingClient):
        self.client = client
        self._orders: dict[int, ManagedOrder] = {}

    async def submit_order(self, order: ManagedOrder) -> ManagedOrder:
        """Submit an order to the exchange."""
        try:
            result = await self.client.place_order(
                symbol=order.symbol,
                side=order.side,
                order_type=order.order_type,
                quantity=order.quantity,
                price=order.price,
                stop_price=order.stop_price,
                reduce_only=(order.tag in ("stop_loss", "take_profit")),
            )
            order.order_id = result.get("orderId")
            order.status = self._map_status(result.get("status", "NEW"))
            order.filled_quantity = float(result.get("executedQty", 0))
            order.avg_fill_price = float(result.get("avgPrice", 0))
            order.updated_at = time.time()

            if order.order_id:
                self._orders[order.order_id] = order

            logger.info(
                "order_submitted",
                order_id=order.order_id,
                symbol=order.symbol,
                side=order.side,
                tag=order.tag,
                status=order.status.value,
            )
        except Exception as e:
            order.status = OrderStatus.FAILED
            logger.error("order_submit_failed", symbol=order.symbol, error=str(e))

        return order

    async def cancel(self, order: ManagedOrder) -> ManagedOrder:
        """Cancel a pending/submitted order."""
        if order.order_id and order.status in (OrderStatus.SUBMITTED, OrderStatus.PENDING):
            try:
                await self.client.cancel_order(order.symbol, order.order_id)
                order.status = OrderStatus.CANCELLED
                order.updated_at = time.time()
                logger.info("order_cancelled", order_id=order.order_id, symbol=order.symbol)
            except Exception as e:
                logger.error("order_cancel_failed", order_id=order.order_id, error=str(e))
        return order

    async def check_timeouts(self) -> list[ManagedOrder]:
        """Cancel orders that have exceeded their timeout."""
        now = time.time()
        timed_out: list[ManagedOrder] = []
        for order in list(self._orders.values()):
            if order.status == OrderStatus.SUBMITTED:
                if now - order.created_at > order.timeout_seconds:
                    await self.cancel(order)
                    timed_out.append(order)
        return timed_out

    def get_order(self, order_id: int) -> ManagedOrder | None:
        return self._orders.get(order_id)

    @staticmethod
    def _map_status(exchange_status: str) -> OrderStatus:
        mapping = {
            "NEW": OrderStatus.SUBMITTED,
            "PARTIALLY_FILLED": OrderStatus.PARTIALLY_FILLED,
            "FILLED": OrderStatus.FILLED,
            "CANCELED": OrderStatus.CANCELLED,
            "REJECTED": OrderStatus.FAILED,
            "EXPIRED": OrderStatus.CANCELLED,
        }
        return mapping.get(exchange_status, OrderStatus.SUBMITTED)
