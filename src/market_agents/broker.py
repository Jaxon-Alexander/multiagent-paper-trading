"""Alpaca PAPER brokerage gateway, account/positions and explicitly approved LIMIT orders.

TradingClient(paper=True) is hard-coded; no live trading endpoint is exposed.
No LLM may invoke this module's order submission method.
"""
from __future__ import annotations
from decimal import Decimal, InvalidOperation
import os
from typing import Any
from dotenv import load_dotenv
from .indicators import SYMBOL


def number(value: Any) -> float | None:
    if value is None: return None
    try:
        n = Decimal(str(value))
        return float(n) if n.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def _decimal(value, name) -> Decimal:
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"{name} must be a positive decimal") from exc
    if not d.is_finite() or d <= 0:
        raise ValueError(f"{name} must be a finite positive decimal")
    return d


def normalize_position(pos: Any, equity: float | None) -> dict:
    market_value = number(getattr(pos, "market_value", None))
    weight = round(abs(market_value) / equity * 100, 4) if market_value is not None and equity and equity > 0 else None
    return {
        "symbol": str(getattr(pos, "symbol", "")).upper(),
        "side": str(getattr(getattr(pos, "side", None), "value", getattr(pos, "side", ""))),
        "qty": number(getattr(pos, "qty", None)),
        "avg_entry_price": number(getattr(pos, "avg_entry_price", None)),
        "current_price": number(getattr(pos, "current_price", None)),
        "market_value": market_value,
        "cost_basis": number(getattr(pos, "cost_basis", None)),
        "unrealized_pl": number(getattr(pos, "unrealized_pl", None)),
        "unrealized_plpc": number(getattr(pos, "unrealized_plpc", None)),
        "portfolio_weight_pct": weight,
    }


