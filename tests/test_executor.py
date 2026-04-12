"""Tests for the execution layer — uses mocked Binance client."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.execution.order_manager import ManagedOrder, OrderManager, OrderStatus
from src.execution.position_manager import Position, PositionManager
from src.risk.stop_loss import StopLossManager


# ── Order Manager Tests ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_order_submit_success():
    mock_client = MagicMock()
    mock_client.place_order = AsyncMock(return_value={
        "orderId": 12345,
        "status": "FILLED",
        "executedQty": "1.0",
        "avgPrice": "50000.0",
    })
    mgr = OrderManager(mock_client)
    order = ManagedOrder(symbol="BTCUSDT", side="BUY", order_type="MARKET", quantity=1.0, tag="entry")
    result = await mgr.submit_order(order)
    assert result.order_id == 12345
    assert result.status == OrderStatus.FILLED
    assert result.filled_quantity == 1.0


@pytest.mark.asyncio
async def test_order_submit_failure():
    mock_client = MagicMock()
    mock_client.place_order = AsyncMock(side_effect=Exception("API error"))
    mgr = OrderManager(mock_client)
    order = ManagedOrder(symbol="BTCUSDT", side="BUY", order_type="MARKET", quantity=1.0)
    result = await mgr.submit_order(order)
    assert result.status == OrderStatus.FAILED


@pytest.mark.asyncio
async def test_order_cancel():
    mock_client = MagicMock()
    mock_client.place_order = AsyncMock(return_value={
        "orderId": 99, "status": "NEW", "executedQty": "0", "avgPrice": "0",
    })
    mock_client.cancel_order = AsyncMock(return_value={"status": "CANCELED"})
    mgr = OrderManager(mock_client)

    order = ManagedOrder(symbol="BTCUSDT", side="BUY", order_type="LIMIT", quantity=1.0, price=49000)
    await mgr.submit_order(order)
    result = await mgr.cancel(order)
    assert result.status == OrderStatus.CANCELLED


@pytest.mark.asyncio
async def test_order_timeout():
    mock_client = MagicMock()
    mock_client.place_order = AsyncMock(return_value={
        "orderId": 55, "status": "NEW", "executedQty": "0", "avgPrice": "0",
    })
    mock_client.cancel_order = AsyncMock(return_value={})
    mgr = OrderManager(mock_client)

    order = ManagedOrder(
        symbol="BTCUSDT", side="BUY", order_type="LIMIT",
        quantity=1.0, price=49000, timeout_seconds=0,
    )
    order.created_at = time.time() - 100  # Already expired
    await mgr.submit_order(order)
    timed_out = await mgr.check_timeouts()
    assert len(timed_out) == 1


# ── Position Manager Tests ──────────────────────────────────────────────────

def test_position_unrealized_pnl():
    pos = Position(
        symbol="BTCUSDT", market="futures_um", direction="long",
        entry_price=50000, quantity=1.0, strategy_name="test",
    )
    assert pos.unrealized_pnl(51000) == 1000.0
    assert pos.unrealized_pnl(49000) == -1000.0

    pos_short = Position(
        symbol="ETHUSDT", market="futures_um", direction="short",
        entry_price=3000, quantity=10.0, strategy_name="test",
    )
    assert pos_short.unrealized_pnl(2900) == 1000.0
    assert pos_short.unrealized_pnl(3100) == -1000.0


def test_position_expired():
    pos = Position(
        symbol="BTCUSDT", market="futures_um", direction="long",
        entry_price=50000, quantity=1.0, strategy_name="test",
        max_hold_hours=1.0,
    )
    pos.opened_at = time.time() - 7200  # 2 hours ago
    assert pos.is_expired()

    pos2 = Position(
        symbol="BTCUSDT", market="futures_um", direction="long",
        entry_price=50000, quantity=1.0, strategy_name="test",
        max_hold_hours=48.0,
    )
    assert not pos2.is_expired()


def test_position_manager_exposure():
    mock_client = MagicMock()
    mock_trade_repo = MagicMock()
    sl_mgr = StopLossManager()
    pm = PositionManager(mock_client, mock_trade_repo, sl_mgr)

    pos1 = Position(
        symbol="BTCUSDT", market="futures_um", direction="long",
        entry_price=50000, quantity=1.0, strategy_name="test",
    )
    pos2 = Position(
        symbol="ETHUSDT", market="futures_um", direction="short",
        entry_price=3000, quantity=10.0, strategy_name="test",
    )
    pm.add_position(pos1)
    pm.add_position(pos2)

    assert pm.total_exposure == 80000.0  # 50000 + 30000
    assert pm.exposure_by_symbol["BTCUSDT"] == 50000.0
    assert pm.has_position("BTCUSDT")
    assert not pm.has_position("SOLUSDT")


@pytest.mark.asyncio
async def test_position_manager_check_stop_loss():
    mock_client = MagicMock()
    mock_trade_repo = MagicMock()
    sl_mgr = StopLossManager()
    pm = PositionManager(mock_client, mock_trade_repo, sl_mgr)

    sl_state = sl_mgr.create_stop("BTCUSDT", "long", 50000, stop_pct=2.0)
    pos = Position(
        symbol="BTCUSDT", market="futures_um", direction="long",
        entry_price=50000, quantity=1.0, strategy_name="test",
        stop_loss_state=sl_state,
    )
    pm.add_position(pos)

    # Price above stop — no trigger
    to_close = await pm.check_exits({"BTCUSDT": 50500})
    assert len(to_close) == 0

    # Price below stop — trigger
    to_close = await pm.check_exits({"BTCUSDT": 48000})
    assert len(to_close) == 1
    assert to_close[0].symbol == "BTCUSDT"


@pytest.mark.asyncio
async def test_position_manager_check_take_profit():
    mock_client = MagicMock()
    mock_trade_repo = MagicMock()
    sl_mgr = StopLossManager()
    pm = PositionManager(mock_client, mock_trade_repo, sl_mgr)

    pos = Position(
        symbol="ETHUSDT", market="futures_um", direction="long",
        entry_price=3000, quantity=10.0, strategy_name="test",
        take_profit_price=3300,
    )
    pm.add_position(pos)

    to_close = await pm.check_exits({"ETHUSDT": 3100})
    assert len(to_close) == 0

    to_close = await pm.check_exits({"ETHUSDT": 3400})
    assert len(to_close) == 1
