"""Binance trading API client — handles authentication, signing, and order operations.

Supports both testnet and production. All trading operations go through this wrapper.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from urllib.parse import urlencode

import httpx
import structlog

from config.settings import settings

logger = structlog.get_logger()


class BinanceTradingClient:
    """Authenticated Binance client for order management."""

    def __init__(self, market: str = "futures_um"):
        self.market = market
        if market == "futures_um":
            self.base_url = settings.binance_futures_base
            self._api_prefix = "/fapi/v1"
        elif market == "futures_cm":
            self.base_url = settings.binance_coinm_base
            self._api_prefix = "/dapi/v1"
        else:
            self.base_url = settings.binance_spot_base
            self._api_prefix = "/api/v3"

        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=10.0,
                headers={"X-MBX-APIKEY": settings.binance_api_key},
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    def _sign(self, params: dict) -> dict:
        """Add timestamp and HMAC-SHA256 signature."""
        params["timestamp"] = int(time.time() * 1000)
        query_string = urlencode(params)
        signature = hmac.new(
            settings.binance_api_secret.encode(),
            query_string.encode(),
            hashlib.sha256,
        ).hexdigest()
        params["signature"] = signature
        return params

    # ── Market Data ──────────────────────────────────────────────────────

    async def get_price(self, symbol: str) -> float:
        client = await self._get_client()
        resp = await client.get(
            f"{self._api_prefix}/ticker/price",
            params={"symbol": symbol},
        )
        resp.raise_for_status()
        return float(resp.json()["price"])

    async def get_exchange_info(self, symbol: str) -> dict:
        """Get trading rules for a symbol (precision, filters, etc)."""
        client = await self._get_client()
        resp = await client.get(f"{self._api_prefix}/exchangeInfo")
        resp.raise_for_status()
        data = resp.json()
        for s in data.get("symbols", []):
            if s["symbol"] == symbol:
                return s
        return {}

    # ── Account ──────────────────────────────────────────────────────────

    async def get_account(self) -> dict:
        client = await self._get_client()
        params = self._sign({})
        # Futures uses v3 for account endpoint; spot uses v3 via _api_prefix
        if self.market in ("futures_um", "futures_cm"):
            prefix = self._api_prefix.replace("/v1", "/v3")
            resp = await client.get(f"{prefix}/account", params=params)
        else:
            resp = await client.get(f"{self._api_prefix}/account", params=params)
        resp.raise_for_status()
        return resp.json()

    async def get_balance(self) -> dict:
        """Get simplified balance summary."""
        account = await self.get_account()
        if self.market == "futures_um":
            return {
                "total": float(account.get("totalWalletBalance", 0)),
                "available": float(account.get("availableBalance", 0)),
                "used_margin": float(account.get("totalInitialMargin", 0)),
                "unrealized_pnl": float(account.get("totalUnrealizedProfit", 0)),
            }
        else:
            # Spot
            balances = {b["asset"]: float(b["free"]) for b in account.get("balances", [])}
            return {
                "total": balances.get("USDT", 0),
                "available": balances.get("USDT", 0),
                "used_margin": 0,
                "unrealized_pnl": 0,
            }

    async def get_positions(self) -> list[dict]:
        """Get open positions (futures only)."""
        if self.market not in ("futures_um", "futures_cm"):
            return []
        account = await self.get_account()
        positions = []
        for p in account.get("positions", []):
            amt = float(p.get("positionAmt", 0))
            if amt != 0:
                positions.append({
                    "symbol": p["symbol"],
                    "side": "LONG" if amt > 0 else "SHORT",
                    "quantity": abs(amt),
                    "entry_price": float(p.get("entryPrice", 0)),
                    "unrealized_pnl": float(p.get("unrealizedProfit", 0)),
                    "leverage": int(p.get("leverage", 1)),
                    "margin_type": p.get("marginType", "cross"),
                })
        return positions

    # ── Orders ───────────────────────────────────────────────────────────

    async def place_order(
        self,
        symbol: str,
        side: str,            # BUY / SELL
        order_type: str,      # MARKET / LIMIT / STOP_MARKET / TAKE_PROFIT_MARKET
        quantity: float,
        price: float | None = None,
        stop_price: float | None = None,
        time_in_force: str | None = None,
        reduce_only: bool = False,
        position_side: str | None = None,
    ) -> dict:
        """Place an order on Binance."""
        params = {
            "symbol": symbol,
            "side": side,
            "type": order_type,
            "quantity": quantity,
        }
        # Support hedge mode (dual position side)
        if position_side:
            params["positionSide"] = position_side
        elif self.market in ("futures_um", "futures_cm"):
            # Auto-detect: BUY → LONG, SELL → SHORT for opening positions
            if not reduce_only:
                params["positionSide"] = "LONG" if side == "BUY" else "SHORT"
            else:
                params["positionSide"] = "SHORT" if side == "BUY" else "LONG"
        if price is not None:
            params["price"] = price
        if stop_price is not None:
            params["stopPrice"] = stop_price
        if time_in_force:
            params["timeInForce"] = time_in_force
        elif order_type == "LIMIT":
            params["timeInForce"] = "GTC"
        # In hedge mode, positionSide already implies direction; reduceOnly is not allowed
        if reduce_only and self.market != "spot" and "positionSide" not in params:
            params["reduceOnly"] = "true"

        params = self._sign(params)
        client = await self._get_client()

        logger.info("placing_order", **{k: v for k, v in params.items() if k != "signature"})
        resp = await client.post(f"{self._api_prefix}/order", params=params)
        if resp.status_code != 200:
            logger.error("order_error", status=resp.status_code, body=resp.text)
        resp.raise_for_status()
        result = resp.json()
        logger.info("order_placed", order_id=result.get("orderId"), status=result.get("status"))
        return result

    async def place_algo_order(
        self,
        symbol: str,
        side: str,
        order_type: str,       # STOP_MARKET / TAKE_PROFIT_MARKET / STOP / TRAILING_STOP_MARKET
        trigger_price: float,
        quantity: float | None = None,
        position_side: str | None = None,
        close_position: bool = False,
        working_type: str = "MARK_PRICE",
        price_protect: bool = True,
    ) -> dict:
        """Place a conditional/algo order on Binance Futures (new endpoint since 2025-12)."""
        params: dict = {
            "algoType": "CONDITIONAL",
            "symbol": symbol,
            "side": side,
            "type": order_type,
            "triggerPrice": trigger_price,
            "workingType": working_type,
        }
        if position_side:
            params["positionSide"] = position_side
        if close_position:
            params["closePosition"] = "true"
        elif quantity is not None:
            params["quantity"] = quantity
        if price_protect:
            params["priceProtect"] = "TRUE"

        params = self._sign(params)
        client = await self._get_client()
        logger.info("placing_algo_order", **{k: v for k, v in params.items() if k != "signature"})
        resp = await client.post(f"{self._api_prefix.replace('/v1', '/v1')}/algoOrder", params=params)
        if resp.status_code != 200:
            logger.error("algo_order_error", status=resp.status_code, body=resp.text)
        resp.raise_for_status()
        result = resp.json()
        logger.info("algo_order_placed", algo_id=result.get("algoId"), status=result.get("status"))
        return result

    async def cancel_algo_order(self, symbol: str, algo_id: int) -> dict:
        params = self._sign({"symbol": symbol, "algoId": algo_id})
        client = await self._get_client()
        resp = await client.delete(f"{self._api_prefix}/algoOrder", params=params)
        resp.raise_for_status()
        return resp.json()

    async def cancel_order(self, symbol: str, order_id: int) -> dict:
        params = self._sign({"symbol": symbol, "orderId": order_id})
        client = await self._get_client()
        resp = await client.delete(f"{self._api_prefix}/order", params=params)
        resp.raise_for_status()
        return resp.json()

    async def get_open_orders(self, symbol: str | None = None) -> list[dict]:
        params: dict = {}
        if symbol:
            params["symbol"] = symbol
        params = self._sign(params)
        client = await self._get_client()
        resp = await client.get(f"{self._api_prefix}/openOrders", params=params)
        resp.raise_for_status()
        return resp.json()

    async def set_leverage(self, symbol: str, leverage: int) -> dict:
        """Set leverage for a futures symbol."""
        if self.market == "spot":
            return {}
        params = self._sign({"symbol": symbol, "leverage": leverage})
        client = await self._get_client()
        resp = await client.post(f"{self._api_prefix}/leverage", params=params)
        resp.raise_for_status()
        return resp.json()

    # ── Symbol Precision ─────────────────────────────────────────────────

    async def get_symbol_precision(self, symbol: str) -> tuple[int, int]:
        """Return (quantity_precision, price_precision) for a symbol."""
        info = await self.get_exchange_info(symbol)
        qty_precision = int(info.get("quantityPrecision", 3))
        price_precision = int(info.get("pricePrecision", 2))
        return qty_precision, price_precision

    def round_quantity(self, quantity: float, precision: int) -> float:
        return round(quantity, precision)

    def round_price(self, price: float, precision: int) -> float:
        return round(price, precision)
