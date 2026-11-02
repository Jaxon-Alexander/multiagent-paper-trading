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
    audit = result.get("audit")
    if not result.get("executed") or not isinstance(audit, dict):
        return False
    try:
        for key, expected_key in (("sma20_recomputed", "sma_20"),
                                  ("volatility30_recomputed", "volatility_30d")):
            value = audit[key]
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                    or abs(value - expected[expected_key]) > 0.0002):
                return False
        return audit.get("sma20_match") is True and audit.get("volatility30_match") is True
    except (KeyError, TypeError, ValueError):
        return False


def run_code_audit(client, model: str, stock: dict, indicators: dict, trace, *, demo=False) -> dict:
    bars = stock.get("bars", [])
    if len(bars) < 31 or any(indicators.get(k) is None for k in ("sma_20", "volatility_30d")):
        result = {"status": "skipped", "executed": False, "verified": None,
                  "reason": "At least 31 historical bars are required"}
        trace("audit_skipped", **result)
        return result
    args = {"closing_prices_last_31": [b["close"] for b in bars[-31:]],
            "custom_sma20": indicators["sma_20"],
            "custom_volatility30": indicators["volatility_30d"]}
    if demo:
        result = {"status": "offline_simulation", "executed": False, "verified": None,
                  "reason": "No Gemini Code Execution occurred in scripted demo"}
        trace("audit_demo_only", name="gemini_code_execution", arguments=args, result=result)
        return result

    from google.genai import types
    instruction = (
        "You MUST use built-in Python CODE EXECUTION, not mental arithmetic. "
        "Independently verify the two provided values using ONLY INPUT_JSON. "
        "SMA20 = mean(last 20 prices); volatility = sample stdev of last 30 "
        "simple close-to-close daily returns * sqrt(252)*100. Round both to 4 decimals. "
        "Compare within tolerance 0.0002. Print one line: AUDIT_JSON: followed "
        "by valid JSON with numeric sma20_recomputed, volatility30_recomputed "
        "and boolean sma20_match, volatility30_match. Do not fetch additional data. "
        "INPUT_JSON: " + json.dumps(args)
    )
    try:
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
                "reason": "Independent verification matched" if verified else "Audit not verified or mismatch"}
    except Exception as exc:
        trace("builtin_tool_error", name="gemini_code_execution", arguments=args,
              error=str(exc)[:900])
        return {"status": "error", "executed": False, "verified": False,
                "reason": "Gemini built-in audit request failed; authoritative calculations retained"}
