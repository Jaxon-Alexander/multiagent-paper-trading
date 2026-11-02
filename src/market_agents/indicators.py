"""Lab 3/4 market-data retrieval and deterministic technical math; no LLM calculations."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import math
import re
import statistics
from typing import Any

SYMBOL = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


def validate_dates(ticker: str, start_date: str, end_date: str):
    if not isinstance(ticker, str) or not SYMBOL.fullmatch(ticker.upper()):
        raise ValueError("ticker must be a valid US-style ticker (1-10 characters)")
    try:
        start, end = date.fromisoformat(start_date), date.fromisoformat(end_date)
    except (TypeError, ValueError) as exc:
        raise ValueError("Dates must use YYYY-MM-DD") from exc
    if start > end:
        raise ValueError("start_date must not exceed end_date")
    if (end - start).days > 730:
        raise ValueError("Limit requests to 730 calendar days for this prototype")
    if start > date.today():
        raise ValueError("Cannot request a future-only start date")
    return ticker.upper(), start, end


def _mock_bars(ticker: str, start: date, end: date) -> list[dict[str, Any]]:
    """Illustrative SYNTHETIC data; never represent as actual market evidence."""
    bars = []
    day, i = start, 0
    base = 80 + sum(map(ord, ticker)) % 50
    while day <= end:
        if day.weekday() < 5:
            close = round(base + 0.19 * i + 2.1 * math.sin(i / 4.7), 4)
            volume = 800000 + (i % 9) * 50000
            bars.append({"date": day.isoformat(), "open": round(close - .4, 4),
                         "high": round(close + 1.2, 4), "low": round(close - 1.1, 4),
                         "close": close, "volume": volume})
            i += 1
        day += timedelta(days=1)
    return bars


def get_stock_data(ticker: str, start_date: str, end_date: str,
                   *, mock: bool = False) -> dict[str, Any]:
    ticker, start, end = validate_dates(ticker, start_date, end_date)
    if mock:
        bars = _mock_bars(ticker, start, end)
        return {"ticker": ticker, "start_date": start_date, "end_date": end_date,
                "source": "SYNTHETIC_DEMO_NOT_REAL_MARKET_DATA", "feed": "synthetic",
                "count": len(bars), "bars": bars}

    import os
    from alpaca.data.enums import DataFeed
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame

    from dotenv import load_dotenv
    load_dotenv()
    def configured(name):
        value = os.getenv(name, "").strip()
        return value if value and not value.startswith("REPLACE_WITH_") else None
    data_key = configured("ALPACA_API_KEY")
    data_secret = configured("ALPACA_SECRET_KEY")
    paper_key = configured("ALPACA_PAPER_API_KEY")
    paper_secret = configured("ALPACA_PAPER_SECRET_KEY")
    if data_key and data_secret:
        key, secret = data_key, data_secret
    elif paper_key and paper_secret:
        key, secret = paper_key, paper_secret
    else:
        raise RuntimeError("Set a complete Alpaca market-data or PAPER credential pair in .env")
    client = StockHistoricalDataClient(key, secret)
    # Alpaca's `end` is exclusive; +1 day makes the user-specified date inclusive.
    request = StockBarsRequest(
        symbol_or_symbols=ticker,
        timeframe=TimeFrame.Day,
        start=datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc),
        end=datetime.combine(end + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc),
        feed=DataFeed.IEX,  # Free plan coverage; may differ from consolidated SIP prices.
    )
    response = client.get_stock_bars(request)
    records = response.data.get(ticker, [])
    bars = []
    for item in records:
        bar_day = item.timestamp.date()
        if start <= bar_day <= end:
            bars.append({"date": bar_day.isoformat(), "open": float(item.open),
                         "high": float(item.high), "low": float(item.low),
                         "close": float(item.close), "volume": int(item.volume)})
    bars.sort(key=lambda bar: bar["date"])
    return {"ticker": ticker, "start_date": start_date, "end_date": end_date,
            "source": "alpaca", "feed": "IEX", "count": len(bars), "bars": bars}


def calculate_technical_indicators(closing_prices: list[float]) -> dict[str, float | None]:
    if not isinstance(closing_prices, list) or not closing_prices:
        raise ValueError("closing_prices must be a nonempty list")
    if len(closing_prices) > 1000:
        raise ValueError("At most 1000 closing prices are supported")
    prices = []
    for p in closing_prices:
        if isinstance(p, bool) or not isinstance(p, (int, float)) or not math.isfinite(p) or p <= 0:
            raise ValueError("All closing prices must be finite positive numbers")
        prices.append(float(p))

    def rsi_wilder(period=14):
        if len(prices) < period + 1:
            return None
        changes = [b - a for a, b in zip(prices, prices[1:])]
        gains = [max(0.0, x) for x in changes]
        losses = [max(0.0, -x) for x in changes]
        average_gain = sum(gains[:period]) / period
        average_loss = sum(losses[:period]) / period
        for gain, loss in zip(gains[period:], losses[period:]):
            average_gain = (average_gain * (period - 1) + gain) / period
            average_loss = (average_loss * (period - 1) + loss) / period
        if average_loss == 0:
            return 100.0 if average_gain > 0 else 50.0
        if average_gain == 0:
            return 0.0
        return 100.0 - 100.0 / (1.0 + average_gain / average_loss)

    returns = [b / a - 1.0 for a, b in zip(prices, prices[1:])]
    vol = (statistics.stdev(returns[-30:]) * math.sqrt(252) * 100
           if len(returns) >= 30 else None)
    return {
        "sma_20": round(statistics.mean(prices[-20:]), 4) if len(prices) >= 20 else None,
        "sma_50": round(statistics.mean(prices[-50:]), 4) if len(prices) >= 50 else None,
        "rsi_14": round(rsi_wilder(), 4) if len(prices) >= 15 else None,
        "volatility_30d": round(vol, 4) if vol is not None else None,
    }


def build_analysis(stock: dict | None, indicators: dict | None) -> dict[str, Any]:
    """Deterministic Lab #2 JSON: no fabricated numeric values or model arithmetic."""
    bars = stock.get("bars", []) if stock else []
    last = bars[-1] if bars else None
    indicators = indicators or {k: None for k in ("sma_20", "sma_50", "rsi_14", "volatility_30d")}
    result = {
        "ticker": stock.get("ticker") if stock else None,
        "observation_time": last["date"] if last else None,
        "current_price": last["close"] if last else None,
        "current_volume": last["volume"] if last else None,
        "average_volume": round(statistics.mean(b["volume"] for b in bars[-20:]), 2)
                          if len(bars) >= 20 else None,
        "trend": "UNKNOWN", "momentum": "UNKNOWN", "volatility": "UNKNOWN",
        "indicators": {k: indicators.get(k) for k in ("sma_20", "sma_50", "rsi_14", "volatility_30d")},
        "unusual_conditions": [], "uncertainty": None,
    }
    warnings = []
    p, s20, s50 = result["current_price"], indicators.get("sma_20"), indicators.get("sma_50")
    if p is not None and s20 is not None and s50 is not None:
        if p > s20 and p > s50:
            result["trend"] = "BULLISH"
        elif p < s20 and p < s50:
            result["trend"] = "BEARISH"
        else:
            warnings.append("Moving-average trend signals conflict or are neutral.")
    else:
        warnings.append("Insufficient data to determine trend.")
    rsi = indicators.get("rsi_14")
    if rsi is None:
        warnings.append("Insufficient data to determine momentum.")
    else:
        result["momentum"] = "POSITIVE" if rsi > 50 else "NEGATIVE" if rsi < 50 else "NEUTRAL"
    v = indicators.get("volatility_30d")
    if v is None:
        warnings.append("Insufficient data to determine volatility.")
    else:
        result["volatility"] = "LOW" if v < 15 else "HIGH" if v > 30 else "NORMAL"
    avg = result["average_volume"]
    if avg and last and last["volume"] >= 1.5 * avg:
        result["unusual_conditions"].append("Current volume is at least 50% above its last-20-session average.")
    if stock and ("SYNTHETIC" in stock.get("source", "") or "FIXTURE" in stock.get("source", "")):
        warnings.append("Synthetic demonstration prices; not real market data.")
    result["uncertainty"] = " ".join(warnings) if warnings else None
    return result
