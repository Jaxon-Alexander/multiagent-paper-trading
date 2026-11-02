"""Strict adapter contract and safe default for teammate's future Sentiment Agent.

The provider is explicitly advisory; the main orchestrator owns validation.
"""
from __future__ import annotations
from datetime import datetime
from typing import Protocol

from jsonschema import validate
from ..contracts import SENTIMENT_SCHEMA


class SentimentProvider(Protocol):
    def analyze(self, ticker: str, context: dict) -> dict: ...


class DisabledSentimentProvider:
    def analyze(self, ticker: str, context: dict) -> dict:
        return {'ticker': ticker, 'label': 'UNKNOWN', 'score': None,
                'source': 'disabled', 'observed_at': None, 'evidence': []}


def validate_sentiment_response(item: dict, *, ticker: str) -> None:
    """Reject invalid/stale-looking provenance, never convert it to a trading signal."""
    validate(item, SENTIMENT_SCHEMA)
    if item['ticker'] != ticker:
        raise ValueError('Sentiment provider returned an unexpected ticker')
    if item['label'] != 'UNKNOWN':
        if not item['source'].strip() or item['source'] == 'disabled':
            raise ValueError('Non-UNKNOWN sentiment must identify a data source')
        if not item['evidence']:
            raise ValueError('Non-UNKNOWN sentiment requires cited evidence')
        if not item['observed_at']:
            raise ValueError('Non-UNKNOWN sentiment requires a timestamp')
    if item['observed_at'] is not None:
        try:
            dt = datetime.fromisoformat(item['observed_at'].replace('Z', '+00:00'))
        except ValueError as exc:
            raise ValueError('observed_at must be ISO-8601') from exc
        if dt.tzinfo is None:
            raise ValueError('observed_at must include timezone information')
