"""Circuit breaker — escalating protection levels.

Levels:
  L1:  daily loss > 3%   → reduce new position sizes by 50%, send WARNING
  L2:  daily loss > 5%   → stop opening new positions, only allow closes
  L3:  daily loss > 8%   → close ALL positions, halt trading 24h, CRITICAL alert
  L4:  total loss > 15%  → full shutdown, requires manual restart
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

import structlog

logger = structlog.get_logger()


class BreakerLevel(IntEnum):
    NORMAL = 0
    L1_REDUCE = 1
    L2_STOP_ENTRY = 2
    L3_CLOSE_ALL = 3
    L4_SHUTDOWN = 4


@dataclass
class BreakerState:
    level: BreakerLevel
    position_size_multiplier: float   # 1.0 = normal, 0.5 = half, 0 = no new
    allow_new_entry: bool
    close_all: bool
    shutdown: bool
    message: str


class CircuitBreaker:
    """Evaluates current state and returns the appropriate breaker level."""

    THRESHOLDS = {
        BreakerLevel.L1_REDUCE: 3.0,
        BreakerLevel.L2_STOP_ENTRY: 5.0,
        BreakerLevel.L3_CLOSE_ALL: 8.0,
        BreakerLevel.L4_SHUTDOWN: 15.0,
    }

    def __init__(self, initial_equity: float = 0.0):
        self.initial_equity = initial_equity
        self._current_level = BreakerLevel.NORMAL
        self._manually_reset = False

    def set_initial_equity(self, equity: float) -> None:
        self.initial_equity = equity

    def evaluate(
        self,
        daily_pnl: float,
        total_equity: float,
    ) -> BreakerState:
        """Determine the current circuit breaker level."""
        if total_equity <= 0:
            return self._state(BreakerLevel.NORMAL)

        daily_loss_pct = 0.0
        if daily_pnl < 0:
            daily_loss_pct = abs(daily_pnl) / total_equity * 100

        total_loss_pct = 0.0
        if self.initial_equity > 0 and total_equity < self.initial_equity:
            total_loss_pct = (self.initial_equity - total_equity) / self.initial_equity * 100

        # Check from highest to lowest
        if total_loss_pct >= self.THRESHOLDS[BreakerLevel.L4_SHUTDOWN]:
            new_level = BreakerLevel.L4_SHUTDOWN
        elif daily_loss_pct >= self.THRESHOLDS[BreakerLevel.L3_CLOSE_ALL]:
            new_level = BreakerLevel.L3_CLOSE_ALL
        elif daily_loss_pct >= self.THRESHOLDS[BreakerLevel.L2_STOP_ENTRY]:
            new_level = BreakerLevel.L2_STOP_ENTRY
        elif daily_loss_pct >= self.THRESHOLDS[BreakerLevel.L1_REDUCE]:
            new_level = BreakerLevel.L1_REDUCE
        else:
            new_level = BreakerLevel.NORMAL

        # Log level changes
        if new_level != self._current_level:
            if new_level > self._current_level:
                logger.critical(
                    "circuit_breaker_escalated",
                    from_level=self._current_level.name,
                    to_level=new_level.name,
                    daily_loss_pct=round(daily_loss_pct, 2),
                    total_loss_pct=round(total_loss_pct, 2),
                )
            else:
                logger.info(
                    "circuit_breaker_deescalated",
                    from_level=self._current_level.name,
                    to_level=new_level.name,
                )
            self._current_level = new_level

        return self._state(new_level)

    def _state(self, level: BreakerLevel) -> BreakerState:
        if level == BreakerLevel.NORMAL:
            return BreakerState(
                level=level,
                position_size_multiplier=1.0,
                allow_new_entry=True,
                close_all=False,
                shutdown=False,
                message="正常运行",
            )
        elif level == BreakerLevel.L1_REDUCE:
            return BreakerState(
                level=level,
                position_size_multiplier=0.5,
                allow_new_entry=True,
                close_all=False,
                shutdown=False,
                message="L1: 日亏损超3%，仓位减半",
            )
        elif level == BreakerLevel.L2_STOP_ENTRY:
            return BreakerState(
                level=level,
                position_size_multiplier=0.0,
                allow_new_entry=False,
                close_all=False,
                shutdown=False,
                message="L2: 日亏损超5%，禁止开新仓",
            )
        elif level == BreakerLevel.L3_CLOSE_ALL:
            return BreakerState(
                level=level,
                position_size_multiplier=0.0,
                allow_new_entry=False,
                close_all=True,
                shutdown=False,
                message="L3: 日亏损超8%，平所有仓，暂停24h",
            )
        else:  # L4
            return BreakerState(
                level=level,
                position_size_multiplier=0.0,
                allow_new_entry=False,
                close_all=True,
                shutdown=True,
                message="L4: 总亏损超15%，完全停机，需人工重启",
            )
