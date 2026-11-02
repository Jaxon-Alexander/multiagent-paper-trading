from types import SimpleNamespace
from unittest.mock import patch
import unittest

from market_agents.broker import AlpacaPaperBroker, normalize_position


class FakeTradingClient:
    def get_account(self):
        return SimpleNamespace(equity='10000', cash='8000', buying_power='8000',
                               portfolio_value='10000', trading_blocked=False)

    def get_all_positions(self):
        return [SimpleNamespace(symbol='QQQ', side=SimpleNamespace(value='long'),
                                qty='3', avg_entry_price='500', current_price='510',
                                market_value='1530', cost_basis='1500',
                                unrealized_pl='30', unrealized_plpc='0.02')]


class BrokerTests(unittest.TestCase):
    def setUp(self):
        self.broker = AlpacaPaperBroker(client=FakeTradingClient())

    def test_account_and_positions_are_read_only(self):
        snapshot = self.broker.snapshot()
        self.assertTrue(snapshot['paper'])
        self.assertEqual(snapshot['positions'][0]['portfolio_weight_pct'], 15.3)
        self.assertEqual(snapshot['positions'][0]['unrealized_pl'], 30)
        self.assertNotIn('account_id', snapshot)

    def test_valid_order_preview_does_not_submit(self):
        p = self.broker.preview_limit_order(symbol='QQQ', side='buy', qty=1,
                                            limit_price='100', snapshot=self.broker.snapshot())
        self.assertEqual(p['status'], 'PREVIEW_ONLY')
        self.assertTrue(p['paper'])

    def test_capped_order_value(self):
        with self.assertRaisesRegex(ValueError, 'exceeds project limit'):
            self.broker.preview_limit_order(symbol='QQQ', side='buy', qty=5,
                                            limit_price='400', snapshot=self.broker.snapshot())

    def test_capped_allocation(self):
        with self.assertRaisesRegex(ValueError, 'allocation cap'):
            self.broker.preview_limit_order(symbol='QQQ', side='buy', qty=2,
                                            limit_price='300', snapshot=self.broker.snapshot())

    def test_no_naked_sells(self):
        with self.assertRaisesRegex(ValueError, 'covered'):
            self.broker.preview_limit_order(symbol='SQQQ', side='sell', qty=1,
                                            limit_price='30', snapshot=self.broker.snapshot())

    def test_limit_validation(self):
        for price in ('0', '-3', 'NaN', 'Infinity'):
            with self.assertRaises(ValueError):
                self.broker.preview_limit_order(symbol='QQQ', side='buy', qty=1,
                                                limit_price=price, snapshot=self.broker.snapshot())

    def test_order_rejected_without_explicit_confirmation(self):
        preview = self.broker.preview_limit_order(symbol='QQQ', side='buy', qty=1,
                                                  limit_price='100', snapshot=self.broker.snapshot())
        with self.assertRaises(PermissionError):
            self.broker.submit_limit_order(preview, confirmation=False)
        with patch.dict('os.environ', {'ENABLE_PAPER_ORDERS': 'false'}):
            with self.assertRaises(PermissionError):
                self.broker.submit_limit_order(preview, confirmation=True)


if __name__ == '__main__':
    unittest.main()
