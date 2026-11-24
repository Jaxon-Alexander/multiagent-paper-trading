"""Streamlit web page for the multi-agent paper-trading research project.

Start (from the project folder, with the .venv active):
    python -m streamlit run ui/app.py

One page, top to bottom: settings -> your question -> Run -> short summary cards -> details.

Safety by design:
  * Starts in DEMO mode (synthetic data, no Gemini/Alpaca calls).
  * LIVE mode needs an explicit tick-box and keys in .env (never typed here).
  * No buy/sell buttons: the Manual Paper Orders panel only PREVIEWS; submitting stays in the command line.
  * All text typed here passes through the project guardrails.
"""
from __future__ import annotations

import json
import re
from datetime import timedelta

import streamlit as st

import history
from runner import preview_order, run_analysis

TICKER_CHOICES = ["QQQ", "SQQQ"]
STATUS_NOTE = {
    "VALID": "VALID – data complete, no risk flag triggered (not a low-risk rating)",
    "REVIEW": "REVIEW – a human should look (risk flag, data error or failed audit)",
    "INSUFFICIENT": "INSUFFICIENT – not enough price data",
}


def status_box(status: str) -> None:
    text = STATUS_NOTE.get(status, status)
    {"VALID": st.success, "REVIEW": st.warning}.get(status, st.error)(text)


def tickers_for_run(chosen: list[str], prompt: str) -> tuple[list[str], str]:
    """Buttons win. With none selected: use QQQ/SQQQ named in the question, else QQQ.

    The page (not the AI) decides, and only from the two allowed tickers, so a question can never
    inject any other symbol.
    """
    if chosen:
        return list(chosen), ""
    named = list(dict.fromkeys(re.findall(r"\b(SQQQ|QQQ)\b", (prompt or "").upper())))
    if named:
        return named, f"No ticker button selected: used {', '.join(named)} because the question names it."
    return ["QQQ"], "No ticker button selected: used QQQ by default."


def choose_tickers() -> list[str]:
    """Clickable ticker buttons (multi-select). Falls back to a dropdown on older Streamlit."""
    label = "Tickers (click to select)"
    if hasattr(st, "pills"):
        picked = st.pills(label, TICKER_CHOICES, selection_mode="multi", default=["QQQ"])
    else:
        picked = st.multiselect(label, TICKER_CHOICES, default=["QQQ"])
    return list(picked or [])


# ---------- results: the five panels from the specification (Section 5.2) ----------

def panel_market(ticker: str, entry: dict, report: dict) -> None:
    a = entry["analysis"]
    ind = a.get("indicators", {})
    live = not report["mode"].startswith("OFFLINE")
    st.markdown(f"**{ticker}**  ·  price **{a.get('current_price')}**  ·  historical-close timestamp "
                f"**{a.get('observation_time')}**  ·  source **{'IEX (Alpaca market data)' if live else 'synthetic demo data'}**")
    st.table([{"SMA 20": ind.get("sma_20"), "SMA 50": ind.get("sma_50"),
               "RSI 14": ind.get("rsi_14"), "Annualized volatility %": ind.get("volatility_30d")}])
    st.markdown(f"Labels: **{a.get('trend')}** trend  ·  **{a.get('momentum')}** momentum  ·  "
                f"**{a.get('volatility')}** volatility")
    if any(ind.get(k) is None for k in ("sma_20", "sma_50", "rsi_14", "volatility_30d")):
        st.caption("Empty value / UNKNOWN = not enough price history "
                   "(the 50-day average needs about 70 calendar days or more).")
    st.markdown("**Technical Analysis Agent**")
    st.write(entry.get("technical_interpretation") or "–")
    st.caption("Numbers and labels are calculated by Python, not by the AI.")


def panel_portfolio(ticker: str, entry: dict, report: dict) -> None:
    pf = report.get("paper_portfolio")
    if report.get("paper_portfolio_uncertainty"):
        st.warning(report["paper_portfolio_uncertainty"])
    if not pf:
        st.write("No paper account data in this run (live mode needs Alpaca paper keys in .env).")
        return
    acct = pf.get("account", {})
    st.markdown(f"Source `{pf.get('source')}`  ·  paper-only: **{pf.get('paper')}**")
    c = st.columns(4)
    c[0].metric("Equity", acct.get("equity"))
    c[1].metric("Cash", acct.get("cash"))
    c[2].metric("Buying power", acct.get("buying_power"))
    c[3].metric("Trading blocked", str(acct.get("trading_blocked")))
    pos = entry.get("paper_position") or {}
    st.markdown(f"**{ticker} position ({pos.get('state', 'not available')})**")
    if pos.get("data"):
        d = pos["data"]
        st.table([{"Side": d.get("side"), "Qty": d.get("qty"), "Avg entry": d.get("avg_entry_price"),
                   "Current": d.get("current_price"), "Unrealized P/L": d.get("unrealized_pl"),
                   "Allocation %": d.get("portfolio_weight_pct")}])
    else:
        st.write("No open position for this ticker (or missing-position state).")
    st.write(pos.get("interpretation") or "")
    if pf.get("positions"):
        st.markdown("**All paper holdings**")
        st.table(pf["positions"])
    for flag in report.get("portfolio_flags") or []:
        st.warning(flag)


