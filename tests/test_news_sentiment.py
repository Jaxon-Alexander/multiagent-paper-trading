"""Offline tests for the News & Sentiment provider.

Everything here is a FIXTURE: fictional articles, a scripted stand-in for the LLM and a fixed clock.
No Gemini, Alpaca, news API, API key or network access is used.
"""
import json
import unittest
from datetime import date, datetime, timedelta, timezone

from market_agents.extensions.news_sentiment import (
    ArticleStore, NewsSentimentProvider, fixture_news, run_agent,
    validate_compute_args, validate_news_args)
from market_agents.extensions.sentiment import validate_sentiment_response
from market_agents.orchestrator import MultiAgentOrchestrator

NOW = datetime(2026, 11, 9, 16, 0, tzinfo=timezone.utc)
NEWS_CALL = ('get_market_news', {'symbols': ['QQQ'], 'lookback_hours': 24, 'limit': 10})


def fixed_clock():
    return NOW


class ScriptedLLM:
    """Stand-in for the model. Each step is a list of tool calls or a final JSON answer (dict)."""

    def __init__(self, script):
        self.queue = list(script)
        self.calls = 0
        self.seen = []                      # everything the "model" was shown, for leak checks

    def __call__(self, messages, tools, tool_choice, json_mode):
        self.seen.append(json.dumps(messages))
        step = self.queue.pop(0)
        if isinstance(step, list):
            calls = []
            for name, args in step:
                self.calls += 1
                calls.append({'id': f'call_{self.calls}', 'type': 'function',
                              'function': {'name': name, 'arguments': json.dumps(args)}})
            return {'choices': [{'message': {'role': 'assistant', 'content': None, 'tool_calls': calls}}]}
        return {'choices': [{'message': {'role': 'assistant', 'content': json.dumps(step)}}]}


def assess(*items):
    """items: (article_id, direction, impact) -> compute_sentiment_score call."""
    return [('compute_sentiment_score', {
        'assessments': [{'article_id': a, 'direction': d, 'impact': i} for a, d, i in items],
        'suspected_injection_ids': []})]


def final(score, confidence, volatility=False, events=None, status='OK', scratch='Fixture assessment.'):
    return {'status': status, 'sentiment_score': score, 'confidence': confidence,
            'sentiment_volatility': volatility,
            'market_impact_horizon': 'SHORT_TERM' if status == 'OK' else 'NONE',
            'key_events': events if events is not None else
            [{'description': 'Fixture event', 'type': 'FACT', 'direction': 'NEUTRAL', 'article_ids': ['A1']}],
            'analysis_scratchpad': scratch}


NO_DATA = final(None, 0, status='INSUFFICIENT_DATA', events=[], scratch='CRITICAL_DATA_ABSENT: no usable news.')


def provider(script, fixture_set='normal', **kwargs):
    llm = ScriptedLLM(script)
    return NewsSentimentProvider(llm=llm, news_source='fixtures', fixture_set=fixture_set,
                                 clock=fixed_clock, **kwargs), llm


