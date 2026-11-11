"""Offline tests of the evidence checker and three-indicator Code Execution contract."""
import unittest
from unittest.mock import Mock, patch
from types import ModuleType, SimpleNamespace
from datetime import date

from market_agents.audit import audit_is_verified, run_code_audit
from market_agents.demo import bars as demo_bars
from market_agents.indicators import calculate_technical_indicators


class AuditTests(unittest.TestCase):
    def sample(self):
        stock = demo_bars('QQQ', date(2026, 6, 1), date(2026, 10, 1))
        indicators = calculate_technical_indicators([b['close'] for b in stock['bars']])
        return stock, indicators

    def test_match_requires_all_three_indicators(self):
        _, i = self.sample()
        record = {'executed': True, 'audit': {
            'sma20_recomputed': i['sma_20'], 'sma20_match': True,
            'rsi14_recomputed': i['rsi_14'], 'rsi14_match': True,
            'volatility30_recomputed': i['volatility_30d'], 'volatility30_match': True}}
        self.assertTrue(audit_is_verified(record, i))
        record['audit']['rsi14_match'] = False
        self.assertFalse(audit_is_verified(record, i))
        record['audit']['rsi14_match'] = True
        record['audit']['rsi14_recomputed'] += 1
        self.assertFalse(audit_is_verified(record, i))
        record['audit']['rsi14_recomputed'] = i['rsi_14']
        record['executed'] = False
        self.assertFalse(audit_is_verified(record, i))

    def test_live_audit_prompt_requests_independent_wilder_rsi_code(self):
        stock, i = self.sample()
        audit_json = ('AUDIT_JSON:{"sma20_recomputed":%.4f,"sma20_match":true,'
                      '"rsi14_recomputed":%.4f,"rsi14_match":true,'
                      '"volatility30_recomputed":%.4f,"volatility30_match":true}'
                      % (i['sma_20'], i['rsi_14'], i['volatility_30d']))
        response = Mock()
        part_code = Mock(executable_code=Mock(language='PYTHON', code='print("AUDIT_JSON:...")'),
                         code_execution_result=None)
        part_result = Mock(executable_code=None,
                           code_execution_result=Mock(outcome='OUTCOME_OK', output=audit_json))
        response.candidates = [Mock(content=Mock(parts=[part_code, part_result]))]
        client = Mock()
        client.models.generate_content.return_value = response
        events = []
        # Keep the test credential-free and independent of installed google-genai.
        fake_module = ModuleType('google.genai')
        fake_module.types = SimpleNamespace(
            ToolCodeExecution=lambda: object(),
            Tool=lambda **kwargs: kwargs,
            GenerateContentConfig=lambda **kwargs: kwargs)
        with patch.dict('sys.modules', {'google.genai': fake_module}):
            audit = run_code_audit(client, 'fake-model', stock, i,
                                   lambda evt, **data: events.append((evt, data)))
        self.assertTrue(audit['verified'])
        self.assertTrue(audit['executed'])
        args = client.models.generate_content.call_args.kwargs
        self.assertIn('Wilder RSI14', args['contents'])
        self.assertIn('closing_prices', args['contents'])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0][0], 'builtin_tool')

    def test_insufficient_history_skips_audit(self):
        stock = demo_bars('QQQ', date(2026, 11, 2), date(2026, 11, 3))
        events = []
        result = run_code_audit(Mock(), 'fake-model', stock, {},
                                lambda event, **kw: events.append((event, kw)))
        self.assertEqual(result['status'], 'skipped')
        self.assertFalse(result['executed'])


if __name__ == '__main__':
    unittest.main()
