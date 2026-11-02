"""Entirely synthetic offline demo. No real APIs, no live orders."""
from __future__ import annotations
from datetime import date, timedelta
from .indicators import _mock_bars


def snapshot() -> dict:
    return {
        "source": "SYNTHETIC_DEMO_NOT_ALPACA", "paper": True,
        "account": {"equity": 100000., "cash": 85000., "buying_power": 85000.,
                    "portfolio_value": 100000., "trading_blocked": False},
        "positions": [
            {"symbol": "QQQ", "side": "long", "qty": 3., "avg_entry_price": 570.,
             "current_price": 600., "market_value": 1800., "cost_basis": 1710.,
             "unrealized_pl": 90., "unrealized_plpc": 90. / 1710., "portfolio_weight_pct": 1.8},
            {"symbol": "SQQQ", "side": "long", "qty": 10., "avg_entry_price": 55.,
             "current_price": 50., "market_value": 500., "cost_basis": 550.,
             "unrealized_pl": -50., "unrealized_plpc": -50. / 550., "portfolio_weight_pct": 0.5},
        ]
    }


def bars(ticker: str, start: date, end: date) -> dict:
    return {"ticker": ticker, "start_date": start.isoformat(), "end_date": end.isoformat(),
            "source": "SYNTHETIC_DEMO_NOT_ALPACA", "feed": "synthetic",
            "bars": _mock_bars(ticker, start, end)}