class ProviderOutcomeTests(unittest.TestCase):
    def check(self, prov, result, ticker='QQQ'):
        validate_sentiment_response(result, ticker=ticker)      # repository contract still holds
        self.assertEqual(result['source'], 'fixture_synthetic_news')
        return result

    def test_positive(self):
        prov, _ = provider([[NEWS_CALL], assess(('A1', 'POSITIVE', 'HIGH'), ('A2', 'POSITIVE', 'HIGH')),
                            final(0.85, 0.6)])
        result = self.check(prov, prov.analyze('QQQ', {}))
        self.assertEqual(result['label'], 'POSITIVE')
        self.assertEqual(result['score'], 0.85)
        self.assertEqual(prov.last_status, 'OK')

    def test_negative(self):
        prov, _ = provider([[NEWS_CALL], assess(('A1', 'NEGATIVE', 'HIGH'), ('A2', 'NEGATIVE', 'HIGH')),
                            final(-0.85, 0.6)])
        result = self.check(prov, prov.analyze('QQQ', {}))
        self.assertEqual(result['label'], 'NEGATIVE')
        self.assertEqual(result['score'], -0.85)

    def test_neutral(self):
        prov, _ = provider([[NEWS_CALL], assess(('A1', 'NEUTRAL', 'LOW'), ('A2', 'NEUTRAL', 'LOW')),
                            final(0.0, 0.3)])
        result = self.check(prov, prov.analyze('QQQ', {}))
        self.assertEqual(result['label'], 'NEUTRAL')

    def test_conflicting_high_impact_news_is_neutral(self):
        prov, _ = provider([[NEWS_CALL], assess(('A1', 'POSITIVE', 'HIGH'), ('A2', 'NEGATIVE', 'HIGH')),
                            final(0.0, 0.3, volatility=True)], fixture_set='conflict')
        result = self.check(prov, prov.analyze('QQQ', {}))
        self.assertEqual(result['label'], 'NEUTRAL')

    def test_unknown_when_no_news(self):
        prov, _ = provider([[NEWS_CALL], assess(), NO_DATA], fixture_set='empty')
        result = self.check(prov, prov.analyze('QQQ', {}))
        self.assertEqual(result['label'], 'UNKNOWN')
        self.assertIsNone(result['score'])
        self.assertEqual(result['evidence'], [])
        self.assertEqual(prov.last_status, 'INSUFFICIENT_DATA')

    def test_invalid_ticker_never_reaches_the_model(self):
        prov, llm = provider([])
        for bad in ('XYZ', '', 'QQQ; DROP', 'msft'):
            result = prov.analyze(bad, {})
            self.assertEqual(result['label'], 'UNKNOWN')
            self.assertEqual(prov.last_status, 'UNSUPPORTED_TICKER')
        self.assertEqual(llm.calls, 0)
        self.assertEqual(llm.seen, [])

    def test_stale_news_becomes_unknown(self):
        # Newest used article is 3 hours old; allow only 1 hour.
        prov, _ = provider([[NEWS_CALL], assess(('A1', 'POSITIVE', 'HIGH'), ('A2', 'POSITIVE', 'HIGH')),
                            final(0.85, 0.6)], max_age_hours=1)
        result = self.check(prov, prov.analyze('QQQ', {}))
        self.assertEqual(result['label'], 'UNKNOWN')
        self.assertEqual(prov.last_status, 'STALE')

    def test_api_failure_becomes_unknown(self):
        def broken_llm(messages, tools, tool_choice, json_mode):
            raise RuntimeError('simulated provider outage')
        prov = NewsSentimentProvider(llm=broken_llm, news_source='fixtures', clock=fixed_clock)
        result = self.check(prov, prov.analyze('QQQ', {}))
        self.assertEqual(result['label'], 'UNKNOWN')
        self.assertEqual(prov.last_status, 'ERROR:RuntimeError')

    def test_model_never_finishing_becomes_unknown(self):
        prov, _ = provider([[NEWS_CALL]] * 12)       # keeps asking for tools, never answers
        result = self.check(prov, prov.analyze('QQQ', {}))
        self.assertEqual(result['label'], 'UNKNOWN')

    def test_missing_keys_fail_closed_without_network(self):
        # Real (non-fixture) mode with no keys set must fail before any network call.
        import os
        from unittest.mock import patch
        with patch.dict(os.environ, {}, clear=True):
            prov = NewsSentimentProvider(clock=fixed_clock)
            result = prov.analyze('QQQ', {})
        self.assertEqual(result['label'], 'UNKNOWN')
        self.assertTrue(prov.last_status.startswith('ERROR:'))


