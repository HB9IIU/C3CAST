import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'webapp'))
import app as web
from window_session import WindowLease


class WindowSessions(unittest.TestCase):
    def test_only_one_concurrent_claim_wins(self):
        lease = WindowLease()
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lease.claim, [str(n).zfill(32) for n in range(20)]))
        self.assertEqual(sum(results), 1)

    def test_release_expiry_and_late_release_cannot_remove_new_owner(self):
        now = [0]
        lease = WindowLease(ttl=10, clock=lambda: now[0])
        first, second = 'a'*32, 'b'*32
        self.assertTrue(lease.claim(first))
        self.assertFalse(lease.claim(second))
        now[0] = 9
        self.assertTrue(lease.owns(first, renew=True))
        now[0] = 15
        self.assertFalse(lease.claim(second))
        now[0] = 20
        self.assertTrue(lease.claim(second))
        self.assertFalse(lease.release(first))
        self.assertTrue(lease.owns(second))
        self.assertTrue(lease.release(second))
        self.assertFalse(lease.occupied())

    def test_server_rejects_unowned_control_and_ignores_duplicate_bye(self):
        first, second = 'a'*32, 'b'*32
        with patch.dict(web.app.config, SINGLE_WINDOW=True), patch.object(web, 'WINDOW', WindowLease()), \
             patch.object(web, 'WATCH', {'seen': 0, 'bye': 0}), patch.object(web.receivers, 'start') as start:
            client = web.app.test_client()
            self.assertEqual(client.post('/api/window/claim', json={'token': first}).status_code, 200)
            self.assertEqual(client.post('/api/window/claim', json={'token': second}).status_code, 409)
            self.assertEqual(client.post('/api/receivers/1/start', json={}).status_code, 409)
            self.assertEqual(client.get('/api/receivers').status_code, 409)
            self.assertEqual(client.post('/api/receivers/1/start', json={}, headers={'X-C3CAST-Window': first}).status_code, 200)
            start.assert_called_once_with(1)
            client.post('/api/bye', json={'window_token': second})
            self.assertEqual(web.WATCH['bye'], 0)
            self.assertTrue(web.WINDOW.owns(first))
            client.post('/api/bye', json={'window_token': first})
            self.assertGreater(web.WATCH['bye'], 0)
            self.assertEqual(client.post('/api/window/claim', json={'token': second}).status_code, 200)
            client.post('/api/bye', json={'window_token': first})
            self.assertEqual(web.WATCH['bye'], 0)
            self.assertTrue(web.WINDOW.owns(second))


if __name__ == '__main__':
    unittest.main()
