"""Global configuration — reads from environment variables / .env file."""

from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    # Binance
    binance_api_key: str = ""
    binance_api_secret: str = ""
    binance_testnet: bool = True

    # Binance base URLs (auto-set based on testnet flag)
    @property
    def binance_spot_base(self) -> str:
        if self.binance_testnet:
            return "https://testnet.binance.vision"
        return "https://api.binance.com"

    @property
    def binance_futures_base(self) -> str:
        if self.binance_testnet:
            return "https://testnet.binancefuture.com"
        return "https://fapi.binance.com"

    @property
    def binance_coinm_base(self) -> str:
        if self.binance_testnet:
            return "https://testnet.binancefuture.com"
        return "https://dapi.binance.com"

    @property
    def binance_spot_ws(self) -> str:
        if self.binance_testnet:
            return "wss://testnet.binance.vision/ws"
        return "wss://stream.binance.com:9443/ws"

    @property
    def binance_futures_ws(self) -> str:
        if self.binance_testnet:
            return "wss://fstream.binancefuture.com/ws"
        return "wss://fstream.binance.com/ws"

    # Claude AI
    anthropic_api_key: str = ""
    claude_model: str = "claude-sonnet-4-20250514"

    # Database
    database_url: str = "sqlite+aiosqlite:///./trading_bot.db"

    # Risk
    max_loss_per_trade_pct: float = 2.0
    max_daily_loss_pct: float = 5.0
    max_total_exposure_pct: float = 50.0
    max_leverage: int = 5

    # Alerts
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    discord_webhook_url: str = ""

    # System
    log_level: str = "INFO"
    ticker_interval: int = 10
    screener_interval: int = 30
    strategy_interval: int = 30


settings = Settings()
