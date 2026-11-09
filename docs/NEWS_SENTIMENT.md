# News & Sentiment provider

`NewsSentimentProvider` is ported from the INSE 691 Lab 3/4 News & Sentiment Agent.
It is **advisory only**: it never places orders, never touches the broker or indicators, and it never
reads or forwards the `context` argument (which can hold the paper position), only the ticker.

## How it works

1. An LLM agent (Gemini over plain HTTPS, no new dependency) calls two tools:
   `get_market_news` (Alpaca News, window always ends "now") and `compute_sentiment_score`.
2. Python screens every article first. Future-dated, empty, timestamp-less and prompt-injection-looking
   articles are excluded and never shown to the model.
3. The model only judges direction (POSITIVE/NEGATIVE/NEUTRAL) and impact (HIGH/MEDIUM/LOW) per article.
   Python computes the score, confidence and conflict flag, and rejects any final answer that changes them.
4. The adapter converts the result into the six-field contract (`contracts.SENTIMENT_SCHEMA`).

## Mapping to the contract

| Field | Value |
| --- | --- |
| `ticker` | the requested ticker (only QQQ and SQQQ are supported; anything else is UNKNOWN) |
| `score` | Lab `sentiment_score` (-1..1) |
| `label` | conflicting HIGH-impact news -> NEUTRAL; else score >= +0.2 POSITIVE, <= -0.2 NEGATIVE, otherwise NEUTRAL |
| `source` | `alpaca_news` (`fixture_synthetic_news` for offline tests) |
| `observed_at` | timestamp of the newest article used |
| `evidence` | up to 5 lines `"[<DIRECTION>/<IMPACT>] <publisher> <UTC time>: <headline>"`, built by Python from screened articles. The tag is the direction/impact the agent judged for that article. Highest impact first, newest first within the same impact. |

## UNKNOWN (fail-closed) cases

Unsupported ticker, no usable news, model never gives a valid answer, any exception (network, keys, rate
limits), and stale evidence (newest used article older than `max_age_hours`, default 48).
`provider.last_status` says why (for tests and debugging only; it is not part of the contract).

## Configuration

Reads the existing `.env` names: `GEMINI_API_KEY`, `GEMINI_MODEL`, `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`.
Optional: `LLM_BASE_URL` (default: Gemini's OpenAI-compatible endpoint). No new packages.

```python
from market_agents.extensions.news_sentiment import NewsSentimentProvider
MultiAgentOrchestrator(sentiment=NewsSentimentProvider())
```

The CLI is intentionally **not** changed in this PR; selecting a provider from the command line should be
added after review.

## Tests

`tests/test_news_sentiment.py` runs fully offline (fictional fixture articles, a scripted stand-in for the
model, a fixed clock). It covers positive, negative, neutral, mixed, unknown, invalid ticker, stale data,
API failure, look-ahead, prompt injection, no position data leaking to the model, rejection of bad
model tool arguments, and orchestrator integration.

## Limitations

- Lab web-search tool (Google Search grounding) was left out: its results carry no reliable publication time.
- Lab `confidence`, `sentiment_volatility` and `market_impact_horizon` have no slot in the six-field contract.
- News and model quality are not forecasts; thresholds (+/-0.2, 48 hours) are project choices to review.
