# Web page (Streamlit)

A simple local web page for the same analysis the command line runs.

## Start

```powershell
python -m pip install -r requirements-ui.txt
python -m streamlit run ui/app.py
```

The browser opens at http://localhost:8501.

## Modes

| Mode | Data | Keys needed |
|---|---|---|
| Demo (default) | Synthetic, offline | None |
| Live | Real Gemini + Alpaca PAPER (read-only) | `.env` (never typed on the page) |

Live mode also needs a tick-box confirmation.

## Safety

- The page only calls `MultiAgentOrchestrator.analyze()`, so every guardrail still applies
  (prompt check, output filter, final report check, clean traces).
- No buy/sell buttons. Paper orders stay in the command line with `--confirm-paper`.
- One page: ticker buttons, mode, question box, Run, short summary cards, then expandable details.
- Rejected prompts and missing keys show a red message; nothing runs.
- Each run saves a trace in `traces/` (`trace_ui_*.json`, ignored by Git).

## Files

`ui/app.py` (page), `ui/runner.py` (thin helper), `requirements-ui.txt`.

## Panels (matches Section 5.2 of the specification)
Market Overview, Paper Portfolio, News & Sentiment, Risk & Validation, Manual Paper Orders (preview only), Trace.
The order panel calls the existing `preview_limit_order` checks only. Submitting a paper order stays in the command line
(`paper-order ... --confirm-paper`, plus `ENABLE_PAPER_ORDERS=true`). Demo mode previews against the synthetic account.
