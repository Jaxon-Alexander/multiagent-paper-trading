# Project roadmap

## Phase 0 — repo foundation (implemented)

- Preserve Lab #3/4 Gemini multi-agent analysis and deterministic indicators.
- Expand market-only analysis to paper account / open positions with independent Position Analysis Agent.
- Read QQQ/SQQQ and any symbol, with synthetic offline demos and no credential-dependent tests.
- Establish future sentiment plug-in interface.
- Separate manual paper LIMIT order submission from agent system; default disabled.

## Phase 1 — team integration

- Add Sentiment Agent with reliable sources, timestamps and schema conformance tests.
- Add structured logging/observability and results dashboard (optional).
- Reconcile IEX daily history vs broker marks; add explicit staleness labeling.
- Expand ETF-aware exposure controls and gross/net exposure representation; daily inverse leverage risk.

## Phase 2 — systematic paper strategy (not implemented)

- Agree upon strategy specification, entry/exit criteria, risk budget, and benchmark.
- Deterministic portfolio and order-size calculator, not LLM arithmetic.
- Backtest with realistic limitations (corporate actions, splits, fees, slippage, volume and survivorship).
- Add human-approved paper-only execution; idempotent client-order IDs, broker reconciliation, position limits, market hours, circuit breakers, kill switch and transaction audit.
- Paper account order monitoring and reconciliation against actual submitted/fill/cancel statuses.

## Phase 3 — evaluation

- Explicit evaluation metrics: Sharpe, drawdown, turnover, realized/unrealized P/L, tracking error to benchmark, forecast calibration and agent failure rates.
- Controlled comparisons: market-only vs +positions vs +sentiment; ablations; prompt injection and missing-data tests.
- Paper trading can only establish simulation behavior; it cannot guarantee real execution results.
