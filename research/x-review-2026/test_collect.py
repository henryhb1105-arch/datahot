import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import collect_x as c

class MemoryLedger(c.Ledger):
    def __init__(self, state):
        self.state = state
    def load(self):
        return copy.deepcopy(self.state), 'sha'
    def save(self, state, sha):
        self.state = state

class BoundsTest(unittest.TestCase):
    def setUp(self):
        sleeper = patch.object(c.time, 'sleep')
        sleeper.start()
        self.addCleanup(sleeper.stop)

    def test_request_reservation_survives_unknown_outcome(self):
        ledger = MemoryLedger({'closed': False, 'requests': {}})
        ledger.reserve('one')
        with self.assertRaises(c.Stop):
            ledger.reserve('one')
        self.assertEqual(ledger.state['requests']['one']['reserved_posts'], 10)

    def test_total_budget_and_closed_gate(self):
        ledger = MemoryLedger({'closed': False, 'requests': {}})
        for i in range(30):
            ledger.reserve(str(i))
        with self.assertRaises(c.Stop):
            ledger.reserve('extra')
        ledger.state['closed'] = True
        with self.assertRaises(c.Stop):
            ledger.reserve('closed')

    def test_failed_budget_write_prevents_reservation(self):
        ledger = MemoryLedger({'closed': False, 'requests': {}})
        with patch.object(ledger, 'save', side_effect=c.Stop('conflict')):
            with self.assertRaises(c.Stop):
                ledger.reserve('not-recorded')
        self.assertEqual(ledger.state['requests'], {})

    def test_query_plan_is_bounded_and_no_expansions(self):
        queries = json.loads((Path(__file__).parent / 'queries.json').read_text())
        self.assertEqual(len(queries), 30)
        for q in queries:
            params = c.search_params(q)
            self.assertEqual(params['max_results'], 10)
            self.assertNotIn('expansions', params)
            self.assertNotIn('next_token', params)
            self.assertLess(len(params['query']), 512)

    def test_no_redirect_credentials(self):
        self.assertIsNone(c.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://elsewhere.invalid'))

    def test_logs_no_credentials_on_auth_failure(self):
        with patch.dict(c.os.environ, {'X_API_KEY':'key', 'X_API_SECRET':'secret'}, clear=True):
            with patch.object(c, 'request', side_effect=c.Stop('http_401')):
                with self.assertRaisesRegex(c.Stop, '^http_401$'):
                    c.app_token()
