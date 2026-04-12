"""Strategy abstract base class and core signal types."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
import time


class Signal(str, Enum):
    LONG = "long"
    SHORT = "short"
    CLOSE_LONG = "close_long"
    CLOSE_SHORT = "close_short"
    HOLD = "hold"


@dataclass
class TradeSignal:
    """A trading signal produced by a strategy."""

    strategy_name: str
    symbol: str
    market: str
    signal: Signal
    confidence: float               # 0.0 – 1.0
    entry_price: float
    stop_loss: float
    take_profit: float
    position_size_pct: float        # suggested position as % of total equity
    reasoning: str
    tags: list[str] = field(default_factory=list)
    timestamp: int = 0

    def __post_init__(self):
        if self.timestamp == 0:
            self.timestamp = int(time.time() * 1000)


class BaseStrategy(ABC):
    """All strategies inherit from this base class."""

    def __init__(self, config: dict):
        self.name: str = config["name"]
        self.enabled: bool = config.get("enabled", True)
        self.config = config

    @abstractmethod
    async def evaluate(self, candidate, klines: list) -> TradeSignal | None:
        """Evaluate a single candidate. Return a signal or None."""
        ...

    def check_conditions(self, candidate, conditions: list[dict]) -> bool:
        """Generic condition checker used by YAML-driven strategies."""
        for cond in conditions:
            indicator = cond["indicator"]
            value = getattr(candidate, indicator, None)
            if value is None:
                return False
            op = cond["operator"]
            target = cond["value"]
            if op == ">" and not (value > target):
                return False
            if op == "<" and not (value < target):
                return False
            if op == ">=" and not (value >= target):
                return False
            if op == "<=" and not (value <= target):
                return False
            if op == "==" and not (value == target):
                return False
            if op == "!=" and not (value != target):
                return False
            if op == "between" and not (target[0] <= value <= target[1]):
                return False
        return True

    def compute_stop_take(
        self, price: float, direction: str, stop_pct: float, tp_pct: float
    ) -> tuple[float, float]:
        """Compute stop-loss and take-profit prices from percentages."""
        if direction == "long":
            stop_loss = price * (1 - stop_pct / 100)
            take_profit = price * (1 + tp_pct / 100)
        else:
            stop_loss = price * (1 + stop_pct / 100)
            take_profit = price * (1 - tp_pct / 100)
        return round(stop_loss, 8), round(take_profit, 8)