class AlpacaPaperBroker:
    def __init__(self, client=None):
        load_dotenv()
        if client is None:
            key = os.getenv("ALPACA_PAPER_API_KEY")
            secret = os.getenv("ALPACA_PAPER_SECRET_KEY")
            if (not key or not secret or key.startswith('REPLACE_WITH_')
                    or secret.startswith('REPLACE_WITH_')):
                raise RuntimeError("Set real ALPACA_PAPER_API_KEY and ALPACA_PAPER_SECRET_KEY (paper keys only)")
            from alpaca.trading.client import TradingClient
            client = TradingClient(key, secret, paper=True)
        self.client = client

    def snapshot(self) -> dict:
        account = self.client.get_account()
        equity = number(getattr(account, "equity", None))
        positions = [normalize_position(p, equity) for p in self.client.get_all_positions()]
        # No personally identifying account information, IDs or credentials in output.
        return {
            "source": "alpaca_paper", "paper": True,
            "account": {
                "equity": equity,
                "cash": number(getattr(account, "cash", None)),
                "buying_power": number(getattr(account, "buying_power", None)),
                "portfolio_value": number(getattr(account, "portfolio_value", None)),
                "trading_blocked": bool(getattr(account, "trading_blocked", True)),
            },
            "positions": sorted(positions, key=lambda x: x["symbol"]),
        }

    def preview_limit_order(self, *, symbol: str, side: str, qty: int, limit_price: str,
                            snapshot: dict | None = None) -> dict:
        """Validate locally, never transmit order. BUY cannot short, max gross order/position."""
        symbol = symbol.strip().upper() if isinstance(symbol, str) else ""
        if not SYMBOL.fullmatch(symbol): raise ValueError("Invalid ticker")
        side = side.lower() if isinstance(side, str) else ""
        if side not in ("buy", "sell"): raise ValueError("side must be buy or sell")
        if type(qty) is not int or qty < 1 or qty > 100:
            raise ValueError("qty must be an integer between 1 and 100")
        limit = _decimal(limit_price, "limit_price")
        notional = limit * qty
        max_order = _decimal(os.getenv("MAX_PAPER_ORDER_NOTIONAL", "1000"), "MAX_PAPER_ORDER_NOTIONAL")
        if notional > max_order:
            raise ValueError(f"Order value {notional} exceeds project limit {max_order}")
        snapshot = snapshot or self.snapshot()
        if snapshot.get("paper") is not True:
            raise ValueError("Only PAPER accounts supported")
        account = snapshot["account"]
        if account.get("trading_blocked"):
            raise ValueError("Broker reports paper account trading blocked")
        held = next((p for p in snapshot["positions"] if p["symbol"] == symbol), None)
        if side == "sell":
            if not held or held.get("side", "").lower() not in ("long", "positionside.long") or (held.get("qty") or 0) < qty:
                raise ValueError("Sell orders must be covered by existing LONG paper shares (no short-selling)")
        if side == "buy":
            bp = account.get("buying_power")
            if bp is None or Decimal(str(bp)) < notional:
                raise ValueError("Insufficient or unavailable paper buying power")
            equity = account.get("equity")
            if equity is None or equity <= 0:
                raise ValueError("Cannot validate account equity")
            current_value = abs(Decimal(str((held or {}).get("market_value") or 0)))
            max_fraction = _decimal(os.getenv("MAX_PAPER_POSITION_PCT", "20"), "MAX_PAPER_POSITION_PCT")
            if max_fraction > 100: raise ValueError("MAX_PAPER_POSITION_PCT must be <= 100")
            if (current_value + notional) * 100 > Decimal(str(equity)) * max_fraction:
                raise ValueError("Proposed position would exceed project portfolio allocation cap")
        return {"paper": True, "symbol": symbol, "side": side, "qty": qty,
                "order_type": "LIMIT", "limit_price": str(limit), "time_in_force": "DAY",
                "maximum_projected_value": str(notional), "status": "PREVIEW_ONLY",
                "note": "Limit orders may fill partially or not at all; market conditions change."}

    def submit_limit_order(self, preview: dict, *, confirmation: bool = False) -> dict:
        """Only explicit CLI invocation after renewed broker-side validation can call this."""
        if not confirmation:
            raise PermissionError("Explicit --confirm-paper is required")
        if os.getenv("ENABLE_PAPER_ORDERS", "false").lower() != "true":
            raise PermissionError("Set ENABLE_PAPER_ORDERS=true to enable explicit paper limit orders")
        if not preview.get("paper") or preview.get("status") != "PREVIEW_ONLY":
            raise ValueError("Expected a validated paper-order preview")
        # Re-evaluate against a NEW account/position snapshot to minimize stale-risk gates.
        fresh = self.preview_limit_order(symbol=preview["symbol"], side=preview["side"],
                                         qty=preview["qty"], limit_price=preview["limit_price"])
        asset = self.client.get_asset(fresh["symbol"])
        if not getattr(asset, "tradable", False):
            raise ValueError("Broker asset is not tradable")
        from alpaca.trading.requests import GetOrdersRequest, LimitOrderRequest
        from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus
        open_orders = self.client.get_orders(filter=GetOrdersRequest(status=QueryOrderStatus.OPEN))
        if any(str(getattr(item, "symbol", "")).upper() == fresh["symbol"] for item in open_orders):
            raise ValueError("Open order exists for this symbol; reconcile it before placing another")
        order = LimitOrderRequest(symbol=fresh["symbol"], qty=fresh["qty"],
                                  side=OrderSide.BUY if fresh["side"] == "buy" else OrderSide.SELL,
                                  limit_price=float(Decimal(fresh["limit_price"])),
                                  time_in_force=TimeInForce.DAY)
        result = self.client.submit_order(order_data=order)
        return {"paper": True, "status": str(getattr(result, "status", "submitted")),
                "symbol": fresh["symbol"], "side": fresh["side"], "qty": fresh["qty"],
                "limit_price": fresh["limit_price"], "order_id": str(getattr(result, "id", ""))}
