"""Narrow input/output guardrails for the paper-trading research application.

These are application-side checks, not LLM instructions. They complement (rather
than replace) the existing JSON schemas, immutable calculations, news screening,
and human-confirmed paper-order boundary.
"""
from __future__ import annotations

from copy import deepcopy
import json
import math
import os
import re
from typing import Any


class GuardrailViolation(ValueError):
    """Raised when an untrusted request or output cannot be accepted safely."""


MAX_USER_PROMPT_CHARS = 2000
FILTERED_TEXT = '[Filtered by output guardrail]'

# Deliberately narrow, high-confidence patterns: this is not a generic keyword
# blacklist. Legitimate financial questions about risk, selling, or RSI remain valid.
_OVERRIDE = re.compile(
    r'(?:\bignore\s+(?:all\s+|any\s+|previous\s+|prior\s+|your\s+|above\s+)*'
    r'(?:system\s+|developer\s+)?(?:instructions|rules|guidelines|safety\s+checks)\b'
    r'|\b(?:system|developer)\s*(?:prompt|override|message|instruction)\s*[:=]'
    r'|\b(?:bypass|disable|remove|turn\s+off)\s+(?:the\s+|all\s+)?'
    r'(?:guardrails?|validation|safety\s+checks|risk\s+limits?|human\s+approval)\b'
    r'|\b(?:reveal|dump|exfiltrate|print|show)\s+(?:the\s+|all\s+|your\s+)?'
    r'(?:system\s+prompts?|api\s+keys?|secret\s+keys?|credentials|access\s+tokens?)\b'
    r'|\byou\s+are\s+now\s+(?:the\s+)?(?:system|developer|admin|unrestricted)\b'
    r'|\bfollow\s+(?:these|my)\s+instructions\s+instead\b'
    r'|<\s*/?\s*(?:system|developer|security_override)\b'
    r'|<\|(?:im_start|im_end)\|>'
    r'|\[\s*INST\s*\])', re.I)

# Never deliver generated execution/trading commands or active embedded content
# as user-facing prose. The separate manual paper-order CLI is unaffected.
_TRADE_DIRECTIVE = re.compile(
    r'\b(?:buy|sell|purchase|short|liquidate|submit|place|execute)\s+'
    r'(?:\d[\d,.]*\s+)?(?:shares?\b|orders?\b|(?:QQQ|SQQQ)\b)', re.I)
_HTML_OR_LINK = re.compile(
    r'<\s*(?:script|iframe|img|form|object|embed|meta)\b'
    r'|\bon(?:error|load|click)\s*='
    r'|\bjavascript:|\bdata:(?:text/html|image/svg\+xml|application/javascript)'
    r'|https?://|!\[[^\]]*\]\([^)]*\)', re.I)
_SECRET_LABEL = re.compile(
    r'\b(?:GEMINI_API_KEY|ALPACA_API_KEY|ALPACA_SECRET_KEY|'
    r'ALPACA_PAPER_API_KEY|ALPACA_PAPER_SECRET_KEY|APCA_API_KEY_ID|'
    r'APCA_API_SECRET_KEY)\b\s*[:=]\s*\S+', re.I)
_SECRET_VALUE = re.compile(r'\b(?:Bearer\s+[A-Za-z0-9._~-]{12,}|sk-[A-Za-z0-9_-]{16,}|AIza[A-Za-z0-9_-]{20,})', re.I)
_UNSAFE_CONTROLS = re.compile(r'[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f\u202a-\u202e\u2066-\u2069]')
_SECRET_ENVS = (
    'GEMINI_API_KEY', 'ALPACA_API_KEY', 'ALPACA_SECRET_KEY',
    'ALPACA_PAPER_API_KEY', 'ALPACA_PAPER_SECRET_KEY',
    'APCA_API_KEY_ID', 'APCA_API_SECRET_KEY',
)


def _contains_secret(text: str) -> bool:
    if _SECRET_LABEL.search(text) or _SECRET_VALUE.search(text):
        return True
    return any(len(value) >= 12 and value in text
               for name in _SECRET_ENVS if (value := os.getenv(name)))


def _unsafe_reason(text: str, *, output: bool) -> str | None:
    if _UNSAFE_CONTROLS.search(text):
        return 'control characters'
    if _contains_secret(text):
        return 'possible credentials'
    if _OVERRIDE.search(text):
        return 'instruction override'
    if output and (_TRADE_DIRECTIVE.search(text) or _HTML_OR_LINK.search(text)):
        return 'unsafe generated content'
    return None


def validate_user_prompt(prompt: str) -> str:
    """Fail closed before ANY agent or broker call if CLI context is dangerous."""
    if not isinstance(prompt, str):
        raise GuardrailViolation('The optional prompt must be text.')
    if len(prompt) > MAX_USER_PROMPT_CHARS:
        raise GuardrailViolation(f'Prompt exceeds {MAX_USER_PROMPT_CHARS} characters.')
    reason = _unsafe_reason(prompt, output=False)
    if reason:
        raise GuardrailViolation(f'User prompt rejected by input guardrail ({reason}).')
    if _TRADE_DIRECTIVE.search(prompt):
        raise GuardrailViolation('Paper trading requests must use the separate approved CLI; '
                                 'analyze --prompt cannot place trades.')
    return prompt.strip()


def sanitize_public_text(text: Any, limit: int = 1200) -> str:
    """Fail *safe* on untrusted prose; never echo dangerous input back to user."""
    if not isinstance(text, str):
        return ''
    if _unsafe_reason(text, output=True):
        return FILTERED_TEXT
    return text[:limit]


