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
    def setUp(self):                                           # never read the developer's own config.json
        patcher = patch.object(web, "load_config", return_value={})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_api_rejects_levels_outside_the_default_limits_before_worker(self):
        client = web.app.test_client()
        with patch.object(web, "load_config", return_value={}), patch.object(web.subprocess, "Popen") as process:
            for level in (-1, 0, 14, 101, 400, 480):                  # defaults: 15 to 100
                response = client.post("/api/start", json={"sr": 500000, "fec": "3/4", "level": level})
                self.assertEqual(response.status_code, 400)
                self.assertIn("output level", response.json["error"])
            process.assert_not_called()

    def test_users_own_limits_apply(self):
        client = web.app.test_client()
        cfg = {"callsign": "HB9IIU", "locator": "JN36kl", "level_min": 20, "level_max": 480}
        with patch.object(web, "load_config", return_value=cfg), patch.object(web.subprocess, "Popen") as process:
            self.assertEqual(web.level_limits(), (20, 480))
            for level in (0, 19, 481):
                response = client.post("/api/start", json={"sr": 500000, "fec": "3/4", "level": level})
                self.assertEqual(response.status_code, 400)
                self.assertIn("output level", response.json["error"])
            # 480 is inside this user's limits: whatever stops the request now, it is not the level
            response = client.post("/api/start", json={"sr": 500000, "fec": "3/4", "level": 480})
            self.assertNotIn("output level", response.json.get("error", ""))
            process.assert_not_called()

    def test_bad_limits_in_config_fall_back_to_defaults(self):
        for cfg in ({"level_min": 0, "level_max": 100}, {"level_min": 50, "level_max": 20}, {"level_min": "x"}, {"level_max": 9999}):
            with patch.object(web, "load_config", return_value=cfg):
                self.assertEqual(web.level_limits(), web.LEVEL_LIMITS_DEFAULT)

    def test_limits_are_validated(self):
        for lo, hi in ((0, 100), (50, 20), (1, 481), ("a", 100), (15.5, 100), (None, None)):
            self.assertEqual(web.check_limits({"level_min": lo, "level_max": hi})[:2], (None, None), (lo, hi))
            self.assertTrue(web.check_limits({"level_min": lo, "level_max": hi})[2])
        self.assertEqual(web.check_limits({"level_min": "20", "level_max": "480"}), (20, 480, ""))
        self.assertEqual(web.check_limits({"level_min": 1, "level_max": 1}), (1, 1, ""))

    def test_popup_saves_the_limits_and_the_setup_page_keeps_them(self):
        client = web.app.test_client()
        saved = {}
        with patch.object(web, "write_config", side_effect=lambda **kw: saved.update(kw)):
            bad = client.post("/api/level-limits", json={"level_min": 60, "level_max": 30})
            self.assertEqual(bad.status_code, 400)
            self.assertEqual(saved, {})
            ok = client.post("/api/level-limits", json={"level_min": 20, "level_max": 300})
            self.assertEqual((ok.status_code, ok.json["level_min"], ok.json["level_max"]), (200, 20, 300))
            self.assertEqual(saved, {"level_min": 20, "level_max": 300})
        clean, error = web.check_setup({"callsign": "HB9IIU", "locator": "JN36kl", "clock_ahead": 5})
        self.assertEqual(error, "")
        self.assertNotIn("level_min", clean)                              # saving the Setup page must not reset the user's limits
        self.assertNotIn("level_max", clean)

    def test_worker_rejects_unsafe_amplitudes_before_opening_device(self):
        args = ["--source", "clock", "--port", "COM_TEST", "--freq", "2405", "--baud", "500000",
                "--fec", "3/4", "--seconds", "10", "--callsign", "TEST", "--locator", "JN00aa"]
        with patch.object(stream_tx.subprocess, "Popen") as process:
            for level in (0, -1, 481, 600):                               # the firmware's own range is 1 to 480
                with self.assertRaises(SystemExit) as result:
                    stream_tx.main(args + ["--amp", str(level)])
                self.assertEqual(result.exception.code, 2)
            process.assert_not_called()

    def test_slider_bounds(self):
        page = web.app.test_client().get("/").data
        self.assertIn(b'id="level" min="0" max="100" value="0"', page)

    @unittest.skipUnless(shutil.which('node'), 'Node.js required for browser state logic')
    def test_slider_jumps_over_the_levels_below_the_users_lowest(self):
        page = web.app.test_client().get('/').data.decode()
        start = page.index('let levelMin = ')
        end = page.index('updatePlan();', start) + len('updatePlan();\n};')
        logic = page[start:end]
        harness = """
const assert = require('node:assert/strict');
const level = {value: '0'};
const $ = id => level;
const updatePlan = () => {};
"""
        checks = """
const move = v => { level.value = String(v); level.oninput(); return Number(level.value); };
assert.equal(move(1), levelMin);       // up from Off: the first step is the lowest level
assert.equal(move(levelMin - 1), 0);   // down from the lowest level: back to Off
assert.equal(move(7), levelMin);       // a fast drag up lands on the lowest level
assert.equal(move(40), 40);
assert.equal(move(levelMin + 1), levelMin + 1);
assert.equal(move(3), 0);              // a fast drag down lands on Off
assert.equal(move(0), 0);
assert.equal(move(100), 100);
"""
        subprocess.run(['node', '-e', harness + logic + checks], check=True, capture_output=True, text=True)

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
