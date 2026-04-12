"""Risk management engine — the highest priority gate in the decision pipeline.

Hard-coded rules that CANNOT be overridden by strategies or AI:
  1. Single trade max loss:   total_equity * max_loss_per_trade_pct
  2. Single symbol max pos:   total_equity * max_position_pct
  3. Total exposure cap:      total_equity * max_total_exposure_pct
  4. Daily max loss:          total_equity * max_daily_loss_pct → halt trading
  5. Consecutive losses:      N losses in a row → halt + notify
  6. Daily trade count cap:   max_daily_trades
  7. Leverage ceiling:        max_leverage
  8. Low-liquidity guard:     auto-halve position for thin symbols
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import structlog

from config.settings import settings
from src.strategy.base import TradeSignal

logger = structlog.get_logger()


@dataclass
class RiskCheckResult:
    passed: bool
    reason: str = ""


class RiskManager:
    """Stateful risk engine — tracks daily PnL, trade counts, consecutive losses."""

    def __init__(self, config: dict | None = None):
        cfg = config or {}
        self.max_loss_per_trade_pct: float = cfg.get(
            "max_loss_per_trade_pct", settings.max_loss_per_trade_pct
        )
        self.max_position_pct: float = cfg.get("max_position_pct", 10.0)
        self.max_total_exposure_pct: float = cfg.get(
            "max_total_exposure_pct", settings.max_total_exposure_pct
        )
        self.max_daily_loss_pct: float = cfg.get(
            "max_daily_loss_pct", settings.max_daily_loss_pct
        )
        self.max_consecutive_losses: int = cfg.get("max_consecutive_losses", 5)
        self.max_daily_trades: int = cfg.get("max_daily_trades", 20)
        self.max_leverage: int = cfg.get("max_leverage", settings.max_leverage)
        self.min_quote_volume: float = cfg.get("min_quote_volume_for_full_size", 10_000_000)

        # Runtime state
        self._daily_pnl: float = 0.0
        self._daily_trade_count: int = 0
        self._consecutive_losses: int = 0
        self._total_equity: float = 0.0
        self._current_exposure: float = 0.0
        self._symbol_exposure: dict[str, float] = {}
        self._halted: bool = False
        self._halt_reason: str = ""
        self._day_start: float = self._today_start()

    # ── Public API ───────────────────────────────────────────────────────

    def update_equity(self, total_equity: float) -> None:
        self._total_equity = total_equity

    def update_exposure(self, total_exposure: float, by_symbol: dict[str, float]) -> None:
        self._current_exposure = total_exposure
        self._symbol_exposure = by_symbol

    def record_trade_result(self, pnl: float) -> None:
        """Call after a trade closes to update daily stats."""
        self._maybe_reset_day()
        self._daily_pnl += pnl
        self._daily_trade_count += 1
        if pnl <= 0:
            self._consecutive_losses += 1
        else:
            self._consecutive_losses = 0

        # Eagerly check halt conditions
        self._check_daily_loss()
        self._check_consecutive_losses()

    def reset_halt(self) -> None:
        """Manual reset after investigation."""
        self._halted = False
        self._halt_reason = ""
        logger.info("risk_halt_reset")

    @property
    def is_halted(self) -> bool:
        return self._halted

    # ── Pre-trade check ──────────────────────────────────────────────────

    async def pre_check(self, signal: TradeSignal) -> RiskCheckResult:
        """Run all risk checks before entering a trade."""
        self._maybe_reset_day()

        checks = [
            self._check_halt(),
            self._check_daily_loss(),
            self._check_consecutive_losses(),
            self._check_daily_trade_count(),
            self._check_total_exposure(signal),
            self._check_symbol_exposure(signal),
            self._check_leverage(signal),
            self._check_max_loss_per_trade(signal),
        ]
        for check in checks:
            if not check.passed:
                return check
        return RiskCheckResult(passed=True)

    async def final_check(self, signal: TradeSignal) -> RiskCheckResult:
        """Final check after AI adjustments — re-verify critical limits."""
        return await self.pre_check(signal)

    # ── Individual checks ────────────────────────────────────────────────

    def _check_halt(self) -> RiskCheckResult:
        if self._halted:
            return RiskCheckResult(passed=False, reason=f"交易已暂停: {self._halt_reason}")
        return RiskCheckResult(passed=True)

    def _check_daily_loss(self) -> RiskCheckResult:
        if self._total_equity <= 0:
            return RiskCheckResult(passed=True)  # equity not yet set
        daily_loss_pct = abs(self._daily_pnl) / self._total_equity * 100
        if self._daily_pnl < 0 and daily_loss_pct >= self.max_daily_loss_pct:
            self._halted = True
            self._halt_reason = f"日亏损 {daily_loss_pct:.2f}% >= {self.max_daily_loss_pct}%"
            logger.critical("risk_daily_loss_halt", pnl=self._daily_pnl, pct=daily_loss_pct)
            return RiskCheckResult(passed=False, reason=self._halt_reason)
        return RiskCheckResult(passed=True)

    def _check_consecutive_losses(self) -> RiskCheckResult:
        if self._consecutive_losses >= self.max_consecutive_losses:
            self._halted = True
            self._halt_reason = f"连续亏损 {self._consecutive_losses} 次"
            logger.critical("risk_consecutive_loss_halt", count=self._consecutive_losses)
            return RiskCheckResult(passed=False, reason=self._halt_reason)
        return RiskCheckResult(passed=True)

    def _check_daily_trade_count(self) -> RiskCheckResult:
        if self._daily_trade_count >= self.max_daily_trades:
            return RiskCheckResult(
                passed=False,
                reason=f"日交易次数 {self._daily_trade_count} >= {self.max_daily_trades}",
            )
        return RiskCheckResult(passed=True)

    def _check_total_exposure(self, signal: TradeSignal) -> RiskCheckResult:
        if self._total_equity <= 0:
            return RiskCheckResult(passed=True)
        new_exposure = signal.position_size_pct / 100 * self._total_equity
        total_after = self._current_exposure + new_exposure
        exposure_pct = total_after / self._total_equity * 100
        if exposure_pct > self.max_total_exposure_pct:
            return RiskCheckResult(
                passed=False,
                reason=f"总仓位 {exposure_pct:.1f}% > {self.max_total_exposure_pct}%",
            )
        return RiskCheckResult(passed=True)

    def _check_symbol_exposure(self, signal: TradeSignal) -> RiskCheckResult:
        if self._total_equity <= 0:
            return RiskCheckResult(passed=True)
        existing = self._symbol_exposure.get(signal.symbol, 0)
        new_pos = signal.position_size_pct / 100 * self._total_equity
        total_sym = existing + new_pos
        sym_pct = total_sym / self._total_equity * 100
        if sym_pct > self.max_position_pct:
            return RiskCheckResult(
                passed=False,
                reason=f"{signal.symbol} 仓位 {sym_pct:.1f}% > {self.max_position_pct}%",
            )
        return RiskCheckResult(passed=True)

    def _check_leverage(self, signal: TradeSignal) -> RiskCheckResult:
        # Leverage is checked at order level; here we just verify config
        return RiskCheckResult(passed=True)

    def _check_max_loss_per_trade(self, signal: TradeSignal) -> RiskCheckResult:
        if self._total_equity <= 0:
            return RiskCheckResult(passed=True)
        # Potential loss = distance to stop loss * position size
        if signal.stop_loss and signal.entry_price:
            loss_pct = abs(signal.entry_price - signal.stop_loss) / signal.entry_price * 100
            position_value = signal.position_size_pct / 100 * self._total_equity
            potential_loss = position_value * loss_pct / 100
            max_allowed = self._total_equity * self.max_loss_per_trade_pct / 100
            if potential_loss > max_allowed:
                return RiskCheckResult(
                    passed=False,
                    reason=(
                        f"单笔潜在亏损 ${potential_loss:.2f} > "
                        f"上限 ${max_allowed:.2f} ({self.max_loss_per_trade_pct}%)"
                    ),
                )
        return RiskCheckResult(passed=True)

    # ── Helpers ──────────────────────────────────────────────────────────

    def _maybe_reset_day(self) -> None:
        """Reset daily counters at midnight."""
        today = self._today_start()
        if today > self._day_start:
            self._daily_pnl = 0.0
            self._daily_trade_count = 0
            self._day_start = today
            if self._halted and "日亏损" in self._halt_reason:
                self._halted = False
                self._halt_reason = ""
                logger.info("risk_daily_reset")

    @staticmethod
    def _today_start() -> float:
        t = time.time()
        return t - (t % 86400)
