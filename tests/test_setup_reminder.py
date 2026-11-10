"""Without a callsign the reason sits under the Start button (not at the bottom of the page)."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "webapp"), str(ROOT / "host")]
import app as web


def page(ready):
    with patch.object(web, "setup_ready", return_value=ready), patch.object(web, "load_config", return_value={}):
        return web.app.test_client().get("/").get_data(as_text=True)


class SetupReminder(unittest.TestCase):
    def test_no_callsign_message_is_under_the_start_button(self):
        html = page(False)
        reminder = html[html.index('id="powerReminder"'):html.index('id="toggle"')]
        self.assertIn("callsign", reminder)
        self.assertIn('href="/setup"', reminder)
        self.assertNotIn("Set power before Start", reminder)
        self.assertNotIn("setupWarn", html)

    def test_with_callsign_the_power_reminder_stays(self):
        html = page(True)
        self.assertIn("Set power before Start", html)
        self.assertNotIn("No callsign yet", html)


if __name__ == "__main__":
    unittest.main()
