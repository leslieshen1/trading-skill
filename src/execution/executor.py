"""Order executor — the final step that places orders on Binance.

Flow:
  FinalDecision → price slippage check → compute quantity → place order
  → confirm fill → set stop-loss/take-profit → record trade
"""

from __future__ import annotations

import time

import structlog

from src.ai.decision import FinalDecision
from src.execution.binance_client import BinanceTradingClient
from src.execution.order_manager import ManagedOrder, OrderManager, OrderStatus
from src.execution.position_manager import Position, PositionManager
from src.risk.position_sizer import PositionSizer
from src.risk.stop_loss import StopLossManager
from src.storage.repo_trades import TradeRepo
from src.strategy.base import Signal

logger = structlog.get_logger()


class OrderExecutor:
    """Executes finalized trade decisions."""

    def __init__(
        self,
        client: BinanceTradingClient,
        order_mgr: OrderManager,
        position_mgr: PositionManager,
        trade_repo: TradeRepo,
        stop_loss_mgr: StopLossManager,
        total_equity: float = 0.0,
        max_slippage: float = 0.005,
    ):
        self.client = client
        self.order_mgr = order_mgr
        self.position_mgr = position_mgr
        self.trade_repo = trade_repo
        self.stop_loss_mgr = stop_loss_mgr
        self.total_equity = total_equity
        self.max_slippage = max_slippage

    def update_equity(self, equity: float) -> None:
        self.total_equity = equity

    async def execute(self, decision: FinalDecision) -> bool:
        """Execute a finalized trade decision. Returns True if order placed."""
        signal = decision.signal
        if not signal:
            return False

        # 1. Check if we already have a position in this symbol
        if self.position_mgr.has_position(signal.symbol):
            logger.warning("executor_position_exists", symbol=signal.symbol)
            return False

        # 2. Price slippage check
        try:
            current_price = await self.client.get_price(signal.symbol)
        except Exception as e:
            logger.error("executor_price_check_failed", symbol=signal.symbol, error=str(e))
            return False

        slippage = abs(current_price - signal.entry_price) / signal.entry_price
        if slippage > self.max_slippage:
            logger.warning(
                "executor_slippage_exceeded",
                symbol=signal.symbol,
                expected=signal.entry_price,
                current=current_price,
                slippage=f"{slippage:.4%}",
            )
            return False

        # 3. Get symbol precision
        try:
            qty_precision, price_precision = await self.client.get_symbol_precision(signal.symbol)
        except Exception:
            qty_precision, price_precision = 3, 2

        # 4. Calculate position size
        sizer = PositionSizer(self.total_equity, max_position_pct=10.0)
        pos_size = sizer.calculate(
            method="fixed_percent",
            entry_price=current_price,
            stop_loss=signal.stop_loss,
            risk_per_trade_pct=signal.position_size_pct,
        )

        quantity = self.client.round_quantity(pos_size.quantity, qty_precision)
        if quantity <= 0:
            logger.warning("executor_zero_quantity", symbol=signal.symbol)
            return False

        # 5. Place entry order
        side = "BUY" if signal.signal in (Signal.LONG, Signal.CLOSE_SHORT) else "SELL"
        entry_order = ManagedOrder(
            symbol=signal.symbol,
            side=side,
            order_type="MARKET",
            quantity=quantity,
            tag="entry",
        )
        entry_order = await self.order_mgr.submit_order(entry_order)

        if entry_order.status == OrderStatus.FAILED:
            return False

        fill_price = entry_order.avg_fill_price or current_price

        # 6. Set stop-loss
        sl_order = None
        if signal.stop_loss:
            sl_side = "SELL" if signal.signal == Signal.LONG else "BUY"
            sl_price = self.client.round_price(signal.stop_loss, price_precision)
            sl_order = ManagedOrder(
                symbol=signal.symbol,
                side=sl_side,
                order_type="STOP_MARKET",
                quantity=quantity,
                stop_price=sl_price,
                tag="stop_loss",
            )
            await self.order_mgr.submit_order(sl_order)

        # 7. Set take-profit
        tp_order = None
        if signal.take_profit:
            tp_side = "SELL" if signal.signal == Signal.LONG else "BUY"
            tp_price = self.client.round_price(signal.take_profit, price_precision)
            tp_order = ManagedOrder(
                symbol=signal.symbol,
                side=tp_side,
                order_type="TAKE_PROFIT_MARKET",
                quantity=quantity,
                stop_price=tp_price,
                tag="take_profit",
            )
            await self.order_mgr.submit_order(tp_order)

        # 8. Create stop-loss tracking state
        direction = "long" if signal.signal == Signal.LONG else "short"
        sl_state = self.stop_loss_mgr.create_stop(
            symbol=signal.symbol,
            direction=direction,
            entry_price=fill_price,
            stop_pct=abs(fill_price - signal.stop_loss) / fill_price * 100 if signal.stop_loss else 2.0,
        )

        # 9. Record trade
        ai_reasoning = ""
        if decision.ai_analysis:
            ai_reasoning = decision.ai_analysis.get("reasoning", "")

        trade_record = await self.trade_repo.create(
            symbol=signal.symbol,
            market=signal.market,
            side=side,
            signal=signal.signal.value,
            strategy_name=signal.strategy_name,
            entry_price=fill_price,
            quantity=quantity,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            status="open",
            opened_at=int(time.time() * 1000),
            ai_reasoning=ai_reasoning[:2000] if ai_reasoning else None,
        )

        # 10. Register position
        position = Position(
            symbol=signal.symbol,
            market=signal.market,
            direction=direction,
            entry_price=fill_price,
            quantity=quantity,
            strategy_name=signal.strategy_name,
            stop_loss_state=sl_state,
            take_profit_price=signal.take_profit,
            trade_record_id=trade_record.id,
        )
        self.position_mgr.add_position(position)

        logger.info(
            "trade_executed",
            symbol=signal.symbol,
            direction=direction,
            entry=fill_price,
            quantity=quantity,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            risk_amount=pos_size.risk_amount,
        )
        return True

    async def close_position_market(self, symbol: str, reason: str = "") -> bool:
        """Close an existing position with a market order."""
        position = self.position_mgr.get_position(symbol)
        if not position:
            return False

        side = "SELL" if position.direction == "long" else "BUY"
        close_order = ManagedOrder(
            symbol=symbol,
            side=side,
            order_type="MARKET",
            quantity=position.quantity,
            tag="close",
        )
        close_order = await self.order_mgr.submit_order(close_order)

        if close_order.status == OrderStatus.FAILED:
            return False

        exit_price = close_order.avg_fill_price
        if not exit_price:
            try:
                exit_price = await self.client.get_price(symbol)
            except Exception:
                exit_price = position.entry_price

        await self.position_mgr.close_position(position, exit_price, reason)
        return True
