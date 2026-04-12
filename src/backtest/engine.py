"""Backtest engine — simulates strategy execution on historical data.

Walks through klines bar-by-bar, evaluating strategies and simulating
order fills, stop-losses, and take-profits.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import structlog

from src.monitor.metrics import PerformanceMetrics, calculate_metrics
from src.risk.stop_loss import StopLossManager
from src.scanner.screener import CandidateToken
from src.strategy.base import BaseStrategy, Signal, TradeSignal
from src.strategy.indicators import calculate_indicators

logger = structlog.get_logger()


@dataclass
class BacktestConfig:
    initial_equity: float = 10_000.0
    commission_pct: float = 0.04       # 0.04% per trade (Binance futures taker)
    slippage_pct: float = 0.01         # 0.01% simulated slippage
    max_open_positions: int = 5


@dataclass
class SimulatedTrade:
    symbol: str
    direction: str
    entry_price: float
    exit_price: float
    quantity: float
    pnl: float
    pnl_pct: float
    commission: float
    entry_bar: int
    exit_bar: int
    strategy: str
    exit_reason: str


@dataclass
class SimulatedPosition:
    symbol: str
    direction: str
    entry_price: float
    quantity: float
    stop_loss: float
    take_profit: float
    strategy: str
    entry_bar: int


@dataclass
class BacktestResult:
    config: BacktestConfig
    symbol: str
    interval: str
    total_bars: int
    start_time: int
    end_time: int
    initial_equity: float
    final_equity: float
    trades: list[SimulatedTrade] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)
    metrics: PerformanceMetrics | None = None

    @property
    def return_pct(self) -> float:
        if self.initial_equity == 0:
            return 0
        return (self.final_equity - self.initial_equity) / self.initial_equity * 100


class BacktestEngine:
    """Event-driven backtest engine."""

    def __init__(self, strategies: list[BaseStrategy], config: BacktestConfig | None = None):
        self.strategies = strategies
        self.config = config or BacktestConfig()
        self.stop_loss_mgr = StopLossManager()

    async def run(
        self,
        klines: list,
        symbol: str = "BTCUSDT",
        market: str = "futures_um",
        interval: str = "1h",
        lookback: int = 50,
    ) -> BacktestResult:
        """Run backtest on historical kline data.

        Args:
            klines: list of KlineBar objects, ordered ascending by time.
            symbol: trading pair symbol.
            market: market type.
            interval: kline interval.
            lookback: number of bars needed before first signal evaluation.
        """
        if len(klines) < lookback + 1:
            logger.warning("backtest_insufficient_data", bars=len(klines), need=lookback + 1)
            return BacktestResult(
                config=self.config,
                symbol=symbol,
                interval=interval,
                total_bars=len(klines),
                start_time=0,
                end_time=0,
                initial_equity=self.config.initial_equity,
                final_equity=self.config.initial_equity,
            )

        equity = self.config.initial_equity
        equity_curve: list[float] = [equity]
        trades: list[SimulatedTrade] = []
        open_positions: list[SimulatedPosition] = []

        start_time = getattr(klines[0], "open_time", 0)
        end_time = getattr(klines[-1], "open_time", 0)

        for i in range(lookback, len(klines)):
            bar = klines[i]
            current_price = float(getattr(bar, "close", 0))
            high = float(getattr(bar, "high", 0))
            low = float(getattr(bar, "low", 0))

            # 1. Check exits for open positions
            closed_indices = []
            for j, pos in enumerate(open_positions):
                exit_price = None
                exit_reason = ""

                if pos.direction == "long":
                    if low <= pos.stop_loss:
                        exit_price = pos.stop_loss
                        exit_reason = "stop_loss"
                    elif high >= pos.take_profit:
                        exit_price = pos.take_profit
                        exit_reason = "take_profit"
                else:
                    if high >= pos.stop_loss:
                        exit_price = pos.stop_loss
                        exit_reason = "stop_loss"
                    elif low <= pos.take_profit:
                        exit_price = pos.take_profit
                        exit_reason = "take_profit"

                if exit_price:
                    pnl_raw = self._calc_pnl(pos, exit_price)
                    commission = pos.quantity * pos.entry_price * self.config.commission_pct / 100 * 2
                    pnl = pnl_raw - commission
                    pnl_pct = pnl / (pos.quantity * pos.entry_price) * 100

                    trades.append(SimulatedTrade(
                        symbol=symbol,
                        direction=pos.direction,
                        entry_price=pos.entry_price,
                        exit_price=exit_price,
                        quantity=pos.quantity,
                        pnl=round(pnl, 2),
                        pnl_pct=round(pnl_pct, 4),
                        commission=round(commission, 4),
                        entry_bar=pos.entry_bar,
                        exit_bar=i,
                        strategy=pos.strategy,
                        exit_reason=exit_reason,
                    ))
                    equity += pnl
                    closed_indices.append(j)

            for j in sorted(closed_indices, reverse=True):
                open_positions.pop(j)

            # 2. Evaluate strategies for new entries
            if len(open_positions) < self.config.max_open_positions:
                history = klines[max(0, i - lookback):i + 1]
                indicators = calculate_indicators(history)

                candidate = CandidateToken(
                    symbol=symbol,
                    market=market,
                    price=current_price,
                    change_24h=0,
                    volume_24h=float(getattr(bar, "volume", 0)),
                    quote_volume_24h=0,
                    rsi_14=indicators.rsi_14,
                    macd_signal=indicators.macd_signal,
                    ema_trend=indicators.ema_trend,
                    volume_ratio=indicators.volume_ratio,
                    atr_percent=indicators.atr_percent,
                    adx_14=indicators.adx_14,
                    bollinger_pct=indicators.bollinger_pct,
                )

                for strategy in self.strategies:
                    signal = await strategy.evaluate(candidate, history)
                    if signal and not self._has_position(open_positions, symbol):
                        # Apply slippage
                        if signal.signal == Signal.LONG:
                            entry = current_price * (1 + self.config.slippage_pct / 100)
                        else:
                            entry = current_price * (1 - self.config.slippage_pct / 100)

                        risk_pct = signal.position_size_pct / 100
                        position_value = equity * risk_pct
                        qty = position_value / entry

                        open_positions.append(SimulatedPosition(
                            symbol=symbol,
                            direction="long" if signal.signal == Signal.LONG else "short",
                            entry_price=round(entry, 8),
                            quantity=round(qty, 8),
                            stop_loss=signal.stop_loss,
                            take_profit=signal.take_profit,
                            strategy=signal.strategy_name,
                            entry_bar=i,
                        ))
                        break  # one entry per bar

            equity_curve.append(round(equity, 2))

        # Close remaining positions at last price
        last_price = float(getattr(klines[-1], "close", 0))
        for pos in open_positions:
            pnl_raw = self._calc_pnl(pos, last_price)
            commission = pos.quantity * pos.entry_price * self.config.commission_pct / 100 * 2
            pnl = pnl_raw - commission
            pnl_pct = pnl / (pos.quantity * pos.entry_price) * 100

            trades.append(SimulatedTrade(
                symbol=symbol,
                direction=pos.direction,
                entry_price=pos.entry_price,
                exit_price=last_price,
                quantity=pos.quantity,
                pnl=round(pnl, 2),
                pnl_pct=round(pnl_pct, 4),
                commission=round(commission, 4),
                entry_bar=pos.entry_bar,
                exit_bar=len(klines) - 1,
                strategy=pos.strategy,
                exit_reason="backtest_end",
            ))
            equity += pnl

        # Calculate metrics
        pnl_list = [t.pnl for t in trades]
        hold_times = [
            (t.exit_bar - t.entry_bar) * self._interval_to_ms(interval)
            for t in trades
        ]
        metrics = calculate_metrics(pnl_list, hold_times)

        result = BacktestResult(
            config=self.config,
            symbol=symbol,
            interval=interval,
            total_bars=len(klines),
            start_time=start_time,
            end_time=end_time,
            initial_equity=self.config.initial_equity,
            final_equity=round(equity, 2),
            trades=trades,
            equity_curve=equity_curve,
            metrics=metrics,
        )

        logger.info(
            "backtest_complete",
            symbol=symbol,
            bars=len(klines),
            trades=len(trades),
            pnl=round(result.final_equity - result.initial_equity, 2),
            return_pct=f"{result.return_pct:.2f}%",
        )
        return result

    @staticmethod
    def _calc_pnl(pos: SimulatedPosition, exit_price: float) -> float:
        if pos.direction == "long":
            return (exit_price - pos.entry_price) * pos.quantity
        else:
            return (pos.entry_price - exit_price) * pos.quantity

    @staticmethod
    def _has_position(positions: list[SimulatedPosition], symbol: str) -> bool:
        return any(p.symbol == symbol for p in positions)

    @staticmethod
    def _interval_to_ms(interval: str) -> int:
        mapping = {
            "1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000,
            "30m": 1_800_000, "1h": 3_600_000, "2h": 7_200_000,
            "4h": 14_400_000, "6h": 21_600_000, "12h": 43_200_000,
            "1d": 86_400_000, "1w": 604_800_000,
        }
        return mapping.get(interval, 3_600_000)