def panel_news(ticker: str, entry: dict) -> None:
    s = entry.get("sentiment") or {}
    st.markdown(f"**{ticker}** label **{s.get('label')}**  ·  score {s.get('score')}  ·  "
                f"newest article {s.get('observed_at')}  ·  source {s.get('source')}")
    for line in s.get("evidence") or []:
        st.write(f"- {line}")
    if s.get("label") == "UNKNOWN":
        st.caption("UNKNOWN = the news agent is off, has no fresh evidence, or failed safely.")
    if ticker == "SQQQ" and s.get("label") in ("POSITIVE", "NEGATIVE"):
        st.caption("SQQQ moves opposite to the Nasdaq-100: a POSITIVE market label is bad news for an SQQQ holder.")


def panel_risk(ticker: str, entry: dict) -> None:
    a, risk = entry["analysis"], entry["risk_review"]
    status_box(risk["status"])
    st.markdown("**Warnings**")
    for f in risk.get("deterministic_flags") or ["No risk flags triggered."]:
        st.write(f"⚠ {f}")
    for n in risk.get("agent_notes") or []:
        st.write(f"- Agent note: {n}")
    if a.get("uncertainty"):
        st.info(a["uncertainty"])
    audit = risk.get("audit") or {}
    st.caption(f"Audit status: {audit.get('status')} · verified: {audit.get('verified')} · {audit.get('reason')}")
    st.caption("Provenance: flags and status are set by Python; the Risk agent can only add notes.")


def panel_orders(chosen: list[str], live: bool) -> None:
    st.info("Preview only. Nothing is sent to the broker from this page. "
            "Submitting a paper order stays in the command line with explicit confirmation.")
    with st.form("order_form"):
        c = st.columns(4)
        symbol = c[0].selectbox("Symbol", chosen or TICKER_CHOICES)
        side = c[1].selectbox("Side", ["buy", "sell"])
        qty = c[2].number_input("Quantity (1-100)", min_value=1, max_value=100, value=1, step=1)
        limit = c[3].text_input("Limit price ($)", "")
        go = st.form_submit_button("Preview order (does not send)")
    if go:
        try:
            st.session_state["order_result"] = preview_order(symbol, side, int(qty), limit, live=live)
            if st.session_state.get("save_hist", True):
                history.log_event("order_preview_ok", f"{side} {int(qty)} {symbol} limit {limit} (preview only)")
        except Exception as exc:
            st.session_state.pop("order_result", None)
            if st.session_state.get("save_hist", True):
                history.log_event("order_preview_rejected", f"{side} {int(qty)} {symbol}: {str(exc)[:120]}")
            st.error(f"Order not allowed: {exc}")
    prev = st.session_state.get("order_result")
    if prev:
        st.success("Order passes the project checks (PREVIEW ONLY, not sent).")
        st.table([prev])
        st.markdown("To actually submit this **paper** order, a person must do it deliberately in the command line:")
        st.code(f"python -m market_agents paper-order --symbol {prev['symbol']} --side {prev['side']} "
                f"--qty {prev['qty']} --limit-price {prev['limit_price']} --confirm-paper", language="bash")
        st.caption("It also needs ENABLE_PAPER_ORDERS=true in .env, and the broker re-checks every limit.")


def clear_screen() -> None:
    """Clear button: remove the shown results, order preview and typed question. History is kept."""
    for key in ("last_run", "order_result"):
        st.session_state.pop(key, None)
    st.session_state["user_prompt"] = ""


def fill_download(slot, out: dict | None) -> None:
    """Download button lives under More options; it is filled after the run so it always has the latest report."""
    with slot:
        st.download_button("Download full report (JSON)",
                           data=json.dumps(out["report"], indent=2, default=str) if out else "",
                           file_name="analysis_report.json", mime="application/json",
                           disabled=not out, key="dl_report",
                           help="Available after a run.")


def history_panel() -> None:
    st.caption("Local SQLite database (traces/run_history.db). Question text and account values are never stored.")
    runs = history.list_runs(20)
    if not runs:
        st.info("No saved runs yet. Tick 'Save runs to local history' under More options, then run an analysis.")
    else:
        st.markdown("**Saved runs**")
        st.table(runs)
        ids = [r["id"] for r in runs]
        pick = st.selectbox("Open a saved run", ids, key="history_pick")
        saved = history.get_run(pick)
        if saved:
            st.json(saved, expanded=False)
    ev = history.list_events(10)
    if ev:
        st.markdown("**Recent events** (blocked prompts and order previews)")
        st.table(ev)
    if (runs or ev) and st.button("Clear history", key="history_clear"):
        history.clear_history()
        st.rerun()


