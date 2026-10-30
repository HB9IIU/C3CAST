import sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'webapp'))
import app as web


class PlayerButton(unittest.TestCase):
    def setUp(self):                                           # never read the developer's own config.json
        patcher = patch.object(web, "load_config", return_value={})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_missing_player_hides_button_and_refuses_to_start(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(web, 'PLAYER_EXE', Path(tmp) / 'nope.exe'):
            client = web.app.test_client()
            self.assertEqual(client.get('/api/player').get_json(), {'available': False})
            reply = client.post('/api/player/open', json={})
            self.assertEqual(reply.status_code, 404)
            self.assertIn('H266-Player', reply.get_json()['error'])

    def test_present_player_starts_once_and_detached(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / 'player.exe'
            exe.write_bytes(b'x')
            running = MagicMock()
            running.poll.return_value = None
            with patch.object(web, 'PLAYER_EXE', exe), patch.object(web, 'player', {'proc': None}), \
                 patch.object(web.subprocess, 'Popen', return_value=running) as popen:
                client = web.app.test_client()
                self.assertTrue(client.get('/api/player').get_json()['available'])
                self.assertEqual(client.post('/api/player/open', json={}).get_json(), {'ok': True})
                self.assertEqual(popen.call_args.args[0], [str(exe)])
                self.assertEqual(popen.call_args.kwargs['cwd'], str(tmp))
                self.assertEqual(client.post('/api/player/open', json={}).get_json(), {'ok': True, 'already': True})
                self.assertEqual(popen.call_count, 1)              # a second click does not open a second window

    def test_page_has_the_hidden_button(self):
        page = web.app.test_client().get('/').data
        self.assertIn(b'id="playerBtn" class="btn d-none"', page)


if __name__ == '__main__':
    unittest.main()