class SafetyTests(unittest.TestCase):
    def test_look_ahead_article_never_shown_to_model(self):
        prov, llm = provider([[NEWS_CALL], assess(), NO_DATA], fixture_set='lookahead')
        result = prov.analyze('QQQ', {})
        self.assertEqual(result['label'], 'UNKNOWN')
        self.assertNotIn('Nasdaq posts', ' '.join(llm.seen))

    def test_prompt_injection_article_excluded_and_not_cited(self):
        prov, llm = provider([[NEWS_CALL], assess(('A1', 'NEGATIVE', 'HIGH')), final(-0.69, 0.45)],
                             fixture_set='injection')
        result = prov.analyze('QQQ', {})
        self.assertEqual(result['label'], 'NEGATIVE')
        self.assertEqual(len(result['evidence']), 1)
        text = ' '.join(llm.seen) + json.dumps(result)
        self.assertNotIn('SECURITY_OVERRIDE', text)
        self.assertNotIn('developer_debug', text)

    def test_paper_position_context_is_never_forwarded(self):
        prov, llm = provider([[NEWS_CALL], assess(('A1', 'POSITIVE', 'HIGH'), ('A2', 'POSITIVE', 'HIGH')),
                              final(0.85, 0.6)])
        prov.analyze('QQQ', {'paper_position': {'qty': 123456789}, 'analysis': {'secret': 'ACCOUNT-XYZ'}})
        self.assertNotIn('123456789', ' '.join(llm.seen))
        self.assertNotIn('ACCOUNT-XYZ', ' '.join(llm.seen))

    def test_evidence_is_attributed_and_bounded(self):
        prov, _ = provider([[NEWS_CALL], assess(('A1', 'POSITIVE', 'HIGH'), ('A2', 'POSITIVE', 'HIGH')),
                            final(0.85, 0.6)])
        result = prov.analyze('QQQ', {})
        self.assertLessEqual(len(result['evidence']), 5)
        for line in result['evidence']:
            self.assertLessEqual(len(line), 300)
            # [judged direction/impact] + publisher + timestamp + headline
            self.assertRegex(line, r'^\[(POSITIVE|NEGATIVE|NEUTRAL)/(HIGH|MEDIUM|LOW)\] \S.* 2026-11-09T\d\d:\d\d:\d\dZ: ')
        self.assertEqual(result['observed_at'], '2026-11-09T13:00:00Z')        # newest used article

    def test_highest_impact_evidence_comes_first(self):
        # A1 is older but HIGH impact; A2 is newer but LOW impact. A1 must be listed first,
        # while observed_at still reports the newest article used (A2).
        prov, _ = provider([[NEWS_CALL], assess(('A1', 'POSITIVE', 'HIGH'), ('A2', 'POSITIVE', 'LOW')),
                            final(0.69, 0.6)])
        result = prov.analyze('QQQ', {})
        self.assertEqual(result['label'], 'POSITIVE')
        self.assertTrue(result['evidence'][0].startswith('[POSITIVE/HIGH] Reuters '))
        self.assertTrue(result['evidence'][1].startswith('[POSITIVE/LOW] Bloomberg '))
        self.assertEqual(result['observed_at'], '2026-11-09T13:00:00Z')

    def test_model_must_copy_python_computed_score(self):
        trace = run_agent('q', 'QQQ', NOW, news_source='fixtures', llm=ScriptedLLM([
            [NEWS_CALL], assess(('A1', 'POSITIVE', 'HIGH'), ('A2', 'POSITIVE', 'HIGH')),
            final(0.99, 0.6),                       # wrong on purpose: rejected, model must retry
            final(0.85, 0.6)]))
        self.assertEqual(trace['final_answer']['sentiment_score'], 0.85)
        self.assertTrue(any(s['type'] == 'correction' for s in trace['steps']))


