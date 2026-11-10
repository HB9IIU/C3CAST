"""Setup option: show the scrolling text and band at the bottom of the camera picture (the callsign and clock at the top always stay)."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "webapp"), str(ROOT / "host")]
import app as web
import camera


class MarqueeOption(unittest.TestCase):
    def test_off_leaves_only_the_top_banner(self):
        on, off = camera.overlay_filter("HB9IIU"), camera.overlay_filter("HB9IIU", {"marquee": False})
        self.assertIn("marquee.txt", on)
        self.assertNotIn("marquee.txt", off)
        self.assertEqual(off.count("drawbox"), 1)                       # the top band only
        self.assertIn("banner_left.txt", off)                           # the callsign stays
        self.assertIn("banner_right.txt", off)                          # and the clock

    def test_no_banner_keeps_the_bottom_and_local_time_changes_the_clock(self):
        no_banner = camera.overlay_filter("HB9IIU", {"banner": False})
        self.assertNotIn("banner_left.txt", no_banner)
        self.assertIn("marquee.txt", no_banner)
        camera.overlay_filter("HB9IIU", {"local_time": True})
        self.assertIn("LOCAL", (camera.FOLDER / "banner_right.txt").read_text(encoding="utf-8"))
        camera.overlay_filter("HB9IIU")
        self.assertIn("UTC", (camera.FOLDER / "banner_right.txt").read_text(encoding="utf-8"))

    def test_nothing_at_all_is_still_a_valid_filter(self):
        self.assertEqual(camera.overlay_filter("HB9IIU", {"banner": False, "marquee": False}), "null")

    def test_setup_keeps_the_picture_options_when_not_sent(self):
        with patch.object(web, "load_config", return_value={"banner": False, "local_time": True}):
            kept, _ = web.check_setup({"callsign": "HB9IIU", "locator": "JN36kl"})
        self.assertFalse(kept["banner"])
        self.assertTrue(kept["local_time"])

    def test_setup_saves_it_and_keeps_it_when_not_sent(self):
        with patch.object(web, "load_config", return_value={"marquee": False}):
            kept, _ = web.check_setup({"callsign": "HB9IIU", "locator": "JN36kl"})
            on, _ = web.check_setup({"callsign": "HB9IIU", "locator": "JN36kl", "marquee": True})
        self.assertFalse(kept["marquee"])
        self.assertTrue(on["marquee"])

    def test_it_is_on_by_default(self):
        with patch.object(web, "load_config", return_value={}):
            self.assertTrue(web.get_setup()["marquee"])


if __name__ == "__main__":
    unittest.main()
