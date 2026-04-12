"""Alert system — Telegram, Discord webhook, email notifications.

Alert levels:
  INFO:     new position opened, position closed, strategy triggered
  WARNING:  approaching stop-loss, risk downgrade, AI rejected trade
  CRITICAL: circuit breaker triggered, system error, consecutive losses
"""

from __future__ import annotations

import asyncio
from enum import Enum

import structlog
import httpx

from config.settings import settings

logger = structlog.get_logger()


class AlertLevel(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


LEVEL_EMOJI = {
    AlertLevel.INFO: "ℹ️",
    AlertLevel.WARNING: "⚠️",
    AlertLevel.CRITICAL: "🚨",
}


class AlertManager:
    """Dispatches alerts to configured channels."""

    def __init__(self):
        self.telegram_enabled = bool(settings.telegram_bot_token and settings.telegram_chat_id)
        self.discord_enabled = bool(settings.discord_webhook_url)
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=10.0)
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def send(self, level: AlertLevel, title: str, message: str) -> None:
        """Send an alert to all enabled channels."""
        full_msg = f"{LEVEL_EMOJI.get(level, '')} [{level.value}] {title}\n\n{message}"
        logger.info("alert_sending", level=level.value, title=title)

        tasks = []
        if self.telegram_enabled:
            tasks.append(self._send_telegram(full_msg))
        if self.discord_enabled:
            tasks.append(self._send_discord(full_msg, level))

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, Exception):
                    logger.error("alert_send_failed", error=str(r))

    # ── Convenience methods ──────────────────────────────────────────────

    async def notify_trade_opened(
        self, symbol: str, direction: str, entry: float, quantity: float, strategy: str
    ) -> None:
        await self.send(
            AlertLevel.INFO,
            f"开仓 {symbol}",
            f"方向: {direction}\n入场: {entry}\n数量: {quantity}\n策略: {strategy}",
        )

    async def notify_trade_closed(
        self, symbol: str, direction: str, entry: float, exit_price: float, pnl: float, reason: str
    ) -> None:
        pnl_str = f"+{pnl:.2f}" if pnl > 0 else f"{pnl:.2f}"
        level = AlertLevel.INFO if pnl >= 0 else AlertLevel.WARNING
        await self.send(
            level,
            f"平仓 {symbol} | PnL: {pnl_str}",
            f"方向: {direction}\n入场: {entry}\n出场: {exit_price}\n原因: {reason}",
        )

    async def notify_circuit_breaker(self, level_name: str, message: str) -> None:
        await self.send(AlertLevel.CRITICAL, f"熔断触发 {level_name}", message)

    async def notify_risk_halt(self, reason: str) -> None:
        await self.send(AlertLevel.CRITICAL, "交易暂停", reason)

    async def notify_ai_rejection(self, symbol: str, reason: str) -> None:
        await self.send(AlertLevel.WARNING, f"AI拒绝 {symbol}", reason)

    async def notify_error(self, component: str, error: str) -> None:
        await self.send(AlertLevel.CRITICAL, f"系统异常: {component}", error)

    # ── Channel implementations ──────────────────────────────────────────

    async def _send_telegram(self, text: str) -> None:
        """Send message via Telegram Bot API."""
        client = await self._get_client()
        url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
        payload = {
            "chat_id": settings.telegram_chat_id,
            "text": text,
            "parse_mode": "HTML",
        }
        resp = await client.post(url, json=payload)
        if resp.status_code != 200:
            logger.warning("telegram_send_failed", status=resp.status_code, body=resp.text[:200])

    async def _send_discord(self, text: str, level: AlertLevel) -> None:
        """Send message via Discord webhook."""
        client = await self._get_client()
        color_map = {
            AlertLevel.INFO: 3447003,      # blue
            AlertLevel.WARNING: 16776960,   # yellow
            AlertLevel.CRITICAL: 15158332,  # red
        }
        payload = {
            "embeds": [{
                "description": text,
                "color": color_map.get(level, 3447003),
            }],
        }
        resp = await client.post(settings.discord_webhook_url, json=payload)
        if resp.status_code not in (200, 204):
            logger.warning("discord_send_failed", status=resp.status_code)
