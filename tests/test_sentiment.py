import unittest
from market_agents.extensions.sentiment import DisabledSentimentProvider, validate_sentiment_response


class SentimentContractTests(unittest.TestCase):
    def test_default_is_unknown(self):
        result = DisabledSentimentProvider().analyze('QQQ', {})
        validate_sentiment_response(result, ticker='QQQ')
        self.assertIsNone(result['score'])

    def test_grounded_result_with_timestamp(self):
        result = {'ticker': 'QQQ', 'label': 'POSITIVE', 'score': 0.1,
                  'source': 'example-data-provider', 'observed_at': '2026-11-02T15:00:00Z',
                  'evidence': ['Illustrative fixture only.']}
        validate_sentiment_response(result, ticker='QQQ')

    def test_unsupported_source_rejected(self):
        result = {'ticker': 'QQQ', 'label': 'POSITIVE', 'score': 0.1,
                  'source': 'disabled', 'observed_at': None, 'evidence': []}
        with self.assertRaises(ValueError):
            validate_sentiment_response(result, ticker='QQQ')

    def test_timezone_required(self):
        result = {'ticker': 'QQQ', 'label': 'NEUTRAL', 'score': 0.,
                  'source': 'source', 'observed_at': '2026-11-02T15:00:00',
                  'evidence': ['Illustrative fixture only.']}
        with self.assertRaises(ValueError):
            validate_sentiment_response(result, ticker='QQQ')

    def test_wrong_ticker_rejected(self):
        item = DisabledSentimentProvider().analyze('SQQQ', {})
        with self.assertRaises(ValueError):
            validate_sentiment_response(item, ticker='QQQ')


if __name__ == '__main__':
    unittest.main()