def show_results(out: dict) -> None:
    report = out["report"]
    if out.get("ticker_note"):
        st.info(out["ticker_note"])
    (st.warning if report["mode"].startswith("OFFLINE") else st.success)(
        f"Mode: {report['mode']}  ·  {report['generated_at_utc']}")
    symbols = list(report["symbols"])
    ticker = symbols[0]
    if len(symbols) > 1:
        ticker = st.radio("Ticker shown in the panels", symbols, horizontal=True)
    entry = report["symbols"][ticker]

    tabs = st.tabs(["Market Overview", "Paper Portfolio", "News & Sentiment", "Risk & Validation",
                    "Manual Paper Orders", "Trace"])
    with tabs[0]:
        panel_market(ticker, entry, report)
    with tabs[1]:
        panel_portfolio(ticker, entry, report)
    with tabs[2]:
        panel_news(ticker, entry)
    with tabs[3]:
        panel_risk(ticker, entry)
    with tabs[4]:
        panel_orders(symbols, out.get("live", False))
    with tabs[5]:
        st.caption(f"Saved to {out['trace_path']}")
        st.markdown("**Agents invoked:** " + ", ".join(report["coordination"]["agents_invoked"]))
        st.markdown("**Path:** " + " → ".join(report["coordination"]["path"]))
        st.json(out["events"])


# ---------- page ----------

def main() -> None:
    st.set_page_config(page_title="Multi-Agent Market & Paper-Position Analyzer", layout="wide",
                       initial_sidebar_state="expanded")
    # compact header: smaller title and less top padding so the results get more room
    st.markdown(
        "<style>.block-container{padding-top:4.2rem;padding-bottom:1rem;}</style>"
        "<div style='font-size:1.35rem;font-weight:700;line-height:1.2;'>"
        "Multi-Agent Market &amp; Paper-Position Analyzer</div>"
        "<div style='font-size:0.8rem;color:#777;margin:2px 0 6px 0;'>"
        "Decision support only – not investment advice. Paper trading only; this page can preview but never submit orders.</div>",
        unsafe_allow_html=True)

    # ---- left pane: everything the user sets ----
    with st.sidebar:
        chosen = choose_tickers()
        mode = st.radio("Data mode", ["Demo (safe)", "Live (Gemini + Alpaca paper)"], index=0)
        live = mode.startswith("Live")
        confirmed = True
        use_news = False
        if live:
            confirmed = st.checkbox("I understand and want a live run")
            use_news = st.checkbox("Enable News & Sentiment agent",
                                   help="Needs ALPACA_API_KEY / ALPACA_SECRET_KEY (market data) and GEMINI_API_KEY in .env.")
        prompt = st.text_area("Please enter your question", "", height=150, key="user_prompt",
                              placeholder="e.g. Explain what RSI and volatility mean for my paper position")
        b1, b2 = st.columns(2)
        run = b1.button("Run analysis", type="primary", disabled=live and not confirmed)
        b2.button("Clear / Cancel", on_click=clear_screen,
                  help="Clears the results and your question. Clicking it while a run is in progress stops that run.")
        with st.expander("More options"):
            days = st.slider("History (calendar days)", 30, 365, 125, key="history_days",
                             help="Use 90 or more so the 50-day average can be calculated.")
            save_hist = st.checkbox("Save runs to local history", value=True,
                                    help="Small SQLite file in traces/ (not committed). No account values or question text are saved.")
            st.session_state["save_hist"] = save_hist
            dl_slot = st.container()
            use_dates = st.checkbox("Use an exact date range instead")
            d_start = d_end = None
            if use_dates:
                d_end = st.date_input("End date", key="d_end")
                d_start = st.date_input("Start date", value=d_end - timedelta(days=125), key="d_start")

    # ---- right: results ----
    run_error = None
    if run:
        try:
            symbols, note = tickers_for_run(chosen, prompt)
            with st.spinner("Running agents..."):
                st.session_state["last_run"] = run_analysis(symbols, live=live, days=days, prompt=prompt,
                                                            start_date=d_start.isoformat() if d_start else None,
                                                            end_date=d_end.isoformat() if d_end else None,
                                                            news=use_news)
                st.session_state["last_run"]["ticker_note"] = note
                if save_hist:
                    history.save_run(st.session_state["last_run"], prompt_length=len(prompt), news_enabled=use_news)
        except Exception as exc:  # guardrail rejections, missing keys, bad input -> shown safely
            st.session_state.pop("last_run", None)
            if save_hist and "guard" in str(exc).lower():
                history.log_event("prompt_rejected", f"input guardrail, prompt length {len(prompt)}")
            run_error = f"Could not run: {exc}"

    out = st.session_state.get("last_run")
    fill_download(dl_slot, out)
    results_tab, history_tab = st.tabs(["Results", "History"])
    with results_tab:
        if run_error:
            st.error(run_error)
        elif out:
            show_results(out)
        else:
            st.info("Choose a ticker (or type a question), then click Run analysis. "
                    "Past runs are under the History tab.")
    with history_tab:
        history_panel()


main()
