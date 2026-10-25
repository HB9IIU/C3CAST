"""Keep control bytes out of a clean raw-symbol stream."""
import unittest
from unittest.mock import patch

from esp_link import Link


class Firmware:
    def __init__(self, clean, chunk=65536):
        self.clean = clean
        self.chunk = chunk
        self.pending = b""
        self.writes = []
        self.closed = False

    def write(self, data):
        self.writes.append(data)
        if b"INFO" in data:
            self.pending += b"ESP32DATV 1 PA_GPIO 3" + (b" CLEAN_TX 1" if self.clean else b"") + b"\r\n"
        elif data.startswith(b"QPSKT"):
            target = data.split()[-1]
            self.pending += b"OK QPSKT TARGET " + target + b" PA 0 PA_ARMED 1\r\n"

    def read(self, size):
        size = min(size, self.chunk)
        result, self.pending = self.pending[:size], self.pending[size:]
        return result

    def reset_input_buffer(self):
        self.pending = b""

    def close(self):
        self.closed = True


class CleanTxProtocolTests(unittest.TestCase):
    def finish(self, clean, target):
        firmware = Firmware(clean)
        with patch("esp_link.serial.Serial", return_value=firmware), patch("esp_link.time.sleep"):
            link = Link("fake-port")
            link.start(f"QPSKT 2405.250 1000000 8 60 3 0 {target}")
            firmware.pending += b"TX END symbols=4096 (buffer drained)\r\n"
            summary = link.finish()
        self.assertIn("TX END", summary)
        self.assertTrue(firmware.closed)
        return firmware.writes

    def test_clean_stream_drains_without_appending_symbols(self):
        self.assertNotIn(b"\xa5\xff", self.finish(True, 3000))

    def test_legacy_stream_keeps_legacy_stop(self):
        self.assertEqual(self.finish(False, 3000)[-1], b"\xa5\xff")

    def test_prbs_keeps_explicit_stop_even_on_clean_firmware(self):
        self.assertEqual(self.finish(True, 0)[-1], b"\xa5\xff")

    def test_capabilities_and_ack_may_arrive_in_pieces(self):
        firmware = Firmware(True, chunk=7)
        with patch("esp_link.serial.Serial", return_value=firmware), patch("esp_link.time.sleep"):
            link = Link("fake-port")
            self.assertTrue(link.clean_tx)
            self.assertEqual(link.pa_gpio, 3)
            ack = link.start("QPSKT 2405.250 1000000 8 60 3 0 3000")
        self.assertTrue(ack.endswith("PA_ARMED 1"))
        self.assertTrue(link.streaming)


if __name__ == "__main__":
    unittest.main()
