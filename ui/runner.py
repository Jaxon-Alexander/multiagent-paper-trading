"""Thin helper between the web page and the existing analysis code.

This file contains NO trading logic. It only calls MultiAgentOrchestrator.analyze(),
so every existing guardrail (prompt check, output filter, report check) still applies.
There is deliberately no function here that can place an order: preview_order() only
VALIDATES an order (broker.preview_limit_order); submit_limit_order is never imported or called.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:      # lets the page run even if 'pip install -e .' was skipped
    sys.path.insert(0, str(ROOT / "src"))

from market_agents.broker import AlpacaPaperBroker  # noqa: E402
from market_agents.demo import snapshot as demo_snapshot  # noqa: E402
from market_agents.guardrails import sanitize_agent_result  # noqa: E402
from market_agents.orchestrator import MultiAgentOrchestrator  # noqa: E402

TICKER = re.compile(r"[A-Za-z.\-]{1,10}")


def parse_symbols(text: str) -> list[str]:
    """'QQQ, sqqq  AAPL' -> ['QQQ', 'SQQQ', 'AAPL'] (duplicates removed, max 15)."""
    parts = [p.strip().upper() for p in re.split(r"[,\s;]+", text or "") if p.strip()]
    for p in parts:
        if not TICKER.fullmatch(p):
            raise ValueError(f"'{p}' is not a valid ticker (letters only, up to 10 characters).")
    return list(dict.fromkeys(parts))


def save_trace(events: list[dict]) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path = ROOT / "traces" / f"trace_ui_{stamp}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(events, indent=2, default=str), encoding="utf-8")
    return str(path)


def run_analysis(symbols: list[str], *, live: bool, days: int = 125, prompt: str = "",
                 start_date: str | None = None, end_date: str | None = None) -> dict:
    """Run one analysis. Returns {'report':..., 'events':..., 'trace_path':...}.

    live=False -> offline synthetic demo, no Gemini/Alpaca calls.
    live=True  -> real Gemini + Alpaca PAPER read-only data (needs keys in .env).
    Errors (bad prompt, missing keys, ...) are raised and shown on the page.
    """
    system = MultiAgentOrchestrator(demo=not live)
    try:
        report = system.analyze(symbols, days=days, prompt=prompt,
                                start_date=start_date, end_date=end_date)
    finally:
        events = list(system.events)
    return {"report": report, "events": events, "trace_path": save_trace(events), "live": live}


def preview_order(symbol: str, side: str, qty: int, limit_price: str, *, live: bool) -> dict:
    """Validate a paper LIMIT order WITHOUT sending it (same checks as `order-preview`).

    demo -> checked against the synthetic account, no keys, no network.
    live -> checked against the real Alpaca PAPER account (read-only call, keys from .env).
    Raises ValueError/RuntimeError with a plain message if the order breaks a project limit.
    """
    if live:
        broker = AlpacaPaperBroker()
        result = broker.preview_limit_order(symbol=symbol, side=side, qty=qty, limit_price=limit_price)
    else:
        broker = AlpacaPaperBroker(client=object())          # no real client: never touches the network
        result = broker.preview_limit_order(symbol=symbol, side=side, qty=qty,
                                            limit_price=limit_price, snapshot=demo_snapshot())
    result, _ = sanitize_agent_result(result)
    return result
