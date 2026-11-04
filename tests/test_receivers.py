"""Receiver ownership, assignment and browser embedding without opening USB hardware."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'webapp'))
import app as web
import receivers
import tuner_assignment
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'webapp' / 'receiver'))
from tuners import QocastBackend
import usb_devices


class Receivers(unittest.TestCase):
    def test_absent_hardware_and_invalid_number(self):
        with patch.object(tuner_assignment, 'slots', return_value=[]):
            client = web.app.test_client()
            self.assertFalse(any(r['available'] for r in client.get('/api/receivers').json['receivers']))
            self.assertEqual(client.post('/api/receivers/1/start', json={}).status_code, 400)
            self.assertEqual(client.post('/api/receivers/3/start', json={}).status_code, 400)

    def test_pico_second_channel_shares_service_and_correct_udp_port(self):
        slots = [dict(tuner='picotuner', channel=n, serial=None, label=f'Pico {n}') for n in (1, 2)]
        with patch.object(receivers, '_workers', {}), patch.object(receivers, '_closing', False), \
             patch.object(tuner_assignment, 'slots', return_value=slots), \
             patch.object(receivers.threading, 'Thread'):
            receivers.start(2)
            first, second = receivers._workers[1], receivers._workers[2]
            self.assertEqual(second['service_port'], first['service_port'])
            self.assertEqual(second['ts_port'], first['ts_port2'])
            self.assertNotEqual(first['port'], second['port'])
            self.assertNotEqual(first['ts_port'], second['ts_port'])

    def test_serial_pinning_and_worker_arguments(self):
        slot = dict(tuner='minitiouner', channel=1, serial='TEST123', label='MiniTiouner TEST123')
        entry = dict(port=19000, service_port=19001, ts_port=19002, ts_port2=19003, url='http://127.0.0.1:19000')
        proc = MagicMock()
        proc.poll.return_value = None
        import tempfile
        with tempfile.TemporaryDirectory() as tmp, patch.object(receivers, '_closing', False), \
             patch.object(receivers.paths, 'RECEIVER_DATA', Path(tmp)), \
             patch.object(receivers.paths, 'RECEIVER', Path(tmp)), \
             patch.object(receivers.subprocess, 'Popen', return_value=proc) as popen, \
             patch.object(receivers.urllib.request, 'urlopen') as open_url:
            (Path(tmp) / 'bin').mkdir()
            (Path(tmp) / 'bin' / 'ffmpeg.exe').touch()
            open_url.return_value.__enter__.return_value.read.return_value = b'{}'
            receivers._launch(1, slot, entry, False)
            self.assertEqual(entry['state'], 'running')
            command = popen.call_args.args[0]
            self.assertIn('--watch-stdin', command)
            self.assertNotIn('--no-autotune', command)  # RX 1 starts on the beacon.
            self.assertEqual(popen.call_args.kwargs['env']['QOCAST_TUNER_SERIAL'], 'TEST123')

    def test_stop_closes_parent_pipe_and_waits(self):
        proc = MagicMock()
        proc.poll.return_value = None
        with patch.object(receivers, '_workers', {1: {'proc': proc}}), patch.object(receivers, '_closing', False):
            receivers.stop()
            proc.stdin.close.assert_called_once()
            proc.wait.assert_called_once()
            proc.terminate.assert_not_called()

    def test_pico_channel_two_can_prepare_primary_without_tuning_rx_one(self):
        backend = QocastBackend('picotuner', None, 19001, 19002, 9750, 0, 'off', 'A',
                                Path('.'), channel=2, primary_port=19000)
        with patch.object(backend, 'api', side_effect=ConnectionError('not started')), \
             patch('tuners.urllib.request.urlopen') as open_url:
            backend.ensure_service()
        request = open_url.call_args.args[0]
        self.assertEqual(request.full_url, 'http://127.0.0.1:19000/prepare')
        self.assertEqual(request.get_header('Origin'), 'http://127.0.0.1:19000')
        self.assertIsNone(backend.service)

    def test_busy_tuner_reports_ownership_conflict_without_waiting_for_timeout(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / 'service.exe'
            exe.touch()
            backend = QocastBackend('minitiouner', exe, 19001, 19002, 9750, 0, 'off', 'A', Path(tmp))
            process = MagicMock(returncode=2)
            process.poll.return_value = 2
            with patch.object(backend, 'api', side_effect=ConnectionError('not started')), \
                 patch('tuners.subprocess.Popen', return_value=process), patch('tuners.time.sleep') as sleep:
                with self.assertRaisesRegex(ValueError, 'Another player or tuner service'):
                    backend.ensure_service()
                sleep.assert_not_called()

    def test_busy_minitiouners_keep_their_distinct_serial_assignments(self):
        devices = [dict(id='minitiouner', count=2, label='MiniTiouner', serials=['FIRST', 'SECOND'])]
        with patch.object(usb_devices, 'detect', return_value=devices), \
             patch.object(tuner_assignment, 'free_tuners', return_value=[]) as free:
            slots = tuner_assignment._enumerate()
        self.assertEqual([s['serial'] for s in slots], ['FIRST', 'SECOND'])
        free.assert_not_called()

    def test_actual_page_places_both_receivers_before_telemetry(self):
        with patch.object(web, 'load_config', return_value={}):
            page = web.app.test_client().get('/').text
        self.assertIn('data-receiver="1"', page)
        self.assertIn('data-receiver="2"', page)
        self.assertLess(page.index('id="receivers"'), page.index('>Telemetry<'))
        self.assertIn('id="rxTargetLabel"', page)
        self.assertEqual(page.count('class="rx-pill"'), 2)
        self.assertNotIn('rx-tuning', page)
        self.assertEqual(page.count('class="rx-eye-display"'), 2)


if __name__ == '__main__':
    unittest.main()
