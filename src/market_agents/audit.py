"""Independent built-in Gemini Code Execution audit; advisory only.

This never supplies authoritative prices or replaces deterministic calculations.
"""
from __future__ import annotations
import json
import math


def extract_execution(response) -> dict:
    codes, outputs = [], []
    for candidate in (getattr(response, "candidates", None) or []):
        for part in (getattr(getattr(candidate, "content", None), "parts", None) or []):
            code = getattr(part, "executable_code", None)
            if code is not None:
                codes.append({"language": str(getattr(code, "language", "PYTHON")),
                              "code": getattr(code, "code", "")})
            result = getattr(part, "code_execution_result", None)
            if result is not None:
                outputs.append({"outcome": str(getattr(result, "outcome", "UNKNOWN")),
                                "output": str(getattr(result, "output", "") or "")})
    audit_result = None
    for item in reversed(outputs):
        for line in reversed(item["output"].splitlines()):
            if line.strip().startswith("AUDIT_JSON:"):
                try:
                    audit_result = json.loads(line.split("AUDIT_JSON:", 1)[1].strip())
                except ValueError:
                    pass
                break
        if audit_result is not None:
            break
    return {"executed": bool(codes and outputs and any("OK" in x["outcome"] for x in outputs)), "code": codes,
            "outputs": outputs, "audit": audit_result}


def audit_is_verified(result: dict, expected: dict) -> bool:
    """Accept only executed Python outputs matching ALL three deterministic indicators."""
    audit = result.get("audit")
    if not result.get("executed") or not isinstance(audit, dict):
        return False
    checks = (
        ("sma20_recomputed", "sma_20", "sma20_match"),
        ("rsi14_recomputed", "rsi_14", "rsi14_match"),
        ("volatility30_recomputed", "volatility_30d", "volatility30_match"),
    )
    try:
        for recomputed_key, expected_key, matched_key in checks:
            value = audit[recomputed_key]
            reference = expected[expected_key]
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or isinstance(reference, bool) or not isinstance(reference, (int, float))
                    or not math.isfinite(value) or not math.isfinite(reference)
                    or abs(value - reference) > 0.0002
                    or audit.get(matched_key) is not True):
                return False
        return True
    except (KeyError, TypeError, ValueError):
        return False


def run_code_audit(client, model: str, stock: dict, indicators: dict, trace, *, demo=False) -> dict:
    """Execute a model-generated Python verification without changing trusted calculations.

    The RiskValidationAgent controls *whether* this is called. It never supplies
    Python source code, price data, indicator values, or trading permissions.
    """
    bars = stock.get("bars", [])
    required = ("sma_20", "rsi_14", "volatility_30d")
    if len(bars) < 31 or any(indicators.get(k) is None for k in required):
        result = {"status": "skipped", "executed": False, "verified": None,
                  "reason": "At least 31 historical bars and three indicators are required"}
        trace("audit_skipped", **result)
        return result

    args = {"closing_prices": [b["close"] for b in bars],
            "custom_sma20": indicators["sma_20"],
            "custom_rsi14": indicators["rsi_14"],
            "custom_volatility30": indicators["volatility_30d"]}
    if demo:
        result = {"status": "offline_simulation", "executed": False, "verified": None,
                  "reason": "No Gemini Code Execution occurred in scripted demo"}
        trace("audit_demo_only", name="gemini_code_execution", arguments=args, result=result)
        return result

    instruction = (
        "You MUST use built-in Python CODE EXECUTION to independently recalculate all THREE "
        "indicators from INPUT_JSON. Do not do mental arithmetic, fetch prices, or use "
        "the provided custom values as the calculations. Use only Python standard library. "
        "Prices are chronological, oldest first. SMA20: arithmetic mean of last 20 prices. "
        "Volatility30: sample standard deviation (statistics.stdev) of last 30 SIMPLE "
        "close-to-close returns (price_today/price_yesterday - 1), multiplied by sqrt(252)*100. "
        "Wilder RSI14: calculate close-to-close changes for ALL prices; take simple mean "
        "of gains and losses from the FIRST 14 changes, then recursively update each "
        "remaining gain and loss as (old_average*13 + new_value)/14. "
        "If average_loss==0: RSI=100 when average_gain>0, otherwise 50. "
        "If average_gain==0 but average_loss>0: RSI=0. "
        "Otherwise RSI=100 - 100/(1 + average_gain/average_loss). "
        "Round all THREE recomputed indicators to four decimals. "
        "Compare each recomputed number to its corresponding custom value with absolute "
        "tolerance 0.0002. PRINT EXACTLY ONE LINE starting AUDIT_JSON: followed by a JSON "
        "object with numbers sma20_recomputed, rsi14_recomputed, volatility30_recomputed, "
        "and booleans sma20_match, rsi14_match, volatility30_match. "
        "Do not modify broker positions or place orders. "
        "INPUT_JSON: " + json.dumps(args, separators=(",", ":"))
    )
    try:
        from google.genai import types
        response = client.models.generate_content(
            model=model, contents=instruction,
            config=types.GenerateContentConfig(
                tools=[types.Tool(code_execution=types.ToolCodeExecution())], temperature=0))
        parsed = extract_execution(response)
        verified = audit_is_verified(parsed, indicators)
        status = "passed" if verified else "failed"
        trace("builtin_tool", name="gemini_code_execution", arguments=args,
              result=parsed, executed=parsed["executed"], verified=verified, status=status)
        return {"status": status, "executed": parsed["executed"], "verified": verified,
                "reason": "Independent SMA, RSI, and volatility verification matched"
                          if verified else "Audit not verified or a mismatch was detected"}
    except Exception as exc:
        trace("builtin_tool_error", name="gemini_code_execution", arguments=args,
              error=str(exc)[:900])
        return {"status": "error", "executed": False, "verified": False,
                "reason": "Gemini built-in audit request failed; authoritative calculations retained"}
