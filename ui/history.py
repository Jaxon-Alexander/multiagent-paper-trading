"""Optional local run history (SQLite) for the web page. New file; no project code is changed.

Why: keeps a small, searchable record of past runs (what was asked, what status each ticker got) so
results can be compared and shown later. It is stored in traces/run_history.db, a folder the project
already keeps out of Git.

Safety rules:
  * Only Python code writes to it; no agent can read or write it.
  * The raw question is NEVER stored, only its length (same rule as the project traces).
  * Account values are NOT stored: paper_portfolio and per-position data are removed before saving.
  * API keys are never passed to this file.
  * Every function fails quietly, so a database problem can never break an analysis run.
"""
from __future__ import annotations

import copy
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[1] / "traces" / "run_history.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_utc TEXT NOT NULL,
    mode TEXT NOT NULL,
    live INTEGER NOT NULL,
    tickers TEXT NOT NULL,
    prompt_length INTEGER NOT NULL,
    news_enabled INTEGER NOT NULL DEFAULT 0,
    trace_path TEXT,
    report_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS symbol_results (
    run_id INTEGER NOT NULL REFERENCES runs(id),
    ticker TEXT NOT NULL,
    status TEXT,
    price REAL, trend TEXT, momentum TEXT, volatility TEXT,
    rsi_14 REAL, sma_20 REAL, sma_50 REAL, volatility_30d REAL,
    flags TEXT, sentiment_label TEXT, sentiment_score REAL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_utc TEXT NOT NULL,
    kind TEXT NOT NULL,
    detail TEXT
);
"""


def _connect(path: Path | str | None = None) -> sqlite3.Connection:
    p = Path(path or DB_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _redact(report: dict) -> dict:
    """Copy of the report without account balances or holdings."""
    safe = copy.deepcopy(report)
    pf = safe.get("paper_portfolio")
    if isinstance(pf, dict):
        safe["paper_portfolio"] = {"source": pf.get("source"), "paper": pf.get("paper"),
                                   "note": "account values not stored in history"}
    for entry in (safe.get("symbols") or {}).values():
        pos = entry.get("paper_position")
        if isinstance(pos, dict):
            pos["data"] = None
    return safe


def save_run(out: dict, *, prompt_length: int, news_enabled: bool = False, path=None) -> int | None:
    try:
        report = out["report"]
        safe = _redact(report)
        with _connect(path) as con:
            cur = con.execute(
                "INSERT INTO runs (created_utc, mode, live, tickers, prompt_length, news_enabled, trace_path, report_json)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (_now(), report.get("mode", ""), int(bool(out.get("live"))), ",".join(report["symbols"]),
                 int(prompt_length), int(bool(news_enabled)), out.get("trace_path"),
                 json.dumps(safe, default=str)))
            run_id = cur.lastrowid
            for ticker, e in report["symbols"].items():
                a, ind = e.get("analysis", {}), e.get("analysis", {}).get("indicators", {})
                s, risk = e.get("sentiment") or {}, e.get("risk_review") or {}
                con.execute(
                    "INSERT INTO symbol_results VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (run_id, ticker, risk.get("status"), a.get("current_price"), a.get("trend"),
                     a.get("momentum"), a.get("volatility"), ind.get("rsi_14"), ind.get("sma_20"),
                     ind.get("sma_50"), ind.get("volatility_30d"),
                     json.dumps(risk.get("deterministic_flags") or []),
                     s.get("label"), s.get("score")))
        return run_id
    except Exception:
        return None


def log_event(kind: str, detail: str = "", *, path=None) -> None:
    """Short audit entries, e.g. 'prompt_rejected' (length only) or 'order_preview'."""
    try:
        with _connect(path) as con:
            con.execute("INSERT INTO events (created_utc, kind, detail) VALUES (?,?,?)",
                        (_now(), kind, detail[:300]))
    except Exception:
        pass


def list_runs(limit: int = 20, *, path=None) -> list[dict]:
    try:
        with _connect(path) as con:
            rows = con.execute(
                "SELECT r.id, r.created_utc AS time, r.mode, r.tickers, r.news_enabled AS news, "
                "(SELECT group_concat(ticker || ':' || COALESCE(status,'-'), '  ') FROM symbol_results s "
                " WHERE s.run_id = r.id) AS statuses "
                "FROM runs r ORDER BY r.id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def get_run(run_id: int, *, path=None) -> dict | None:
    try:
        with _connect(path) as con:
            row = con.execute("SELECT report_json FROM runs WHERE id = ?", (run_id,)).fetchone()
        return json.loads(row["report_json"]) if row else None
    except Exception:
        return None


def list_events(limit: int = 20, *, path=None) -> list[dict]:
    try:
        with _connect(path) as con:
            return [dict(r) for r in con.execute(
                "SELECT created_utc AS time, kind, detail FROM events ORDER BY id DESC LIMIT ?", (limit,))]
    except Exception:
        return []


def clear_history(*, path=None) -> None:
    try:
        with _connect(path) as con:
            con.executescript("DELETE FROM symbol_results; DELETE FROM runs; DELETE FROM events;")
    except Exception:
        pass
