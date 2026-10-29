"""Never let zero reach the host's automatic high-amplitude setting."""
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "webapp"), str(ROOT / "host")]
import app as web
import stream_tx


class OutputLevel(unittest.TestCase):
    def test_api_rejects_zero_negative_and_over_100_before_worker(self):
        client = web.app.test_client()
        with patch.object(web.subprocess, "Popen") as process:
            for level in (-1, 0, 101, 400, 480):
                response = client.post("/api/start", json={"sr": 500000, "fec": "3/4", "level": level})
                self.assertEqual(response.status_code, 400)
                self.assertIn("output level", response.json["error"])
            process.assert_not_called()

    def test_worker_rejects_unsafe_amplitudes_before_opening_device(self):
        args = ["--source", "clock", "--port", "COM_TEST", "--freq", "2405", "--baud", "500000",
                "--fec", "3/4", "--seconds", "10", "--callsign", "TEST", "--locator", "JN00aa"]
        with patch.object(stream_tx.subprocess, "Popen") as process:
            for level in (0, -1, 101, 400):
                with self.assertRaises(SystemExit) as result:
                    stream_tx.main(args + ["--amp", str(level)])
                self.assertEqual(result.exception.code, 2)
            process.assert_not_called()

    def test_slider_bounds(self):
        page = web.app.test_client().get("/").data
        self.assertIn(b'id="level" min="0" max="100" value="0"', page)

    @unittest.skipUnless(shutil.which('node'), 'Node.js required for browser state logic')
    def test_power_resets_when_transmission_ends_but_not_on_idle_polls(self):
        page = web.app.test_client().get('/').data.decode()
        logic = page[page.index('function updateButtons(state)'):page.index('async function poll()')]
        harness = r'''
const assert = require('node:assert/strict');
const elements = new Map();
const $ = id => {
  if (!elements.has(id)) elements.set(id, {value: '50', disabled: false, textContent: '',
    classList: {remove() {}}, setAttribute() {}});
  return elements.get(id);
};
let busy = false, lastState = 'idle', board = true, flashing = false, freqOk = true, setupReady = true;
let videoMode = false;
const isClock = () => !videoMode, isCamera = () => false, isVideo = () => videoMode;
const document = {querySelectorAll: () => []}, window = {};
'''
        checks = r'''
updateButtons('idle');
assert.equal($('level').value, '50'); // A new selection survives idle polling.
assert.equal($('toggle').disabled, false);
for (const ending of ['idle', 'error']) {
  for (const active of ['starting', 'transmitting', 'stopping']) {
    $('level').value = '75';
    updateButtons(active);
    updateButtons(ending);
    assert.equal(Number($('level').value), 0);
    assert.equal($('levelVal').textContent, '0');
    assert.equal($('toggle').disabled, true);
  }
}
videoMode = true;
$('level').value = '10';
$('video').value = '';
updateButtons('idle');
assert.equal($('toggle').disabled, true); // Empty video folder cannot start.
$('video').value = 'sample.mp4';
updateButtons('idle');
assert.equal($('toggle').disabled, false);
'''
        subprocess.run(['node', '-e', harness + logic + checks], check=True, capture_output=True, text=True)


if __name__ == "__main__":
    unittest.main()
