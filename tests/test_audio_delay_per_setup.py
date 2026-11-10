"""Every camera + sound source keeps its own audio delay (saved at Start); Detect and Apply alone save nothing."""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "webapp"), str(ROOT / "host")]
import app as web
import camera


def ask(cfg, camera_name, audio):
    with patch.object(web, "load_config", return_value=cfg):
        return web.app.test_client().get("/api/audio-delay", query_string={"camera": camera_name, "audio": audio}).get_json()


class DelayPerSetup(unittest.TestCase):
    def test_each_setup_has_its_own_delay(self):
        cfg = {"audio_delays": {"C920|auto": 120, "OBS Virtual Camera|CABLE Output": -40}}
        self.assertEqual(ask(cfg, "C920", "auto"), {"delay": 120, "saved": True})
        self.assertEqual(ask(cfg, "OBS Virtual Camera", "CABLE Output"), {"delay": -40, "saved": True})

    def test_a_new_setup_starts_at_zero(self):
        self.assertEqual(ask({"audio_delays": {"C920|auto": 120}}, "C920", "none"), {"delay": 0, "saved": False})

    def test_the_old_single_value_is_used_until_the_table_exists(self):
        self.assertEqual(ask({"audio_delay": 80}, "C920", "auto"), {"delay": 80, "saved": False})

    def test_start_saves_the_delay_for_this_setup_only(self):
        cam = {"name": "C920", "mic": "Microphone (C920)", "usb": True}
        saved = {}
        previous = {"audio_delays": {"Other|auto": 30}}
        with patch.object(camera, "cameras", return_value=[cam]), patch.object(camera, "audio_devices", return_value=["Microphone (C920)"]), \
             patch.object(camera, "stop_previews"), patch.object(web.time, "sleep"), patch.object(web, "load_config", return_value=previous), \
             patch.object(web, "write_config", side_effect=lambda **kw: saved.update(kw)), \
             patch.object(web, "setup_ready", return_value=True), patch.dict(web.conn, {"connected": True, "port": "COM_TEST"}), \
             patch.object(web.subprocess, "Popen", MagicMock()):
            web.app.test_client().post("/api/start", json={"source": "camera", "camera": "C920", "audio": "auto", "delay": 70,
                                                           "sr": 500000, "fec": "3/4", "level": 50, "freq": "2405.250"})
        web.tx.update(state="idle", proc=None)
        self.assertEqual(saved["audio_delays"], {"Other|auto": 30, "C920|auto": 70})


    def test_a_manual_change_is_saved_at_once_for_this_setup(self):
        saved = {}
        with patch.object(web, "load_config", return_value={"audio_delays": {"Other|auto": 30}}),              patch.object(web, "write_config", side_effect=lambda **kw: saved.update(kw)):
            ok = web.app.test_client().post("/api/audio-delay", json={"camera": "C920", "audio": "auto", "delay": -60})
            bad = web.app.test_client().post("/api/audio-delay", json={"camera": "C920", "audio": "auto", "delay": 900})
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(saved["audio_delays"], {"Other|auto": 30, "C920|auto": -60})
        self.assertEqual(bad.status_code, 400)


if __name__ == "__main__":
    unittest.main()
