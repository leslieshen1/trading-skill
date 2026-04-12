"""Load strategy configurations from YAML files."""

from __future__ import annotations

from pathlib import Path

import structlog
import yaml

from src.strategy.base import BaseStrategy
from src.strategy.builtin.breakout import BreakoutStrategy
from src.strategy.builtin.funding_arb import FundingArbStrategy
from src.strategy.builtin.mean_reversion import MeanReversionStrategy
from src.strategy.builtin.momentum import MomentumStrategy

logger = structlog.get_logger()

# Map strategy type → implementation class.
# The YAML file name (without extension) is used as the key when there's no
# explicit "type" field; otherwise fallback to GenericYAMLStrategy.
BUILTIN_STRATEGIES: dict[str, type[BaseStrategy]] = {
    "momentum": MomentumStrategy,
    "funding_arb": FundingArbStrategy,
    "mean_reversion": MeanReversionStrategy,
    "breakout": BreakoutStrategy,
}


class GenericYAMLStrategy(BaseStrategy):
    """Fallback strategy driven entirely by YAML conditions."""

    async def evaluate(self, candidate, klines: list):
        from src.strategy.base import Signal, TradeSignal

        entry_cfg = self.config.get("entry", {})
        conditions = entry_cfg.get("conditions", [])
        direction = entry_cfg.get("direction", "long")

        if not self.check_conditions(candidate, conditions):
            # Check alt conditions if present
            alt_conditions = entry_cfg.get("alt_conditions")
            if alt_conditions and self.check_conditions(candidate, alt_conditions):
                direction = entry_cfg.get("alt_direction", "short")
            else:
                return None

        exit_cfg = self.config.get("exit", {})
        stop_pct = exit_cfg.get("stop_loss", 2.0)
        tp_pct = exit_cfg.get("take_profit", 5.0)

        stop_loss, take_profit = self.compute_stop_take(
            candidate.price, direction, stop_pct, tp_pct
        )

        pos_cfg = self.config.get("position", {})
        signal_type = Signal.LONG if direction == "long" else Signal.SHORT

        return TradeSignal(
            strategy_name=self.name,
            symbol=candidate.symbol,
            market=candidate.market,
            signal=signal_type,
            confidence=0.6,
            entry_price=candidate.price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            position_size_pct=pos_cfg.get("risk_per_trade", 1.0),
            reasoning=f"YAML conditions met for {direction}",
            tags=candidate.tags if candidate.tags else [],
        )


def load_strategies(strategy_dir: str | Path | None = None) -> list[BaseStrategy]:
    """Load all .yaml strategy files from the given directory."""
    if strategy_dir is None:
        strategy_dir = Path(__file__).resolve().parent.parent.parent / "config" / "strategies"
    else:
        strategy_dir = Path(strategy_dir)

    strategies: list[BaseStrategy] = []

    if not strategy_dir.exists():
        logger.warning("strategy_dir_not_found", path=str(strategy_dir))
        return strategies

    for yaml_file in sorted(strategy_dir.glob("*.yaml")):
        try:
            with open(yaml_file) as f:
                config = yaml.safe_load(f)

            if not config or not config.get("enabled", True):
                logger.info("strategy_skipped", file=yaml_file.name, reason="disabled")
                continue

            # Determine strategy class
            strategy_type = config.get("type", yaml_file.stem.replace("example_", ""))
            cls = BUILTIN_STRATEGIES.get(strategy_type, GenericYAMLStrategy)
            strategy = cls(config)
            strategies.append(strategy)
            logger.info("strategy_loaded", name=strategy.name, type=cls.__name__)

        except Exception as e:
            logger.error("strategy_load_error", file=yaml_file.name, error=str(e))

    return strategies
