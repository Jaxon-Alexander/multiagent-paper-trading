# Architecture and decision boundaries

## Agents

| Role | LLM decision | Trusted code responsibilities |
| --- | --- | --- |
| MarketDataAgent | Explain required price/volume context | CLI supplies ticker/date; Alpaca IEX fetch; range/ticker validation |
| TechnicalAnalysisAgent | Explain trend/momentum/volatility | Python SMA20/50, Wilder RSI14, volatility30, rule labels |
| PositionAnalysisAgent | Interpret an existing **paper** holding and market conditions | Alpaca paper account & positions, P/L and position weights from broker/Python |
| RiskValidationAgent | Explain uncertainty, request extra audit | Flags and validation status, mandatory risk warnings |
| Future Sentiment Agent | Source-grounded sentiment from teammate | Contract/schema validation, timestamp, safe UNKNOWN fallback |

## Orchestration

**Static path:** request → MarketDataAgent → Alpaca bars → trusted calculator → TechnicalAnalysisAgent → (if held) PositionAnalysisAgent → optional Sentiment Agent → RiskValidationAgent → JSON.

**Dynamic branches:** no history skips TechnicalAnalysisAgent; absent/unknown paper holding skips PositionAnalysisAgent; agent error retains deterministic outputs; invalid sentiment becomes UNKNOWN; audit requested via explicit `--audit` or by a flagged Risk Agent decision when data is sufficient. Audit output never replaces Python calculations.

The orchestrator calls one Gemini JSON request per active LLM agent, with model-specific instructions and validated JSON response. The app owns raw numbers and uses only explanatory text from the LLM. Each symbol can have an independent path. A paper portfolio snapshot is read once per analyze command.

**Manual order channel:** completely separate `order-preview` and `paper-order` CLI. There is no model-facing submit-order tool or automatic execution loop. Paper account client is hard-coded with `paper=True`. Limit orders require project caps, broker checks, `.env` opt-in and explicit `--confirm-paper`.

## Deterministic rules

- `BULLISH`: latest historical close strictly above both SMA20 and SMA50.
- `BEARISH`: latest close strictly below both SMAs.
- Other and insufficient trend cases: `UNKNOWN`.
- RSI > 50 positive, < 50 negative, exactly 50 neutral.
- Annualized 30-return simple-return volatility: below 15 LOW; 15–30 NORMAL; above 30 HIGH.
- Additional risks: RSI >=70 / <=30; 30-day volatility >30; portfolio weight >20%; unrealized position loss; mixed QQQ/SQQQ positions.

These thresholds are project rules, not forecasts, liquidity tests, or market consensus. Indicator calculations use historical close data and never intraday prices. Alpaca brokerage position marks need not match IEX historical closes.

## Data security and threats

- Symbols and date range are CLI-owned even if prompts contain hostile text.
- No LLM can update authoritative bars, account positions, calculated P/L, indicators, classifications or execute trades.
- Sentiment/market commentary is lower-trust evidence, never instructions to the orchestrator.
- Trace events omit API credentials and account identifiers, but may contain account equity/position quantities. `traces/` is gitignored; review before sharing.
- Disabled market sentiment returns an explicit UNKNOWN; never invents articles or scores.
- Avoid logging raw orders and secret-bearing API exceptions to shared CI.

## Key design limitations

- Gemini unavailable: retains deterministic results with fallback explanations; does not pretend to have model reasoning.
- Alpaca data unavailable: missing history is represented by null values and UNKNOWN labels.
- Alpaca brokerage unavailable: analysis continues but position status is UNAVAILABLE, not NONE.
- Sentiment not built yet; disabled until teammate provides a reliable, verifiable adapter.
- Paper environment only, no real-money deployment path in this repository.
