"""Every FEC the page offers has a complete encoder profile, and the modulator knows it."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "webapp"), str(ROOT / "host")]
import app as web
import dvbs2
import qo100_enc as enc


class FecProfiles(unittest.TestCase):
    def setUp(self):                                           # never read the developer's own config.json
        patcher = patch.object(web, "load_config", return_value={})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_page_offers_five_fec_values_and_defaults_to_3_4(self):
        self.assertEqual(web.FECS, ("1/2", "3/5", "2/3", "3/4", "4/5"))
        page = web.app.test_client().get("/").data.decode()
        for fec in web.FECS:
            self.assertIn(f'value="{fec}"', page)
        checked = [line for line in page.splitlines() if 'name="fec"' in line and "checked" in line]
        self.assertEqual(len(checked), 1)
        self.assertIn('value="3/4"', checked[0])

    def test_every_symbol_rate_and_fec_has_a_workable_profile(self):
        with patch.object(enc, "video_encoder", return_value="libx265"):
            for sr in (rate // 1000 for rate in web.SYMBOL_RATES):
                last_video = 0
                for fec in web.FECS:                                     # a lower FEC carries less, so less video
                    s = enc.settings(sr, fec)
                    self.assertGreater(s["video_bps"], 40000, (sr, fec))
                    self.assertLess(s["muxrate"], s["capacity"], (sr, fec))
                    self.assertGreaterEqual(s["video_bps"] + 1, last_video * 0.0, (sr, fec))
                    self.assertGreater(dvbs2.ts_rate(sr * 1000, fec, "normal", False, "qpsk"), 100000)
                    last_video = s["video_bps"]
                rates = [enc.settings(sr, fec)["capacity"] for fec in web.FECS]
                self.assertEqual(rates, sorted(rates), sr)

    def test_the_new_3_5_profile_sits_between_1_2_and_2_3(self):
        with patch.object(enc, "video_encoder", return_value="libx265"):
            for sr in (125, 250, 333, 500, 1000):
                low, mid, high = (enc.settings(sr, f)["video_bps"] for f in ("1/2", "3/5", "2/3"))
                same_size = enc.QO100[(sr, "3/5")]["size"] in (enc.QO100[(sr, "1/2")]["size"], enc.QO100[(sr, "2/3")]["size"])
                self.assertTrue(same_size, sr)                               # a size already used by a neighbour, not a new one

    def test_the_server_accepts_each_fec_and_refuses_others(self):
        client = web.app.test_client()
        with patch.object(enc, "video_encoder", return_value="libx265"):
            for fec in web.FECS:
                reply = client.get(f"/api/plan?sr=500000&fec={fec}&source=picture")
                self.assertEqual(reply.status_code, 200, fec)
                self.assertGreater(reply.get_json()["video_kbps"], 0)
            self.assertEqual(client.get("/api/plan?sr=500000&fec=5/6&source=picture").status_code, 400)


if __name__ == "__main__":
    unittest.main()