class ToolArgumentValidationTests(unittest.TestCase):
    """The model's tool arguments are never trusted: Python rejects anything outside the schema."""

    def test_news_arguments_reject_bad_values(self):
        good = {'symbols': ['QQQ'], 'lookback_hours': 24, 'limit': 5}
        bad_cases = [
            {**good, 'symbols': ['XYZ']},                  # symbol not allowed
            {**good, 'symbols': []},                       # no symbols
            {**good, 'symbols': ['QQQ', 'SQQQ', 'AAPL', 'MSFT', 'NVDA', 'AMZN']},   # more than 5
            {**good, 'lookback_hours': 7},                 # not an allowed window
            {**good, 'limit': 0},                          # out of range
            {**good, 'limit': 21},
            {**good, 'limit': True},                       # booleans are not integers here
            {**good, 'end': '2030-01-01'},                 # extra field (no way to ask for future news)
            {'symbols': ['QQQ'], 'lookback_hours': 24},    # missing field
        ]
        for args in bad_cases:
            with self.assertRaises(ValueError, msg=str(args)):
                validate_news_args(args)
        with self.assertRaises(ValueError):
            validate_news_args('not json')

    def test_news_arguments_accept_and_normalise_valid_values(self):
        symbols, lookback, limit = validate_news_args(
            json.dumps({'symbols': ['qqq', 'QQQ', ' nvda '], 'lookback_hours': 48, 'limit': 20}))
        self.assertEqual(symbols, ['QQQ', 'NVDA'])         # upper-cased, de-duplicated
        self.assertEqual((lookback, limit), (48, 20))

    def test_assessments_reject_excluded_unknown_duplicate_and_invalid_items(self):
        store = ArticleStore(NOW)
        for item in fixture_news('injection', ['QQQ'], NOW - timedelta(hours=24), NOW, 10):
            store.add(item)                                # A1 usable, A2 is the injection article
        self.assertIn('A1', store.articles)
        self.assertEqual(store.excluded, {'A2': 'PROMPT_INJECTION'})

        def args(*items, suspected=()):
            return {'assessments': [{'article_id': a, 'direction': d, 'impact': i} for a, d, i in items],
                    'suspected_injection_ids': list(suspected)}

        validate_compute_args(args(('A1', 'NEGATIVE', 'HIGH')), store)                   # valid
        for bad in (args(('A2', 'POSITIVE', 'HIGH')),                                    # excluded article
                    args(('A9', 'POSITIVE', 'HIGH')),                                    # never retrieved
                    args(('A1', 'NEGATIVE', 'HIGH'), ('A1', 'NEGATIVE', 'LOW')),         # duplicate
                    args(('A1', 'BULLISH', 'HIGH')),                                     # bad direction
                    args(('A1', 'NEGATIVE', 'HUGE')),                                    # bad impact
                    args(('A1', 'NEGATIVE', 'HIGH'), suspected=['A1']),                  # flagged as injection
                    args(suspected=['A9'])):                                             # unknown id
            with self.assertRaises(ValueError, msg=str(bad)):
                validate_compute_args(bad, store)


class OrchestratorIntegrationTests(unittest.TestCase):
    def test_provider_plugs_into_orchestrator_offline(self):
        prov, _ = provider([[NEWS_CALL], assess(('A1', 'POSITIVE', 'HIGH'), ('A2', 'POSITIVE', 'HIGH')),
                            final(0.85, 0.6)])
        system = MultiAgentOrchestrator(demo=True, today=date(2026, 11, 2), sentiment=prov)
        result = system.analyze(['QQQ'])
        sentiment = result['symbols']['QQQ']['sentiment']
        self.assertEqual(sentiment['label'], 'POSITIVE')
        self.assertTrue(result['coordination']['paper_only'])
        self.assertFalse(any(e['event'] == 'sentiment_error' for e in system.events))

    def test_failing_provider_leaves_demo_run_intact(self):
        def broken_llm(messages, tools, tool_choice, json_mode):
            raise RuntimeError('simulated outage')
        prov = NewsSentimentProvider(llm=broken_llm, news_source='fixtures')
        system = MultiAgentOrchestrator(demo=True, today=date(2026, 11, 2), sentiment=prov)
        result = system.analyze(['QQQ'])
        self.assertEqual(result['symbols']['QQQ']['sentiment']['label'], 'UNKNOWN')
        self.assertIn('RiskValidationAgent', result['coordination']['agents_invoked'])


if __name__ == '__main__':
    unittest.main()
