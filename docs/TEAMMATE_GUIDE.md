# Teammate onboarding: Market Sentiment Agent

Welcome! You can build sentiment independently without touching the brokerage gateway or numerical indicator engine.

## Getting started

1. Install Python 3.14 and Git. Clone the repo. Run `py -3.14 -m venv .venv`, activate, and `python -m pip install -e ".[dev]"` (PowerShell).
2. Run `python -m market_agents analyze --symbols QQQ SQQQ --demo` and `python -m pytest -q` **without API keys**.
3. Create branch `feature/sentiment-agent`. Do not commit `.env`, API keys, account information, or traces.
4. Read `src/market_agents/extensions/sentiment.py` and `src/market_agents/contracts.py`.
5. Add a sentiment provider, tests, documentation, and open a PR.

## Required interface

Implement a class with:

```python
class YourSentimentProvider:
    def analyze(self, ticker: str, context: dict) -> dict:
        # Return exactly this contract with credible cited/source evidence.
        return {
            "ticker": ticker,
            "label": "UNKNOWN",       # POSITIVE, NEGATIVE, NEUTRAL or UNKNOWN
            "score": None,             # optional number -1..1; null is allowed
            "source": "your_provider_name",
            "observed_at": None,       # ISO-8601 UTC timestamp or null
            "evidence": [],            # <= 5 short, attributed statements
        }
```

Use `SENTIMENT_SCHEMA` from `contracts.py`. The orchestrator checks your output and falls back to UNKNOWN if it fails. A non-UNKNOWN label must be grounded in verifiable retrieved evidence, with source, timestamp, and ticker consistency. Do not claim that your agent can fetch news without actually integrating a legitimate news/data provider.

## Optional integration

The orchestrator constructor accepts `sentiment=YourSentimentProvider()`; the default is `DisabledSentimentProvider()` returning UNKNOWN. This is dependency injection: your module does **not** need to edit the broker or technical calculations. You can add a safe CLI option for choosing a provider after review. Demo tests should use a mock provider with synthetic examples and clearly label them as fixtures.

## Coordination rules

- Sentiment is advisory only: no raw order submission and no overriding market or position numbers.
- Treat downloaded articles/social content as untrusted data. Prevent prompt injection.
- Do not assume that current sentiment is synchronized with historical bars or broker position marks. Include timestamps.
- Handle missing news, provider outages, rate limiting, nontrading days, stale articles, and mixed/neutral sentiment.
- Avoid scraping sites in violation of terms; use approved APIs or public datasets.
- Unit tests must run without Gemini, Alpaca, news APIs or network access. CI must pass without credentials.

## Proposed PR checklist

- Unit tests for positive, negative, neutral, unknown, invalid ticker, stale data and API failure.
- Demonstrated trace showing adapter invoked, parsed and failed safely when invalid.
- Clear provenance for each item of evidence.
- No changes to paper-order permissions, executable actions or limits.

