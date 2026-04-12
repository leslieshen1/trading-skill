"""Main entry point — starts all bot components.

Components:
  1. Data collector (ticker, kline, funding rate)
  2. Strategy engine (scan → evaluate → signal)
  3. Decision maker (signal → AI → risk → decision)
  4. Executor (decision → order → position)
  5. Monitor (alerts, position tracking)
  6. API server (dashboard)
"""

from __future__ import annotations

import asyncio
import signal as sys_signal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import structlog

from config.settings import settings
from src.ai.analyst import AIAnalyst
from src.ai.decision import DecisionMaker
from src.ai.memory import TradingMemory
from src.data.collector import DataCollector
from src.execution.binance_client import BinanceTradingClient
from src.execution.executor import OrderExecutor
from src.execution.order_manager import OrderManager
from src.execution.position_manager import PositionManager
from src.monitor.alerts import AlertLevel, AlertManager
from src.monitor.logger import setup_logging
from src.risk.circuit_breaker import CircuitBreaker
from src.risk.risk_manager import RiskManager
from src.risk.stop_loss import StopLossManager
from src.scanner.filters import ScreenerConfig
from src.scanner.screener import MarketScreener
from src.storage.database import async_session, init_db
from src.storage.repo_kline import KlineRepo
from src.storage.repo_ticker import TickerRepo
from src.storage.repo_trades import TradeRepo
from src.strategy.engine import StrategyEngine
from src.strategy.loader import load_strategies

logger = structlog.get_logger()


class TradingBot:
    """Main bot orchestrator."""

    def __init__(self):
        self._running = False
        self.alert_mgr = AlertManager()

    async def start(self) -> None:
        setup_logging()
        logger.info("bot_starting", testnet=settings.binance_testnet)
        await init_db()

        # ── Initialize components ────────────────────────────────────────
        # Data
        self.collector = DataCollector()

        # Storage (shared session factory via async_session)
        # Strategy
        strategies = load_strategies()
        logger.info("strategies_loaded", count=len(strategies))

        # Build strategy config map for AI
        strategy_configs = {s.name: s.config for s in strategies}

        # Risk
        risk_manager = RiskManager()
        circuit_breaker = CircuitBreaker()
        stop_loss_mgr = StopLossManager()

        # AI
        ai_analyst = AIAnalyst()

        # Execution
        trading_client = BinanceTradingClient(market="futures_um")
        order_mgr = OrderManager(trading_client)

        # ── Start data collection ────────────────────────────────────────
        await self.collector.start()

        # ── Main loop ────────────────────────────────────────────────────
        self._running = True
        logger.info("bot_started")
        await self.alert_mgr.send(AlertLevel.INFO, "Bot启动", "Trading bot is now running.")

        while self._running:
            try:
                await self._run_cycle(
                    strategies, strategy_configs, risk_manager,
                    circuit_breaker, stop_loss_mgr, ai_analyst,
                    trading_client, order_mgr,
                )
            except Exception as e:
                logger.error("main_loop_error", error=str(e))
                await self.alert_mgr.notify_error("main_loop", str(e))

            await asyncio.sleep(settings.strategy_interval)

    async def _run_cycle(
        self, strategies, strategy_configs, risk_manager,
        circuit_breaker, stop_loss_mgr, ai_analyst,
        trading_client, order_mgr,
    ) -> None:
        """One iteration of scan → evaluate → decide → execute."""

        async with async_session() as session:
            ticker_repo = TickerRepo(session)
            kline_repo = KlineRepo(session)
            trade_repo = TradeRepo(session)

            # 1. Update equity and risk state
            try:
                balance = await trading_client.get_balance()
                equity = balance.get("total", 0)
                risk_manager.update_equity(equity)
                circuit_breaker.set_initial_equity(equity)
            except Exception as e:
                logger.warning("balance_fetch_failed", error=str(e))
                return

            # 2. Check circuit breaker
            breaker_state = circuit_breaker.evaluate(
                daily_pnl=risk_manager._daily_pnl,
                total_equity=equity,
            )
            if not breaker_state.allow_new_entry:
                logger.warning("circuit_breaker_active", level=breaker_state.level.name)
                return

            # 3. Scan market
            screener_config = ScreenerConfig()
            screener = MarketScreener(ticker_repo, kline_repo, screener_config)
            strategy_engine = StrategyEngine(strategies, screener, kline_repo)

            # 4. Run strategy engine
            signals = await strategy_engine.run_cycle()
            if not signals:
                return

            # 5. Decision & execution
            trading_memory = TradingMemory(trade_repo)
            decision_maker = DecisionMaker(ai_analyst, trading_memory, strategy_configs)
            decision_maker.set_risk_manager(risk_manager)

            position_mgr = PositionManager(trading_client, trade_repo, stop_loss_mgr)
            executor = OrderExecutor(
                trading_client, order_mgr, position_mgr,
                trade_repo, stop_loss_mgr, total_equity=equity,
            )

            for signal in signals[:5]:  # limit to top 5 signals per cycle
                klines = await kline_repo.get_klines(
                    signal.symbol, "1h", market=signal.market, limit=100
                )
                # Build a minimal candidate for AI analysis
                from src.scanner.screener import CandidateToken
                candidate = CandidateToken(
                    symbol=signal.symbol,
                    market=signal.market,
                    price=signal.entry_price,
                    change_24h=0,
                    volume_24h=0,
                    quote_volume_24h=0,
                    tags=signal.tags,
                )

                decision = await decision_maker.make_decision(signal, candidate, klines)
                if decision.execute:
                    success = await executor.execute(decision)
                    if success:
                        await self.alert_mgr.notify_trade_opened(
                            signal.symbol, signal.signal.value,
                            signal.entry_price, signal.position_size_pct,
                            signal.strategy_name,
                        )

    async def stop(self) -> None:
        self._running = False
        await self.collector.stop()
        await self.alert_mgr.close()
        logger.info("bot_stopped")


async def main() -> None:
    bot = TradingBot()

    loop = asyncio.get_event_loop()
    for sig in (sys_signal.SIGINT, sys_signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(bot.stop()))

    await bot.start()


if __name__ == "__main__":
    asyncio.run(main())
