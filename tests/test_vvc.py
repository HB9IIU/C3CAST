"""Encoder and web contract tests. No radio, camera or FFmpeg process is started.

Run: .venv-host/Scripts/python.exe -m unittest discover -s tests -v
"""
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "webapp"), str(ROOT / "host")]
import qo100_enc as enc
import stream_tx
import app as web


def command(settings):
    return enc.ffmpeg_command(settings, ["-i", "video", "-i", "audio"], "TEST", "C3CAST")


class VvcEncoding(unittest.TestCase):
    def test_h265_default_is_explicit_h265_for_both_encoders(self):
        for encoder in ("libx265", "hevc_nvenc"):
            with patch.object(enc, "video_encoder", return_value=encoder):
                for source in ("picture", "clock", "camera"):
                    default = stream_tx.source_settings(source, 500, "3/4")
                    explicit = stream_tx.source_settings(source, 500, "3/4", "h265")
                    self.assertEqual(command(default), command(explicit))
                    self.assertEqual(default["encoder"], encoder)
                    self.assertNotIn("libvvenc", command(default))

    def test_vvc_budget_and_unchanged_transport_for_all_profiles(self):
        with patch.object(enc, "video_encoder", return_value="libx265"):
            for sr in (125, 250, 333, 500, 1000):
                for fec in ("3/4", "4/5"):
                    for source in ("picture", "clock", "camera"):
                        with self.subTest(sr=sr, fec=fec, source=source):
                            hevc = stream_tx.source_settings(source, sr, fec)
                            vvc = stream_tx.source_settings(source, sr, fec, "h266")
                            h, v = command(hevc), command(vvc)
                            value = lambda key: v[v.index(key) + 1]
                            self.assertEqual(value("-c:v"), "libvvenc")
                            self.assertEqual(value("-pix_fmt"), "yuv420p10le")
                            self.assertEqual(value("-preset"), "faster")
                            self.assertEqual(value("-period"), "2")
                            self.assertGreaterEqual(int(value("-maxrate")), 1.5 * vvc["video_bps"])
                            budget = (hevc["muxrate"] - hevc["audio_k"] * 1000 - 51520) / 1.12
                            self.assertEqual(vvc["video_bps"], round(budget * .8))
                            self.assertLess(vvc["video_bps"] * 1.2 * 1.12 + vvc["audio_k"] * 1000 + 51520,
                                            vvc["muxrate"])
                            self.assertEqual(h[h.index("-c:a"):], v[v.index("-c:a"):])
                            self.assertEqual(hevc["size"], vvc["size"])
                            self.assertEqual(hevc["fps"], vvc["fps"])
                            for forbidden in ("-minrate", "-x265-params", "-multipass", "-tune", "-profile:v"):
                                self.assertNotIn(forbidden, v)

    def test_vvc_does_not_probe_nvenc_or_apply_clock_bitrate_stretch(self):
        with patch.object(enc, "video_encoder", side_effect=AssertionError("GPU probe")):
            s = enc.settings(500, "3/4", {"rate": 1.3, "multipass": "fullres"}, "h266")
            self.assertEqual(s["rate"], .8)
            self.assertNotIn("-multipass", command(s))

    def test_picture_and_clock_build_use_selected_codec(self):
        for source in ("picture", "clock"):
            settings, cmd = stream_tx.build(source, "test.png", 125, "3/4", "TEST", "JN00aa", 5, 0, codec="h266")
            self.assertEqual(settings["encoder"], "libvvenc")
            self.assertIn("libvvenc", cmd)
            self.assertIn("aac", cmd)

    def test_camera_build_preserves_audio_delay_and_filters(self):
        with patch("camera.inputs_and_filter", return_value=(["-i", "camera"], "overlay", "adelay=100")) as inputs:
            _, cmd = stream_tx.build("camera", "", 125, "3/4", "TEST", "JN00aa", 5, 0,
                                     "webcam", "microphone", 100, "h266")
            inputs.assert_called_once_with("webcam", "microphone", "640x360", 30, "TEST", 100)
            self.assertIn("overlay", cmd)
            self.assertIn("adelay=100", cmd)

    def test_test_executable_override_is_vvc_only_and_ignored_when_frozen(self):
        with patch.dict(os.environ, {"C3CAST_VVC_TEST_FFMPEG": "test-only.exe"}):
            with patch.object(enc.paths, "FROZEN", False):
                self.assertEqual(enc.ffmpeg_path("h266"), Path("test-only.exe"))
                self.assertEqual(enc.ffmpeg_path("h265"), enc.FFMPEG)
            with patch.object(enc.paths, "FROZEN", True):
                self.assertEqual(enc.ffmpeg_path("h266"), enc.FFMPEG)

    def test_capability_check_and_failures(self):
        for output, code, valid in ((" V..... libvvenc VVC encoder", 0, True),
                                    (" V..... libx265 HEVC", 0, False),
                                    (" V..... libvvenc VVC encoder", 1, False)):
            with patch.object(enc.subprocess, "run", return_value=subprocess.CompletedProcess([], code, output, "")):
                if valid:
                    enc.require_vvc()
                else:
                    with self.assertRaisesRegex(ValueError, "libvvenc"):
                        enc.require_vvc()
        with patch.object(enc.subprocess, "run", side_effect=subprocess.TimeoutExpired("ffmpeg", 15)):
            with self.assertRaisesRegex(ValueError, "Cannot check"):
                enc.require_vvc()


class WebCodec(unittest.TestCase):
    def setUp(self):
        self.client = web.app.test_client()

    def test_plan_defaults_and_vvc_selection(self):
        with patch.object(enc, "video_encoder", return_value="libx265"):
            base = "/api/plan?sr=125000&fec=3/4&source=picture"
            self.assertEqual(self.client.get(base).json["codec"], "H.265")
            self.assertEqual(self.client.get(base + "&codec=h266").json["codec"], "H.266")
            self.assertEqual(self.client.get(base + "&codec=bad").status_code, 400)

    def test_unavailable_vvc_rejected_before_starting_worker(self):
        with patch.object(enc, "require_vvc", side_effect=ValueError("missing libvvenc")), \
             patch.object(web.subprocess, "Popen") as process:
            response = self.client.post("/api/start", json={"codec": "h266"})
            self.assertEqual(response.status_code, 400)
            self.assertIn("libvvenc", response.json["error"])
            process.assert_not_called()

    def test_page_has_off_by_default_switch_and_explanation(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'id="vvc" type="checkbox" autocomplete="off"', response.data)
        self.assertIn(b'H.266, in plain language', response.data)


if __name__ == "__main__":
    unittest.main()
