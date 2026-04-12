"""WebSocket stream manager for real-time Binance data.

Streams:
  !ticker@arr                     — All-market ticker (spot/futures)
  <symbol>@kline_<interval>       — Kline stream
  <symbol>@aggTrade               — Aggregated trades
  <symbol>@depth@100ms            — Order book depth
  <symbol>@markPrice@1s           — Mark price (futures)
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Callable, Coroutine

import structlog
import websockets
from websockets.asyncio.client import ClientConnection

from config.settings import settings

logger = structlog.get_logger()

Callback = Callable[[dict[str, Any]], Coroutine[Any, Any, None]]


class WebSocketManager:
    """Manages multiple WebSocket connections with auto-reconnect."""

    def __init__(self):
        self._connections: dict[str, asyncio.Task] = {}
        self._running = False

    async def start(self) -> None:
        self._running = True

    async def stop(self) -> None:
        self._running = False
        for name, task in self._connections.items():
            task.cancel()
            logger.info("ws_stream_stopped", stream=name)
        self._connections.clear()

    def subscribe(
        self,
        name: str,
        url: str,
        streams: list[str],
        callback: Callback,
    ) -> None:
        """Subscribe to one or more streams on a single connection."""
        if name in self._connections:
            logger.warning("ws_stream_already_exists", stream=name)
            return
        task = asyncio.create_task(self._run_stream(name, url, streams, callback))
        self._connections[name] = task

    async def _run_stream(
        self,
        name: str,
        url: str,
        streams: list[str],
        callback: Callback,
    ) -> None:
        """Run a WebSocket stream with auto-reconnect."""
        # Build combined stream URL
        if streams:
            stream_path = "/".join(streams)
            full_url = f"{url}/{stream_path}"
        else:
            full_url = url

        backoff = 1.0
        while self._running:
            try:
                logger.info("ws_connecting", stream=name, url=full_url)
                async with websockets.connect(full_url, ping_interval=20) as ws:
                    backoff = 1.0  # reset on successful connect
                    logger.info("ws_connected", stream=name)
                    async for raw_msg in ws:
                        try:
                            data = json.loads(raw_msg)
                            await callback(data)
                        except json.JSONDecodeError:
                            logger.warning("ws_json_error", stream=name)
                        except Exception as e:
                            logger.error("ws_callback_error", stream=name, error=str(e))
            except websockets.ConnectionClosed as e:
                logger.warning("ws_disconnected", stream=name, code=e.code, reason=e.reason)
            except Exception as e:
                logger.error("ws_error", stream=name, error=str(e))

            if self._running:
                logger.info("ws_reconnecting", stream=name, backoff=backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)

    # ── Convenience methods ──────────────────────────────────────────────

    def subscribe_futures_tickers(self, callback: Callback) -> None:
        """Subscribe to all USDT-M futures tickers."""
        self.subscribe(
            name="futures_all_tickers",
            url=settings.binance_futures_ws,
            streams=["!ticker@arr"],
            callback=callback,
        )

    def subscribe_spot_tickers(self, callback: Callback) -> None:
        """Subscribe to all spot tickers."""
        self.subscribe(
            name="spot_all_tickers",
            url=settings.binance_spot_ws,
            streams=["!ticker@arr"],
            callback=callback,
        )

    def subscribe_klines(
        self, symbols: list[str], interval: str, callback: Callback, market: str = "futures"
    ) -> None:
        """Subscribe to kline streams for specific symbols."""
        streams = [f"{s.lower()}@kline_{interval}" for s in symbols]
        ws_url = settings.binance_futures_ws if market == "futures" else settings.binance_spot_ws
        self.subscribe(
            name=f"klines_{market}_{interval}",
            url=ws_url,
            streams=streams,
            callback=callback,
        )

    def subscribe_mark_price(self, symbols: list[str], callback: Callback) -> None:
        """Subscribe to mark price for specific futures symbols."""
        streams = [f"{s.lower()}@markPrice@1s" for s in symbols]
        self.subscribe(
            name="mark_price",
            url=settings.binance_futures_ws,
            streams=streams,
            callback=callback,
        )
