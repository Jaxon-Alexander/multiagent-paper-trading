"""Explicit JSON contracts; models never control numerical/trading state."""

MARKET_PLAN_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["needs_volume", "reason"],
    "properties": {
        "needs_volume": {"type": "boolean"},
        "reason": {"type": "string", "maxLength": 400},
    },
}
TECHNICAL_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["explanation", "requested_indicators"],
    "properties": {
        "explanation": {"type": "string", "maxLength": 1200},
        "requested_indicators": {"type": "array", "uniqueItems": True,
            "items": {"type": "string", "enum": ["sma_20", "sma_50", "rsi_14", "volatility_30d"]}},
    },
}
POSITION_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["explanation", "observations"],
    "properties": {
        "explanation": {"type": "string", "maxLength": 1200},
        "observations": {"type": "array", "maxItems": 5, "items": {"type": "string", "maxLength": 400}},
    },
}
RISK_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["notes", "request_audit", "reason"],
    "properties": {
        "notes": {"type": "array", "maxItems": 5, "items": {"type": "string", "maxLength": 400}},
        "request_audit": {"type": "boolean"},
        "reason": {"type": "string", "maxLength": 400},
    },
}
SENTIMENT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["ticker", "label", "score", "source", "observed_at", "evidence"],
    "properties": {
        "ticker": {"type": "string", "pattern": "^[A-Z][A-Z0-9.-]{0,9}$"},
        "label": {"type": "string", "enum": ["POSITIVE", "NEGATIVE", "NEUTRAL", "UNKNOWN"]},
        "score": {"type": ["number", "null"], "minimum": -1, "maximum": 1},
        "source": {"type": "string", "maxLength": 150},
        "observed_at": {"type": ["string", "null"]},
        "evidence": {"type": "array", "maxItems": 5, "items": {"type": "string", "maxLength": 300}},
    },
}
