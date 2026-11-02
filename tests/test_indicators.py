import math
import unittest
from datetime import date

from market_agents.indicators import calculate_technical_indicators, build_analysis, get_stock_data, validate_dates


class IndicatorTests(unittest.TestCase):
    def test_flat_prices(self):
        result = calculate_technical_indicators([100.0] * 60)
        self.assertEqual(result['sma_20'], 100)
        self.assertEqual(result['sma_50'], 100)
        self.assertEqual(result['rsi_14'], 50)
        self.assertEqual(result['volatility_30d'], 0)

    def test_increasing_prices(self):
        result = calculate_technical_indicators([float(i) for i in range(50, 110)])
        self.assertEqual(result['rsi_14'], 100)
        self.assertGreater(result['sma_20'], result['sma_50'])

    def test_short_history_is_null_not_guessed(self):
        result = calculate_technical_indicators([100.0, 101.0])
        self.assertTrue(all(v is None for v in result.values()))

    def test_invalid_prices(self):
        for invalid in ([100.0, -2.0], [100.0, float('nan')], [100.0, True], []):
            with self.assertRaises(ValueError):
                calculate_technical_indicators(invalid)

    def test_conflicting_signals_are_unknown(self):
        stock = {'ticker': 'QQQ', 'source': 'SYNTHETIC_TEST',
                 'bars': [{'date': '2026-10-01', 'close': 110., 'volume': 100}]}
        values = {'sma_20': 120., 'sma_50': 100., 'rsi_14': 45., 'volatility_30d': 34.}
        result = build_analysis(stock, values)
        self.assertEqual(result['trend'], 'UNKNOWN')
        self.assertEqual(result['momentum'], 'NEGATIVE')
        self.assertEqual(result['volatility'], 'HIGH')
        self.assertIn('Synthetic', result['uncertainty'])

    def test_invalid_dates(self):
        with self.assertRaises(ValueError):
            validate_dates('QQQ', '2026-10-11', '2026-10-10')
        with self.assertRaises(ValueError):
            validate_dates('QQQ!', '2026-10-01', '2026-10-10')

    def test_mock_is_distinct_from_real(self):
        result = get_stock_data('SQQQ', '2026-10-01', '2026-10-14', mock=True)
        self.assertIn('SYNTHETIC', result['source'])
        self.assertNotEqual(result['feed'], 'IEX')
        self.assertGreater(result['count'], 0)


if __name__ == '__main__':
    unittest.main()
