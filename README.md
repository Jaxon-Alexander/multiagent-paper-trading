# Multi-Agent Market & Paper-Position Analyzer

Team foundation for an agentic **Alpaca paper-trading** research project.

**Current state (v0.1):** analyzes arbitrary US stock/ETF tickers; reads paper holdings and account equity; interprets positions including entry price, unrealized P/L and account concentration; runs four distinct LLM agent roles; preserves deterministic SMA/RSI/volatility and classifications; supports an optional Code Execution audit; and separately supports carefully gated **manual** paper limit orders. **It does not yet autonomously create trading signals or execute trades.**

The initial reproducible symbols are **QQQ** and **SQQQ**, but `--symbols` accepts other tickers. SQQQ targets -3× the **daily** Nasdaq-100 performance; it does not provide -3× performance over an arbitrary holding period.

## Architecture

```text
User CLI (symbols, dates, optional context)
    |
    +--> Python orchestrator (immutable evidence; JSON contracts; traces)
           |
           +---> Alpaca PAPER account/positions (read-only for analysis)
           |
           +---> Market Data Agent --> Alpaca historical daily IEX bars
           |                              |
           |                         Python indicator engine (SMA20/50, Wilder RSI14, volatility30)
           |                              |
           +---> Technical Analysis Agent (LLM interpretation only)
           +---> Position Analysis Agent (only if paper position exists; LLM interpretation only)
           +---> [Sentiment Agent adapter: disabled until teammate implements]
           +---> Risk Validation Agent (deterministic warnings + LLM review)
           +---> optional Gemini Code Execution audit (verification only)
           |
         JSON output + trace

SEPARATE trusted CLI ONLY: order-preview -> paper-order --confirm-paper + ENABLE_PAPER_ORDERS=true
```

The Python orchestrator—not the LLM—controls data retrieval, computation, routing, classification, account math, and order gates. LLMs cannot call the broker's order submission function. Analysis is usable even when the paper account is temporarily unavailable, but it explicitly marks position analysis incomplete.

## Quick start (Windows PowerShell)

Use **Python 3.14** (recommended) or another supported Python version with compatible wheels.

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

Edit `.env`: enter your **Google AI Studio Gemini** key, Alpaca **market-data** key if different, and **Alpaca PAPER** keys. Never paste keys into Git, Issues, PRs, screenshots or traces.

Run a safe **synthetic** demo first (no API keys, no Gemini calls, no orders):

```powershell
python -m market_agents analyze --symbols QQQ SQQQ --demo
python -m market_agents portfolio --demo
python -m pytest -q
```

Live read-only analysis of market data and your **paper positions**:

```powershell
python -m market_agents portfolio
python -m market_agents analyze --symbols QQQ SQQQ --days 125
python -m market_agents analyze --symbols AAPL --days 125 --prompt "Review current trend and open paper position, if any"
python -m market_agents analyze --symbols MSFT --days 125 --audit
```

Explicit date-window test:

```powershell
python -m market_agents analyze --symbols QQQ --start 2026-10-10 --end 2026-10-11
```

Results are JSON to stdout and trace events go to `traces/trace_*.json` (ignored by Git). Price observation dates refer to **historical daily bars**, not live market quotes. Account/position values are from a **different broker endpoint** and may be observed at another time. Historical free-tier IEX volumes are a subset of US market activity, not consolidated volume.

### Paper order workflow (manual and off by default)

To develop execution safely, order placement is **not** part of agent orchestration. Only an explicit human CLI action can submit, limited to **DAY LIMIT orders**. The preview does not submit.

```powershell
python -m market_agents order-preview --symbol QQQ --side buy --qty 1 --limit-price 400
```

For actual paper orders, first review the preview and verify that the **Alpaca paper account** is selected. In `.env`, set `ENABLE_PAPER_ORDERS=true`, then **explicitly** invoke the separate command:

```powershell
python -m market_agents paper-order --symbol QQQ --side buy --qty 1 --limit-price 400 --confirm-paper
```

This sends a **real order to the paper simulator**, not a live account. Project gates include maximum order value ($1,000 by default), maximum position allocation (20% of equity), positive integer quantity (1–100), paper buying power check, no uncovered sells or shorting, paper-only SDK mode, and a fresh account re-check. **An accepted order may fill at the specified price or better, partially fill, remain open, or never fill; this code does not automatically monitor/cancel orders.** Do not set `ENABLE_PAPER_ORDERS=true` unless you intend to allow explicit paper submissions. The Gemini agents never choose the order quantity or submit an order.

## Repository layout

```text
src/market_agents/
    agents.py              # Gemini agent roles and constraints
    orchestrator.py        # per-request routing / shared state
    indicators.py          # Lab #3/#4 deterministic math and Alpaca bars
    broker.py              # paper-only account/positions; separate order gate
    gemini.py              # validated JSON response/retries
    audit.py               # optional Code Execution verifier
    contracts.py           # agent and sentiment JSON schemas
    extensions/sentiment.py# teammate plug-in interface + disabled default
    demo.py                # synthetic fixtures, clearly labeled
    cli.py                 # explicit command-line actions

docs/ARCHITECTURE.md      # technical design and limits
docs/TEAMMATE_GUIDE.md     # how to integrate new sentiment agent
.github/workflows/test.yml # credential-free CI

tests/                   # unit and routing tests
```

## Team workflow

1. Create a branch (`feature/sentiment-agent`, `feature/trading-policy`, etc.) and open a pull request; keep `main` stable.
2. Run `python -m pytest -q` before opening a PR. CI also runs on PRs and pushes.
3. Never commit `.env`, credential files, `traces/`, account snapshots, or log dumps.
4. Changes to brokerage order gates require a second-person PR review. Never permit LLM-selected raw order requests to reach the broker.
5. Sentiment integration details are in [`docs/TEAMMATE_GUIDE.md`](docs/TEAMMATE_GUIDE.md).

## Important limitations

- No automated trade strategy, trade recommendation, automated order loop, backtester, or brokerage order monitor yet.
- Alpaca paper fills simulate trading and do **not** represent actual execution conditions or investment performance.
- The demo uses synthetic market/portfolio data.
- The volatility and RSI thresholds are project conventions, not financial advice or guaranteed predictors.
- Historical IEX bars, broker position marks, and later sentiment sources may have different coverage and timestamps.
- Treat QQQ/SQQQ positions carefully: leveraged inverse daily funds can exhibit path dependence and compounding effects.