def _sanitize_tree(value: Any, path: str = '$', *, max_depth: int = 18) -> tuple[Any, list[str]]:
    """Recursively sanitize values while preserving all trusted numeric fields."""
    if max_depth < 0:
        raise GuardrailViolation('Output exceeded maximum nesting depth.')
    if isinstance(value, str):
        result = sanitize_public_text(value, 4000)
        return result, [path] if result != value else []
    if isinstance(value, dict):
        cleaned, changes = {}, []
        for key, item in value.items():
            if not isinstance(key, str) or _unsafe_reason(key, output=True):
                raise GuardrailViolation('Output contained an invalid field name.')
            cleaned[key], new = _sanitize_tree(item, f'{path}.{key}', max_depth=max_depth - 1)
            changes.extend(new)
        return cleaned, changes
    if isinstance(value, list):
        if len(value) > 20000:
            raise GuardrailViolation('Output array exceeds safety limit.')
        cleaned, changes = [], []
        for index, item in enumerate(value):
            elem, new = _sanitize_tree(item, f'{path}[{index}]', max_depth=max_depth - 1)
            cleaned.append(elem)
            changes.extend(new)
        return cleaned, changes
    if value is None or isinstance(value, (bool, int)):
        return value, []
    if isinstance(value, float):
        if not math.isfinite(value):
            raise GuardrailViolation('Output included a non-finite numeric value.')
        return value, []
    raise GuardrailViolation(f'Output included an unsupported value type at {path}.')


def sanitize_agent_result(result: dict) -> tuple[dict, list[str]]:
    """Clean LLM JSON *before* it enters traces, another agent, or the report."""
    if not isinstance(result, dict):
        raise GuardrailViolation('Agent response must be a JSON object.')
    return _sanitize_tree(result)


def validate_external_sentiment(item: dict) -> None:
    """News headlines are untrusted even if their structure and ticker are valid."""
    for name in ('source', 'evidence'):
        values = item.get(name, []) if name == 'evidence' else [item.get(name, '')]
        if not isinstance(values, list):
            raise GuardrailViolation('Sentiment evidence must be a list.')
        if any(not isinstance(text, str) or _unsafe_reason(text, output=True)
               for text in values):
            raise GuardrailViolation('Sentiment evidence was rejected by content guardrail.')


def guard_analysis_report(report: dict, requested_symbols: list[str]) -> tuple[dict, list[str]]:
    """Verify top-level authority boundaries then scrub every user-visible string.

    Output cleaning never invents or edits financial numbers or trade actions.
    """
    if not isinstance(report, dict) or set(report) != {
        'generated_at_utc', 'mode', 'paper_portfolio', 'paper_portfolio_uncertainty',
        'symbols', 'portfolio_flags', 'coordination',
    }:
        raise GuardrailViolation('Final report schema is not the expected shape.')
    if not isinstance(report['symbols'], dict) or set(report['symbols']) != set(requested_symbols):
        raise GuardrailViolation('Final report tickers differ from validated request.')
    coordination = report['coordination']
    if not isinstance(coordination, dict) or coordination.get('paper_only') is not True:
        raise GuardrailViolation('Final report lacks mandatory paper-only protection.')
    if report['paper_portfolio'] is not None and report['paper_portfolio'].get('paper') is not True:
        raise GuardrailViolation('Final report references an unverified brokerage account.')
    for ticker, entry in report['symbols'].items():
        if not isinstance(entry, dict) or not isinstance(entry.get('analysis'), dict):
            raise GuardrailViolation('Symbol report is missing analysis.')
        a = entry['analysis']
        if a.get('ticker') != ticker:
            raise GuardrailViolation('Symbol report contains a ticker mismatch.')
        for field, valid in [('trend', {'BULLISH', 'BEARISH', 'UNKNOWN'}),
                             ('momentum', {'POSITIVE', 'NEGATIVE', 'NEUTRAL', 'UNKNOWN'}),
                             ('volatility', {'LOW', 'NORMAL', 'HIGH', 'UNKNOWN'})]:
            if a.get(field) not in valid:
                raise GuardrailViolation(f'Invalid {field} classification in report.')
        if entry.get('risk_review', {}).get('status') not in {'VALID', 'REVIEW', 'INSUFFICIENT'}:
            raise GuardrailViolation('Invalid risk-review status.')
    cleaned, changes = _sanitize_tree(deepcopy(report))
    # Detect prior filtering too: the model gateway and local narrative formatter
    # already scrub unsafe prose before the report is assembled.
    def has_filtered_marker(value: Any) -> bool:
        if isinstance(value, str):
            return FILTERED_TEXT in value
        if isinstance(value, dict):
            return any(has_filtered_marker(v) for v in value.values())
        if isinstance(value, list):
            return any(has_filtered_marker(v) for v in value)
        return False

    for ticker, entry in cleaned['symbols'].items():
        if (any(p.startswith(f'$.symbols.{ticker}.') for p in changes)
                or has_filtered_marker(entry)):
            entry['risk_review']['status'] = 'REVIEW'
            prev = entry['analysis'].get('uncertainty') or ''
            notice = 'Potentially unsafe free-text content was removed by output guardrails.'
            entry['analysis']['uncertainty'] = (prev + ' ' + notice).strip()
    json.dumps(cleaned, allow_nan=False)
    return cleaned, changes


def sanitize_trace_event(value: Any) -> Any:
    """Trace events must not persist injected commands, credentials or raw prompts."""
    cleaned, _ = _sanitize_tree(value)
    return cleaned
